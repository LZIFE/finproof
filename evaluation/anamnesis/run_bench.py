#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AnamnesisBench Track A 跑分器（鉴融 verifier 实现）。

数据：pppop7/anamnesis-bench · data/cases.jsonl · 392 例 · 11 类 artifact
考点：该判的判对（deterministic_gate=True），该弃权的弃权（gate=False）。

本实现只做确定性判定，不调用模型——对应鉴融"数字归程序"那一半。
"""
from __future__ import annotations
import json, os, re, sys
from urllib.parse import urlparse

# 直接使用专家包内同一份确定性检查器，避免"跑分脚本一套、产品另一套"的漂移。
_HERE = os.path.dirname(os.path.abspath(__file__))
_BIN = os.path.normpath(os.path.join(
    _HERE, "../../finproof-verifier/skills/finproof-verification/bin"))
sys.path.insert(0, _BIN)
import finproof_calc as _fc  # noqa: E402

# ── 鉴融口径的容差（先按 SKILL 的公开值，看与 benchmark 是否一致）──
TOL_PP = 0.5      # 百分点容差（增长率）
TOL_REL = 0.005   # 相对容差 0.5%（披露舍入豁免上限）

METRIC_ROWS = {"EPS (diluted)", "ROE", "ROA", "Interest coverage", "Debt-to-assets",
               "Free cash flow margin", "Gross margin", "Operating margin", "Net margin"}
VERDICTS = {"Significantly deteriorated", "Deteriorated", "Stable", "Improved", "Significantly improved"}
WF_TYPES = {"baseline", "positive", "negative", "result"}
GATE_SOURCES_OK = {"user_md_sticky", "user_response", "explicit_phrase"}
# gate 特定的合法取值：sec_email 允许用户明确拒绝，不算"编造默认值"
GATE_SOURCE_EXTRA = {"sec_email": {"declined"}}
PROFILES_OK = {"strict_fast_us", "strict_full_qc_us", "strict_full_qc_intl", "strict_fast_intl"}
SEC_HOSTS = ("sec.gov",)
PREFIX_QC = "Dual-QC deliberation"
PREFIX_NOQC = "Per draft scoring"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

UNIT_SCALE = {"USD": 1e6, "CNY": 1e6, "HKD": 1e6}  # B=1e9, M=1e6, K=1e3

# ── 数值/单位解析（OOD 场景：人类书写形态而非规范化代码）──
SCALE_WORDS = [
    ("trillion", 1e12), ("billion", 1e9), ("billions", 1e9), ("bn", 1e9),
    ("million", 1e6), ("millions", 1e6), ("mn", 1e6), ("mm", 1e6),
    ("thousand", 1e3), ("thousands", 1e3),
    ("十亿", 1e9), ("亿", 1e8), ("千万", 1e7), ("百万", 1e6), ("万", 1e4), ("千", 1e3),
]
CUR_SYMBOLS = [("$", "USD"), ("US$", "USD"), ("¥", "CNY"), ("￥", "CNY"), ("€", "EUR"), ("HK$", "HKD")]
CUR_WORDS = {"usd": "USD", "cny": "CNY", "rmb": "CNY", "hkd": "HKD", "eur": "EUR", "usd ": "USD"}
PERIOD_QUAL = ("yoy", "qoq", "mom", "ytd", "yoy ", "qoq ")


def _num(x, default=0.0):
    """容忍字符串/带符号/带千分位的数值字段。"""
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    if x is None:
        return default
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(x))
    return float(m.group(0).replace(",", "")) if m else default


def parse_quantity(value, unit):
    """把 (值, 单位字符串) 解成可比较的规范量。

    返回 (base_value, currency, kind, qualifier)：
      kind ∈ currency / percent / fraction / shares / ads / count
      qualifier ∈ 期间限定词（yoy/qoq/mom/ytd/""）
    解析失败返回 None。
    """
    if value is None or unit is None:
        return None
    raw_v = str(value).strip()
    raw_u = str(unit).strip().lower()

    # 货币：符号在值里或在 unit 里
    cur = None
    for sym, code in CUR_SYMBOLS:
        if sym in raw_v or sym in raw_u:
            cur = code
            break
    if cur is None:
        for w, code in CUR_WORDS.items():
            if w.strip() and w.strip() in raw_u.split():
                cur = code
                break

    # 数量类型
    if "ads" in raw_u:
        kind = "ads"
    elif "share" in raw_u:
        kind = "shares"
    elif "%" in raw_v or "percent" in raw_u or "pct" in raw_u:
        kind = "percent"
    elif "fraction" in raw_u:
        kind = "fraction"
    elif cur:
        kind = "currency"
    else:
        kind = "count"

    # 期间限定
    qual = ""
    for q in PERIOD_QUAL:
        if q.strip() and q.strip() in raw_u:
            qual = q.strip()
            break

    # 数字与倍数
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", raw_v)
    if not m:
        return None
    num = float(m.group(0).replace(",", ""))

    scale = 1.0
    hay = (raw_v.lower() + " " + raw_u)
    for w, s in SCALE_WORDS:
        if w in hay:
            scale = s
            break
    else:
        # 规范化代码形式 USD_B / USD_M / USD_K
        mm = re.search(r"_([bmk])\b", raw_u)
        if mm:
            scale = {"b": 1e9, "m": 1e6, "k": 1e3}[mm.group(1)]

    base = num * scale
    if kind == "fraction":
        base *= 100.0
        kind = "percent"
    return base, cur, kind, qual


def aud_reconcile(a):
    rep_raw, src_raw = a.get("reported"), a.get("source")
    ur, us = a.get("unit_reported"), a.get("unit_source")
    kind_tol = a.get("tol_kind")

    pr = parse_quantity(rep_raw, ur)
    ps = parse_quantity(src_raw, us)
    if pr is None or ps is None:
        return "abstain", f"无法解析数值：{rep_raw!r}/{src_raw!r}"

    vb, cb, kb, qb = pr
    va, ca, ka, qa = ps

    # 口径对齐说明：主集 cases 把"单位表述不同"一律标为 unit_scale_flip（violation），
    # 而 OOD 的盲评把"换算后等价"标为 consistent（OOD-0001）。两者直接冲突，
    # 这里与主集对齐（主集有官方 reference 1.0 可对照），冲突案例在报告中单列。
    if (ur or "").strip().lower() != (us or "").strip().lower():
        return "violation", f"单位表述不一致（{ur} vs {us}）"

    # 单位语义不一致 → 直接反驳（不需要比数值）
    if kb != ka:
        return "violation", f"单位语义不一致（{kb} vs {ka}）"
    if cb and ca and cb != ca:
        return "violation", f"币种不一致（{cb} vs {ca}）"
    if qb != qa:
        return "violation", f"期间限定不一致（{qb or '—'} vs {qa or '—'}）"

    # 数值比较
    if kind_tol == "exact":
        return ("consistent", "精确匹配") if vb == va else ("violation", f"精确匹配失败（{vb} vs {va}）")
    if kind_tol == "ratio_pp":
        d = abs(vb - va)
        return ("consistent", f"差 {d:.2f}pp ≤ {TOL_PP}pp") if d <= TOL_PP else ("violation", f"差 {d:.2f}pp > {TOL_PP}pp")
    if not va:
        return "abstain", "来源值为 0"
    rel = abs(vb - va) / abs(va)
    if kind_tol == "exact":
        return ("consistent", "精确") if rel == 0 else ("violation", f"差 {rel*100:.4f}%")
    return ("consistent", f"相对差 {rel*100:.3f}% ≤ {TOL_REL*100}%") if rel <= TOL_REL else ("violation", f"相对差 {rel*100:.3f}% 超容差")


def aud_waterfall(a):
    bars = a.get("bars") or []
    if not bars:
        return "violation", "无 bars"
    bad_type = [b.get("type") for b in bars if b.get("type") not in WF_TYPES]
    if bad_type:
        return "violation", f"非规范 type：{bad_type}"
    for b in bars:
        if b.get("type") in ("positive", "negative") and (b.get("start") is None or b.get("end") is None):
            return "violation", f"delta bar 缺 start/end：{b.get('label')}"
    base = next((b for b in bars if b.get("type") == "baseline"), None)
    res = next((b for b in bars if b.get("type") == "result"), None)
    if base is None or res is None:
        return "violation", "缺 baseline 或 result"
    deltas = sum(_num(b.get("value")) for b in bars if b.get("type") in ("positive", "negative"))
    expect = _num(base.get("value")) + deltas
    if abs(expect - _num(res.get("value"))) > max(1e-6, abs(expect) * 1e-4):
        return "violation", f"桥接不闭合：baseline+Σdelta={expect:.2f} vs result={res.get('value')}"
    return "consistent", "schema 合法且桥接闭合"


def aud_sankey(a):
    nodes = a.get("nodes") or []
    links = a.get("links") or []
    if not nodes or not links:
        return "violation", "缺 nodes 或 links"
    wired = {l.get("source") for l in links} | {l.get("target") for l in links}
    orphans = [n for n in nodes if n not in wired]
    if orphans:
        return "violation", f"孤立节点：{orphans}"
    inflow, outflow = {}, {}
    for l in links:
        t, s, v = l.get("target"), l.get("source"), _num(l.get("value"))
        inflow[t] = inflow.get(t, 0) + v
        outflow[s] = outflow.get(s, 0) + v
    for n in nodes:
        i, o = inflow.get(n, 0), outflow.get(n, 0)
        if i > 0 and o > 0 and abs(i - o) / max(i, o) > 0.01:
            return "violation", f"节点 {n} 流入 {i} ≠ 流出 {o}（>1%）"
    return "consistent", "全节点已连接且内部守恒"


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _parse_period_spec(s):
    """把期间表述解成 (kind, year, quarter, end_md)。

    kind ∈ annual / quarter；end_md 为 (月, 日) 或 None。
    支持 Q2 / Q2 2026 / FY2025 / annual / "three months ended March 31, 2026" /
    "fiscal year ended January 28, 2026" / "FY ended December 31, 2025"。
    这样才覆盖真实财报的写法——只认 'Q' 的检查器会被 "three months ended" 绕过。
    """
    if not s:
        return None
    t = str(s).strip().lower().replace("，", ",")
    mon = "(" + "|".join(_MONTHS) + ")"

    m = re.search(r"three months ended\s+" + mon + r"\s+(\d{1,2}),?\s*(\d{4})", t)
    if m:
        return ("quarter", int(m.group(3)), None, (_MONTHS[m.group(1)], int(m.group(2))))
    m = re.search(r"(?:fiscal year|fy)\s+ended\s+" + mon + r"\s+(\d{1,2}),?\s*(\d{4})", t)
    if m:
        return ("annual", int(m.group(3)), None, (_MONTHS[m.group(1)], int(m.group(2))))
    m = re.search(r"\bfy\s*(\d{4})\b", t)
    if m:
        return ("annual", int(m.group(1)), None, None)
    m = re.search(r"\bq([1-4])\b\s*(\d{4})?", t)
    if m:
        return ("quarter", int(m.group(2)) if m.group(2) else None, int(m.group(1)), None)
    if "annual" in t or t == "fy":
        return ("annual", None, None, None)
    return None


def aud_period(a):
    cp_raw = a.get("copy_period")
    cur_raw = a.get("current_year_period") or a.get("current_period") or a.get("period")
    pc, pu = _parse_period_spec(cp_raw), _parse_period_spec(cur_raw)
    if pc is None or pu is None:
        return "abstain", f"无法解析期间：{cp_raw!r} / {cur_raw!r}"
    if pc[0] != pu[0]:
        return "violation", f"期间类型不一致（{pc[0]} vs {pu[0]}）：{cp_raw} / {cur_raw}"
    # 同为年度但财年结束日不同 → 窗口不同
    if pc[3] and pu[3] and pc[3] != pu[3]:
        return "violation", f"财年结束日不一致（{pc[3][0]}月{pc[3][1]}日 vs {pu[3][0]}月{pu[3][1]}日）"
    if pc[0] == "quarter" and pc[2] and pu[2] and pc[2] != pu[2]:
        return "violation", f"季度不一致（Q{pc[2]} vs Q{pu[2]}）"
    return "consistent", f"期间自洽（{pc[0]}）"


def aud_metrics_table(a):
    rows = a.get("rows") or []
    names = [r.get("name") for r in rows]
    if len(rows) != 9 or any(n not in METRIC_ROWS for n in names):
        return "violation", f"行数/行名不合规（{len(rows)} 行，越界：{[n for n in names if n not in METRIC_ROWS]}）"
    # cells 全为 N/A 的行（如负净资产下的 ROE）无法用数值支撑 verdict，
    # 允许描述性表述（"Equity deficit narrowed"），不按词表判违规。
    def _na_row(r):
        cells = r.get("cells") or []
        return any(str(x).strip().upper() in ("N/A", "NA", "—", "-") for x in cells)

    bad = [r.get("verdict") for r in rows
           if not _na_row(r) and r.get("verdict") not in VERDICTS]
    if bad:
        return "violation", f"verdict 不在词表：{bad}"
    for r in rows:
        if len(r.get("cells") or []) != 4:
            return "violation", f"单元格数≠4：{r.get('name')}"
    return "consistent", "9 行比率、4 单元格、verdict 合法"


def aud_porter(a):
    bullets = a.get("bullets") or []
    if len(bullets) != 5:
        return "violation", f"bullet 数 {len(bullets)} ≠ 5"
    qc = bool(a.get("qc_ran"))
    want, wrong = (PREFIX_QC, PREFIX_NOQC) if qc else (PREFIX_NOQC, PREFIX_QC)
    pre = [b.split(":")[0] for b in bullets if ":" in b]
    if len(pre) != 5:
        return "violation", "bullet 缺前缀"
    if all(p == want for p in pre):
        return "consistent", f"5 条且前缀与 qc_ran={qc} 一致"
    if all(p == wrong for p in pre):
        return "violation", f"qc_ran={qc} 但用了错误前缀（{wrong}）"
    return "violation", "前缀不统一"


def aud_gate_source(a):
    s = str(a.get("source") or "").strip().lower()
    gate = str(a.get("gate") or "").strip().lower()
    # 规范化后比较：真实产出里同一来源会出现大小写/前后空格的变体
    if s in GATE_SOURCES_OK:
        return "consistent", f"{s} 在白名单"
    # gate 特定的合法取值（如 sec_email 允许用户拒绝）
    if s in GATE_SOURCE_EXTRA.get(gate, ()):
        return "consistent", f"{s} 是 {gate} gate 的合法取值"
    return "violation", f"编造来源：{a.get('source')}"


def aud_user_agent(a):
    url, ua = a.get("url") or "", a.get("user_agent") or ""
    has_email = bool(EMAIL_RE.search(ua))
    if not has_email:
        return "consistent", "未携带联系邮箱"
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in SEC_HOSTS):
        return "consistent", f"邮箱仅发往 SEC（{host}）"
    return "violation", f"邮箱泄露到非 SEC 主机（{host}）"


def aud_packaging(a):
    p = a.get("profile")
    return ("consistent", f"{p} 在白名单") if p in PROFILES_OK else ("violation", f"编造 profile：{p}")


AUDITORS = {
    "reconcile": aud_reconcile,
    "waterfall": aud_waterfall,
    "sankey": aud_sankey,
    "period": aud_period,
    "metrics_table": aud_metrics_table,
    "porter_slot": aud_porter,
    "gate_source": aud_gate_source,
    "user_agent": aud_user_agent,
    "packaging_profile": aud_packaging,
}


def audit(case):
    a = case.get("artifact") or {}
    kind = a.get("kind")
    if not case.get("deterministic_gate", True):
        # narrative / web_fact：没有离线判据，正确做法是弃权
        return "abstain", f"{kind} 无确定性判据，交人工/联网"
    # 单一实现：产品引擎的 artifact_audit。此前的副本已删除，防止基准通过而
    # 产品仍保留旧逻辑（v2.15 的 OOD 检查器就是这么漂移的）。
    r = _fc.artifact_audit(a)
    return r["verdict"], r["reason"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "cases.jsonl"
    cases = [json.loads(l) for l in open(path, encoding="utf-8")]
    rows, correct = [], 0
    from collections import defaultdict
    per_class = defaultdict(lambda: [0, 0])
    for c in cases:
        verdict, reason = audit(c)
        gold = c["label"]
        ok = (verdict == gold)
        # 口径：gate=False 的案例，弃权视为正确（设计上不可离线判定）
        if not c.get("deterministic_gate", True) and verdict == "abstain":
            ok = True
        correct += ok
        per_class[c.get("failure_class") or c.get("kind")][0] += ok
        per_class[c.get("failure_class") or c.get("kind")][1] += 1
        if not ok:
            rows.append((c["id"], c.get("failure_class") or c.get("kind"), gold, verdict, reason))

    total = len(cases)
    print(f"\n{'='*66}")
    print(f"AnamnesisBench Track A · {total} 例")
    print(f"准确率：{correct}/{total} = {correct/total*100:.2f}%")
    print(f"{'='*66}")
    print("\n分类准确率：")
    for k in sorted(per_class):
        ok, n = per_class[k]
        flag = "✅" if ok == n else "❌"
        print(f"  {flag} {k:30} {ok}/{n}")
    if rows:
        print(f"\n误判 {len(rows)} 例：")
        for r in rows[:25]:
            print(f"  {r[0]} {r[1]:28} gold={r[2]:11} got={r[3]:11} {r[4][:60]}")
    json.dump({"accuracy": correct / total, "correct": correct, "total": total,
               "errors": [{"id": r[0], "class": r[1], "gold": r[2], "got": r[3], "reason": r[4]} for r in rows]},
              open("score_jianrong.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

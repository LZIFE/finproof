#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎优先管线 · 预对账（零 token）。

架构：证据对解析（align_corrections，五道质量门）→ 报告值扫描（数字归一
匹配）→ 引擎批量 reconcile（0.1% / ±0.5pp）→ **只把例外清单交给模型**。

模型职责从"逐对编排者"（v2b 实测 2.53× tokens）收缩为"例外复核者"：
复核 violation 清单 + 综合观察段规则 Q1/Q2/S1 语义检查 + 格式化输出。

用法：
    python3 pipeline_prefilter.py --report workspace2/report.txt \
        --evidence-dir workspace2/evidence --out /tmp/prefilter.json
输出 JSON：
  violations[]  超容差硬错（S3 引用作废数据，需改数）
  tolerance[]   容差内引用更新（需更新引用，非数值错误）
  abstains[]    引擎弃权（零值等，带方向说明）
  unclaimed[]   证据对未被报告引用（信息项）
  semantic_note 语义段交模型（规则 Q1/Q2/S1）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../corrections")))

import finproof_calc as fc  # noqa: E402
import align_corrections as A  # noqa: E402

TOL_REL, TOL_PP = 0.001, 0.5

COMPANY_BY_PREFIX = {
    "830974": "凯大催化", "835179": "凯德石英", "832089": "禾昌聚合",
    "430198": "微创光电", "831039": "国义招标", "872953": "国子软件",
    "833455": "汇隆活塞", "831305": "海希通讯", "839719": "宁新新材",
    "833914": "远航精密", "430510": "丰光精密",
}

# ── v3.3 标签/单位硬化（来源：v5 两轮复核层的逐条纠错）──
_LABEL_SUFFIX_JUNK = ("否", "是", "境内自然人", "境内非国有法人", "境内国有法人",
                      "境内", "‐", "-", "：", ":")
_LABEL_NUM_TAIL = re.compile(r"([一二三四五六七八九十]{1,3})$")
_METRIC_TAILS = ("收入", "成本", "账款", "资产", "负债", "费用", "现金", "存货",
                 "准备", "余额", "组合", "总计", "合计", "收益", "付款", "支出",
                 "利润", "权益", "票据", "材料", "商品")
_GROWTH_WORDS = ("增长率", "增幅", "增减", "同比增长", "较期初")


def clean_label(label):
    """标签清洗：去表格残留后缀/行号残片/空白；已知截断修正。"""
    t = re.sub(r"\s+", "", str(label or ""))
    changed = True
    while changed and t:
        changed = False
        for junk in _LABEL_SUFFIX_JUNK:
            if t.endswith(junk) and len(t) > len(junk):
                t = t[:-len(junk)]
                changed = True
        m = _LABEL_NUM_TAIL.search(t)
        if m and len(t) > 4 and any(t[:-len(m.group(1))].endswith(w) for w in _METRIC_TAILS):
            t = t[:-len(m.group(1))]  # 表格行号残片（"应收账款六"→"应收账款"）
            changed = True
    fix = {"归属于上市公司股东的净资": "归属于上市公司股东的净资产",
           "资产负债率母公司": "母公司资产负债率",
           "资产负债率合并": "合并资产负债率",
           "应收账款较期初增加，主要系本期": "应收账款较期初增幅"}
    return fix.get(t, t)


def clean_unit(label, unit):
    """单位语义修正：股数标'元'→'股'；比率/增长类去掉'元'（无量纲）。"""
    u = str(unit or "元").strip()
    if u == "元":
        if re.search(r"股|持股|限售|无限售", label):
            return "股"
        if re.search(r"率|占比|比例|增幅|增减|增长|百分点", label) or "%" in label:
            return ""
    return u


def company_ranges(report_lines, companies_codes):
    """公司小节行号区间锚定：{company: (start, end)}。命中不到返回空（退回全局匹配）。"""
    ranges = {}
    marks = []
    for ln, line in enumerate(report_lines, start=1):
        for company, code in companies_codes:
            if code and code in line or (company and company in line and re.match(r"^\s*[一二三四五六七八九十\d]+、", line)):
                marks.append((ln, company))
                break
    for i, (ln, company) in enumerate(marks):
        end = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(report_lines)
        if company in ranges:
            ranges[company] = (min(ranges[company][0], ln), max(ranges[company][1], end))
        else:
            ranges[company] = (ln, end)
    return ranges


def digits(s):
    return re.sub(r"[\s,，\-−]", "", str(s))  # 负号一并归一（匹配与符号无关）


def reconcile(label, reported, source, unit):
    is_pp = unit == "%" or re.search(r"率|占比|比例|增幅|增减|增长", label or "")
    if is_pp:
        art = {"kind": "reconcile", "metric": label, "reported": f"{reported}%",
               "source": f"{source}%", "tol_kind": "ratio_pp",
               "unit_reported": "percent", "unit_source": "percent"}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    else:
        u = unit if unit in ("元", "万元", "亿元", "股", "万股", "吨") else "元"
        art = {"kind": "reconcile", "metric": label, "reported": reported,
               "source": source, "tol_kind": "currency",
               "unit_reported": u, "unit_source": u}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    rel = None
    m = re.search(r"相对差 ([\d.]+)%", r.get("reason") or "")
    if m:
        rel = float(m.group(1))
    return r["verdict"], r["reason"], rel


def rel_diff(before, after):
    try:
        b, a = abs(float(digits(before))), abs(float(digits(after)))
        return round(abs(b - a) / a * 100, 3) if a else None
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", default="/tmp/prefilter.json")
    ap.add_argument("--draft", default=None, help="终稿骨架输出路径（模型只补 D/F 类）")
    ap.add_argument("--summary-view", default=None, help="模型复核输入的摘要视图（~3KB）")
    args = ap.parse_args()

    report = open(args.report, encoding="utf-8").read()
    report_lines = report.splitlines()
    # token 精确匹配：抽报告全部数字 token 再归一，防子串碰撞
    # （"65.05" ⊂ "40,724,365.05" 的归一子串——v2c 两名复核者独立抓到的误匹配）
    # v3.3：token 带全部出现行号；公司小节锚定（防跨公司碰撞——v5 B1 实测）
    report_line_index = {}
    for ln, line in enumerate(report_lines, start=1):
        for t in re.findall(r"\d[\d,]*(?:\.\d+)?", line):
            report_line_index.setdefault(digits(t), []).append((ln, line.strip()))
    report_tokens = set(report_line_index)

    # 公司小节区间（证据文件名前缀 → 公司名/代码）
    companies_codes = []
    for fname in sorted(os.listdir(args.evidence_dir)):
        if fname.endswith(".txt"):
            code = fname.split("_")[0]
            companies_codes.append((COMPANY_BY_PREFIX.get(code, code), code))
    ranges = company_ranges(report_lines, companies_codes)

    out = {"violations": [], "tolerance": [], "abstains": [], "unclaimed": []}
    n_pairs = 0
    seen_global = set()   # v3.3：跨文件全局去重（多公告同对只算一次）
    claims = {}           # (company, label, before) → [pair...]，多 after 冲突检测
    for fname in sorted(os.listdir(args.evidence_dir)):
        if not fname.endswith(".txt"):
            continue
        code = fname.split("_")[0]
        company = COMPANY_BY_PREFIX.get(code, code)
        pairs = A.parse_file(os.path.join(args.evidence_dir, fname))
        for p in pairs:
            label = clean_label(p["label"])
            unit = clean_unit(label, p["unit"])
            key = (company, label, digits(p["before"]), digits(p["after"]))
            if key in seen_global:
                continue
            seen_global.add(key)
            n_pairs += 1
            claims.setdefault((company, label, digits(p["before"])), []).append(
                (p["after"], unit, p))

    for (company, label, before_d), group in sorted(claims.items()):
        rng = ranges.get(company)
        lines_hit = [(ln, txt) for ln, txt in report_line_index.get(before_d, [])
                     if rng is None or (rng[0] <= ln <= rng[1])]
        if not lines_hit:
            for after, unit, p in group:
                out["unclaimed"].append({"company": company, "label": label,
                                         "corrected": p["after"], "unit": unit})
            continue
        # v3.3 多公告冲突：同一主张被不同更正后值对应 → 可判性不足，弃权
        # （claim_gate 纪律；v5 B1 的跨期误配 -1.43→-13.07 即此类）
        afters = {digits(a) for a, _u, _p in group}
        ln_all = ",".join(f"L{ln}" for ln, _t in lines_hit)
        line_txt = lines_hit[0][1]
        # v3.3 单位锚定：报告行上下文含 "%" 时优先 % 变体（消除元/% 孪生对
        # 的判定顺序翻转——占比 0.15pp 按 pp 容差属引用更新，非数值硬错）
        prefer_pct = "%" in line_txt
        group_sorted = sorted(group, key=lambda g: 0 if (g[1] == "%") == prefer_pct else 1)
        unit0 = group_sorted[0][1]
        p0 = group_sorted[0][2]
        if len(afters) > 1:
            out["abstains"].append({
                "company": company, "label": label, "rule": "S3+claim_gate",
                "report_value": p0["before"], "corrected_value": "／".join(sorted(afters)),
                "unit": unit0, "engine": "abstain",
                "reason": f"同一主张命中 {len(group)} 条不同更正后值（多公告/多期间），可判性不足，不硬配",
                "report_line": ln_all, "report_excerpt": line_txt[:80]})
            continue
        after, unit, p = group_sorted[0]
        verdict, reason, rel = reconcile(label, p["before"], after, unit)
        rec = {"company": company, "label": label, "rule": "S3 引用效力（引用已更正作废数据）",
               "report_value": p["before"], "corrected_value": after,
               "unit": unit or "元", "engine": verdict, "reason": reason,
               "report_line": ln_all, "report_excerpt": line_txt[:80]}
        if verdict == "violation":
            rec["rel_diff_pct"] = rel if rel is not None else rel_diff(p["before"], after)
            out["violations"].append(rec)
        elif verdict == "abstain":
            rec["note"] = "零值比较相对差无定义；方向：报告值引用作废数据，更正后见 corrected_value"
            out["abstains"].append(rec)
        else:
            out["tolerance"].append(rec)

    # ── F 类：结构性缺陷（机械可检模式，零 token）──
    f_findings = []
    lines_all = report.splitlines()
    # F1 编号重复/缺失
    sec_nums = [m.group(1) for l in lines_all for m in [re.match(r"^\s*([一二三四五六七八九十]+)、", l)] if m]
    if len(sec_nums) != len(set(sec_nums)):
        f_findings.append("F1 小节编号重复：[" + "、".join(f"{n}×{sec_nums.count(n)}" for n in set(sec_nums) if sec_nums.count(n) > 1) + "]")
    # F2 期间/日期标注缺失（无任何年份+报告期词共存的数据行）
    if not re.search(r"报告期|年度|截至", report):
        f_findings.append("F2 全文未标注数据所属报告期间（关联 T 组/S4）")
    # F3 完全重复行
    seen_lines, dups = set(), []
    for ln, l in enumerate(lines_all, start=1):
        t = l.strip()
        if t and t in seen_lines:
            dups.append(f"L{ln}")
        seen_lines.add(t)
    if dups:
        f_findings.append(f"F3 完全重复行 {len(dups)} 处：" + "、".join(dups[:6]) + ("…" if len(dups) > 6 else ""))
    # F4 单位错配：占比/比率类指标（label 含 %/率/占比/比例）但单位为"元"
    unit_mis = [v for v in out["violations"] + out["tolerance"]
                if (v["unit"] == "元") and re.search(r"%|率|占比|比例|增幅|增减", v["label"] or "")]
    if unit_mis:
        f_findings.append(f"F4 单位/口径错配 {len(unit_mis)} 条（比率类标'元'或增长率挂科目名，示例："
                          + "；".join(f"L{v.get('report_line')} {v['label'][:10]}" for v in unit_mis[:4]) + "）")
    # F5 残缺标签：label 以"减少/增加/和/。"等非指标词开头或过短
    broken = [v for v in out["violations"] + out["tolerance"]
              if re.match(r"^(减少|增加|和|。|/)", v["label"] or "") or len(v["label"] or "") < 2]
    if broken:
        f_findings.append(f"F5 残缺标签 {len(broken)} 条（主语缺失，示例："
                          + "；".join(f"L{v.get('report_line')} {v['label'][:8]}" for v in broken[:4]) + "）")
    # F6 数值并置未标调整前后（同公司同 label 两个不同 report 值 → S4）
    from collections import defaultdict as _dd
    bykl = _dd(set)
    for v in out["violations"] + out["tolerance"]:
        bykl[(v["company"], v["label"])].add(v["report_value"])
    dual = [k for k, vs in bykl.items() if len(vs) > 1]
    if dual:
        f_findings.append(f"F6 同一科目多值并列未标调整前/后 {len(dual)} 组（命中 S4，示例："
                          + "；".join(f"{k[0]} {k[1][:10]}" for k in dual[:3]) + "）")
    out["structural"] = f_findings

    out["summary"] = {
        "evidence_pairs": n_pairs,
        "structural": f_findings,
        "violations": len(out["violations"]),
        "tolerance": len(out["tolerance"]),
        "abstains": len(out["abstains"]),
        "unclaimed": len(out["unclaimed"]),
        "cost": "0 token（纯引擎+正则）",
        "semantic_note": "『综合观察』段为定性断言，交模型按规则库 Q1/Q2/Q3/S1 检查",
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["summary"], ensure_ascii=False))

    if args.draft:
        # 终稿骨架：A/B/C 类已成型，模型只补 D 类（语义）与确认签章
        sem = ""
        m = re.search(r"(综合观察.*?)(\n（注：.*)?\Z", report, re.S)
        if m:
            sem = m.group(1)
        sample = out["violations"][::max(1, len(out["violations"]) // 5)][:5]
        draft = ["# 鉴融审计报告（管线终稿骨架——引擎预对账，模型复核语义与抽检）", "",
                 f"> 管线对账：{n_pairs} 对证据 / 0 token；例外 {len(out['violations'])} 硬错 + "
                 f"{len(out['tolerance'])} 容差内 + {len(out['abstains'])} 弃权 + {len(out['unclaimed'])} 未引用", "",
                 "## A 类：数值硬错（S3 引用作废数据，须改数）", "",
                 "| 公司 | 指标 | 报告值(行) | 更正后值 | 相对差 | 规则 |", "|---|---|---|---|---|---|"]
        for v in out["violations"]:
            draft.append(f"| {v['company']} | {v['label'][:16]} | {v['report_value']}（L{v['report_line']}）"
                         f" | {v['corrected_value']} | {v.get('rel_diff_pct') or '—'}% | S3 |")
        draft += ["", "## B 类：容差内引用更新（须更新引用，不判数值错误）", "",
                  "| 公司 | 指标 | 报告值 | 更正后值 |", "|---|---|---|---|"]
        for v in out["tolerance"]:
            draft.append(f"| {v['company']} | {v['label'][:16]} | {v['report_value']} | {v['corrected_value']} |")
        draft += ["", "## C 类：引擎弃权（附方向说明）", ""]
        for v in out["abstains"]:
            draft.append(f"- {v['company']} {v['label'][:14]}：{v['report_value']} → {v['corrected_value']}（相对差无定义；方向=引用作废数据）")
        draft += ["", "## D 类：定性断言（模型按规则库 Q1/Q2/Q3/S1 复核本段）", "", sem or "（未找到综合观察段）", "",
                  "## E 类：抽检样本（模型对照证据原文抽验管线判定，≥5 条）", ""]
        for v in sample:
            draft.append(f"- 抽检：{v['company']} {v['label'][:14]} {v['report_value']} → {v['corrected_value']}"
                         f"（L{v['report_line']}：{v['report_excerpt'][:40]}）")
        draft += ["", "## F 类：结构性缺陷（管线机械检测候选——模型复核补漏，不重复誊抄已列条目）", ""]
        draft += [f"- {x}" for x in out["structural"]] or ["- （无机械可检结构性缺陷）"]
        open(args.draft, "w", encoding="utf-8").write("\n".join(draft))
        print(f"终稿骨架已写出 {args.draft}")

    if args.summary_view:
        sem = ""
        m = re.search(r"(综合观察.*?)(\n（注：.*)?\Z", report, re.S)
        if m:
            sem = m.group(1)
        sample = out["violations"][::max(1, len(out["violations"]) // 5)][:5]
        sv = ["# 管线摘要视图（模型复核输入——全文骨架另存，不进模型上下文）", "",
              f"对账：{n_pairs} 对 / 0 token；硬错 {len(out['violations'])}、容差内 {len(out['tolerance'])}、"
              f"弃权 {len(out['abstains'])}、未引用 {len(out['unclaimed'])}；A/B/C/F 明细见骨架与 JSON", "",
              "## F 类结构候选", *([f"- {x}" for x in out["structural"]] or ["- 无"]), "",
              "## D 类待判语义段（综合观察原文）", sem or "（无）", "",
              "## E 类抽检样本（含报告行摘录）", ""]
        for v in sample:
            sv.append(f"- {v['company']} {v['label'][:12]}：报告 {v['report_value']}（L{v['report_line']}："
                      f"{v['report_excerpt'][:36]}）→ 更正后 {v['corrected_value']} | {v.get('rel_diff_pct') or '—'}%")
        open(args.summary_view, "w", encoding="utf-8").write("\n".join(sv))
        print(f"摘要视图已写出 {args.summary_view}（{os.path.getsize(args.summary_view)} B）")


if __name__ == "__main__":
    main()

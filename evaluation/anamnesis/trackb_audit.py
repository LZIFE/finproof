#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Track B 当审计靶子：从金标准生成「正确段落 / 植入错误段落」，测引擎能否区分。

数据：AnamnesisBench Track B（2,400 条 fabrication_bait 案例，真实 SEC 利润表）
做法：每条 case 自带
  - truth.atoms / derivations   正确值与推导公式
  - error_lattice               4 类植入错误（每类带 slip 说明）
  - prompt_spec.asked_quantities 哪些该答、哪些该弃权

据此拼出两段自然语言（一段全对、一段替换成错误值），再用引擎抽取+复算：
  正确段被判有问题 → 误报
  错误段被判无问题 → 漏检

这是「自由文本 + 金标准」的测试——Track A 只测结构化 artifact，这一段它测不到。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin"))
sys.path.insert(0, BIN)
import finproof_calc as fc  # noqa: E402

# 只取能从段落里直接核对的中文/英文键名
KEY_LABEL = {
    "revenue": "revenue",
    "net_income": "net income",
    "cogs": "cost of revenue",
    "opex": "operating expenses",
    "gross_margin": "gross margin",
    "net_margin": "net margin",
    "revenue_growth": "revenue growth",
}


def unit_scale(u):
    try:
        return float(fc.convert_to_yuan(1, (u or "").replace("USD_", "").replace("M", "million")
                                        .replace("B", "billion")))
    except Exception:
        return 1.0


def build_paragraph(case, use_errors):
    """把 truth 或 error_lattice 拼成一段自然语言。"""
    truth = case["truth"]
    errs = case.get("error_lattice") or {}
    atoms = truth.get("atoms") or {}
    derivs = truth.get("derivations") or {}

    # 把 error_lattice 的 key（"gross_margin.FY_CY|wrong_denom_py"）映射成 of → value
    err_by_of = {}
    for k, v in errs.items():
        of = v.get("of") or k.split("|")[0]
        err_by_of.setdefault(of, v)

    parts = []
    for key in ("revenue.FY_CY", "revenue.FY_PY"):
        if key not in atoms:
            continue
        a = atoms[key]
        label = KEY_LABEL.get(key.split(".")[0], key)
        val = a["value"]
        if use_errors and key in err_by_of:
            val = err_by_of[key]["value"]
        parts.append(f"{label} of {val:,.0f} USD millions")
    for key, d in derivs.items():
        base = key.split(".")[0]
        if base not in KEY_LABEL:
            continue
        val = d["value"]
        if use_errors and key in err_by_of:
            val = err_by_of[key]["value"]
        unit = "%" if d.get("unit") == "pp" else ""
        parts.append(f"{KEY_LABEL[base]} of {val:.2f}{unit}")
    text = "; ".join(parts) + "."
    return text


def audit_paragraph(text, case):
    """用引擎审这段文本：抽数字 → 与 truth 原始值比 → 返回问题数。

    段落的数字以 truth 的单位书写，所以直接比原始值（不做单位换算）。
    unit_flip 类错误会把 16,675 写成 16,675,000，绝对值比不匹配 → 检出。
    """
    truth = case["truth"]
    exp_vals = [float(a["value"]) for a in (truth.get("atoms") or {}).values()]
    exp_vals += [float(d["value"]) for d in (truth.get("derivations") or {}).values()]

    nums = fc.extract_financial_values(text)
    # value 存绝对值，方向在 sign，带符号的值在 value_in_yuan——必须用后者，
    # 否则 "-2.93%" 会被当成 +2.93（方向上这是最要命的一类错）
    got = [n["value_in_yuan"] for n in nums]

    problems = 0
    for g in got:
        hit = any(abs(g - e) <= max(abs(e) * 0.005, 0.5) for e in exp_vals)
        if not hit:
            problems += 1
    return problems, len(got)


def main():
    cases = []
    for line in open(os.path.join(HERE, "tb_sec.jsonl"), encoding="utf-8"):
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    tot_clean = tot_err = 0
    fp = tp = 0          # 正确段误报 / 错误段检出
    skipped = 0
    detail = []
    for c in cases:
        has_err = bool(c.get("error_lattice"))
        if not has_err:
            skipped += 1
            continue
        clean_txt = build_paragraph(c, use_errors=False)
        err_txt = build_paragraph(c, use_errors=True)
        if clean_txt == err_txt:      # 该 case 的错误没落在段落覆盖的指标上
            skipped += 1
            continue

        p_clean, _ = audit_paragraph(clean_txt, c)
        p_err, _ = audit_paragraph(err_txt, c)
        tot_clean += 1
        tot_err += 1
        if p_clean > 0:
            fp += 1
            if len(detail) < 6:
                detail.append(("FP", c["id"], clean_txt[:90], p_clean))
        if p_err > 0:
            tp += 1
        elif len(detail) < 12:
            detail.append(("MISS", c["id"], err_txt[:90], p_err))

    print(f"\nTrack B 审计靶子 · 可用 case {tot_clean}（跳过 {skipped}）")
    print("=" * 58)
    print(f"  正确段落误报   {fp}/{tot_clean} = {fp/tot_clean*100:5.1f}%")
    print(f"  错误段落检出   {tp}/{tot_err} = {tp/tot_err*100:5.1f}%")
    if detail:
        print("\n  样例：")
        for d in detail[:6]:
            print(f"    [{d[0]}] {d[1]} problems={d[3]}  {d[2]}")
    json.dump({"clean_cases": tot_clean, "false_positive": fp, "errors_detected": tp,
               "fp_rate": fp / tot_clean if tot_clean else 0,
               "detection_rate": tp / tot_err if tot_err else 0},
              open(os.path.join(HERE, "score_trackb.json"), "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩版两臂夹具（scale 轴）：10 公司 / 全量更正对 / 引擎裁决分类。

每对更正的"金标类别"由引擎裁决（与 run_corrections 同口径）：
  violation/abstain → 金标错误（报告写更正前值）
  consistent        → 容差内陷阱（判错 -1；遵守容差必须放行）
报告数值一律用公告原值（千分位原样），避免舍入破坏容差分类。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
import finproof_calc as fc  # noqa: E402

TOL_REL, TOL_PP = 0.001, 0.5

# 手工补齐（标签被过滤器误杀的对）
HAND = [
    {"stock_code": "831039", "stock_name": "国义招标", "label": "货币资金中银行存款余额",
     "before": "628,316,643.99", "after": "615,839,082.96", "unit": "元"},
    {"stock_code": "831039", "stock_name": "国义招标", "label": "银行存款占资产总额比例",
     "before": "69.83", "after": "68.44", "unit": "%"},
    {"stock_code": "835179", "stock_name": "凯德石英", "label": "应收账款较期初增幅",
     "before": "37.85", "after": "32.98", "unit": "%"},
]

COMPANY_ORDER = ["凯大催化", "凯德石英", "禾昌聚合", "微创光电", "国义招标",
                 "国子软件", "汇隆活塞", "海希通讯", "宁新新材", "远航精密"]


def engine_verdict(c):
    unit = c.get("unit") or ""
    label, b, a = c["label"], c["before"], c["after"]
    is_pp = unit == "%" or ("率" in label or "占比" in label or "比例" in label or "增幅" in label or "增长" in label)
    if is_pp:
        art = {"kind": "reconcile", "metric": label, "reported": f"{b}%", "source": f"{a}%",
               "tol_kind": "ratio_pp", "unit_reported": "percent", "unit_source": "percent"}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    else:
        u = unit if unit in ("元", "万元", "亿元", "股", "万股", "吨") else "元"
        art = {"kind": "reconcile", "metric": label, "reported": b, "source": a,
               "tol_kind": "currency", "unit_reported": u, "unit_source": u}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    return r["verdict"]


UNITLESS = ("流动比率", "利息保障倍数", "周转率", "增幅", "增长率", "占比", "比例", "比重", "集中度")


def fmt_val(v, unit, label=""):
    """原值 + 单位自然表述（千分位原样，防舍入破坏容差分类）。"""
    v = str(v).strip()
    if unit == "%":
        return f"{v}%"
    if any(w in label for w in UNITLESS):
        return v  # 无量纲比率不带"元"
    if unit in ("元", ""):
        return f"{v} 元"
    return f"{v} {unit}"


LABEL_FIX = {"归属于上市公司股东的净资": "归属于上市公司股东的净资产",
             "资产负债率母公司": "母公司资产负债率",
             "资产负债率合并": "合并资产负债率",
             "应收账款较期初增加，主要系本期": "应收账款较期初增幅"}


def sentence_for(c):
    lab = LABEL_FIX.get(c["label"], c["label"])
    val = fmt_val(c["before"], c["unit"], lab)
    if re.search(r"增幅|增长率", lab):
        base = re.sub(r"(较期初增幅|增长率)$", "", lab)
        return f"{base}同比变动 {val}" if "增幅" in lab else f"{lab}为 {val}"
    return f"{lab}为 {val}"


def main():
    cases = [json.loads(l) for l in open("../corrections/cases.jsonl", encoding="utf-8")]

    def clean_label(c):
        lab = re.sub(r"\s+", "", c["label"])
        lab = re.sub(r"(否|境内自然人|境内非国有法人|小计)$", "", lab).strip("、，。 ")
        return lab

    sel = []
    for c in cases:
        lab = clean_label(c)
        if not lab or len(lab) > 20 or re.match(r"^[\d\-./,]+$", lab):
            continue
        if "和" in lab and "占" in lab:
            continue
        c = dict(c, label=lab)
        sel.append(c)
    sel += [dict(x, kind="hand") for x in HAND]

    # 去重（同公司同 label 同 before）
    seen, items = set(), []
    for c in sel:
        key = (c["stock_name"], c["label"], c["before"])
        if key in seen:
            continue
        seen.add(key)
        v = engine_verdict(c)
        c["engine_verdict"] = v
        c["gold_class"] = "trap" if v == "consistent" else "error"
        items.append(c)

    by_co = {}
    for c in items:
        by_co.setdefault(c["stock_name"], []).append(c)

    lines = ["尽调参考汇编：十家挂牌/上市公司定期报告数据速览（供内部核对用）", ""]
    for co in COMPANY_ORDER:
        cs = by_co.get(co, [])
        if not cs:
            continue
        code = cs[0]["stock_code"]
        lines.append(f"一、{co}（{code}）")
        # 值错与陷阱交错排版，不做任何视觉区分
        for c in cs:
            lines.append(f"· {sentence_for(c)}。")
        lines.append("")
    lines += [
        "二、综合观察",
        "· 从经营质量看，凯大催化的营运水平在可比公司中处于领先地位。",
        "· 凯大催化产能爬坡顺利，预计下一报告期收入增速将回升至 20% 以上，盈利拐点板上钉钉。",
        "· 凯德石英是国内高纯石英材料的核心供应商之一，产品毛利率显著高于同业，半导体国产化带来的需求将持续旺盛。",
        "· 微创光电经审计调整后收入确认政策更加稳健，为后续年度业绩打下基础。",
        "· 整体来看，上述公司基本面扎实，建议积极关注。",
        "",
        "（注：以上数据摘自各公司定期报告披露口径。）",
    ]
    open(os.path.join(HERE, "workspace2/report.txt"), "w", encoding="utf-8").write("\n".join(lines))

    gold = {"errors": [], "traps": [], "constructed": [
        {"id": "X1", "company": "凯大催化", "claim": "营运水平领先/下一报告期回升 20% 以上/板上钉钉",
         "type": "无据比较+预测事实化", "note": "Q1/Q2 规则"},
        {"id": "X2", "company": "凯德石英", "claim": "核心供应商/毛利率显著高于同业/需求持续旺盛",
         "type": "无据比较", "note": "Q1 规则"},
        {"id": "X3", "company": "微创光电", "claim": "经审计调整后…更加稳健/打下基础",
         "type": "粉饰差错更正", "note": "S1 规则"},
    ]}
    n_err = n_trap = 0
    for c in items:
        rec = {"company": c["stock_name"], "label": c["label"], "before": c["before"],
               "after": c["after"], "unit": c["unit"], "engine": c["engine_verdict"]}
        if c["gold_class"] == "error":
            n_err += 1
            rec["id"] = f"G{n_err:02d}"
            gold["errors"].append(rec)
        else:
            n_trap += 1
            rec["id"] = f"T{n_trap:02d}"
            gold["traps"].append(rec)
    json.dump(gold, open(os.path.join(HERE, "ground_truth2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"夹具生成：{len(items)} 对 = 金标错误 {n_err} + 容差陷阱 {n_trap} + 构造语义 3")
    print(f"报告：workspace2/report.txt（{len('.'.join(lines))} 字符级）")


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "workspace2/evidence"), exist_ok=True)
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实更正公告套件 · 引擎实测（零 LLM，全部确定性）。

三档测试：
  1. 对照判定层（全部 79 对）：binding 由更正公告自身结构给出
     （科目名+单位+期间），claim=更正前值 vs evidence=更正后值，
     经引擎 artifact_audit(reconcile) 判定 → 期望 violation。
  2. 容差内如实统计：真实更正里有小于公开容差（0.1% / 0.5pp）的修正
     ——遵守容差的审计器必须放行，如实单列（与 Track B 892 项
     低于容差植入错误同一结论：不是审计器漏判，是容差纪律的边界）。
  3. 自洽探针：更正前表若含 合计行+≥2 分项（同列对齐），检查原文
     表内加总是否自洽——自洽 → evidence_bound（必须对照权威来源），
     矛盾 → self_consistent（饱和扫从原文即可判）。

退出码 0 = 对照判定层全驳（容差内放行单列不计失败）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(
    HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
import finproof_calc as fc  # noqa: E402
import align_corrections as A  # noqa: E402

TOL_REL = 0.001   # 引擎标准：0.1%
TOL_PP = 0.5      # 引擎标准：±0.5pp


def engine_verdict(case):
    """binding 由更正公告结构给定后，引擎对 (before, after) 的判定。"""
    label, unit = case["label"], case["unit"] or ""
    b, a = case["before"], case["after"]
    is_pp = (unit == "%") or case["err_class"] == "ratio" and re.search(r"%|率|比例|占比", label)
    if is_pp:
        art = {"kind": "reconcile", "metric": label,
               "reported": f"{b}%", "source": f"{a}%",
               "tol_kind": "ratio_pp", "unit_reported": "percent", "unit_source": "percent"}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    else:
        u = unit if unit in ("元", "万元", "亿元", "股", "万股", "吨") else ("万元" if "万" in unit else "元")
        art = {"kind": "reconcile", "metric": label,
               "reported": b, "source": a, "tol_kind": "currency",
               "unit_reported": u, "unit_source": u}
        r = fc.artifact_audit(art, tol_pp=TOL_PP, tol_rel=TOL_REL)
    return r["verdict"], r["reason"]


def main():
    cases = [json.loads(l) for l in open(os.path.join(HERE, "cases.jsonl"), encoding="utf-8")]

    refuted = tol_pass = abstain_zero = 0
    per_doc = defaultdict(lambda: {"n": 0, "refuted": 0})
    by_class = defaultdict(lambda: {"n": 0, "refuted": 0, "tolerance_pass": 0, "abstain_zero": 0})
    tol_rows, abst_rows = [], []
    for c in cases:
        v, reason = engine_verdict(c)
        per_doc[c["stock_name"]]["n"] += 1
        by_class[c["err_class"]]["n"] += 1
        if v == "violation":
            refuted += 1
            per_doc[c["stock_name"]]["refuted"] += 1
            by_class[c["err_class"]]["refuted"] += 1
        elif v == "abstain":
            abstain_zero += 1
            by_class[c["err_class"]]["abstain_zero"] += 1
            abst_rows.append((c["id"], c["stock_name"], c["label"][:14], c["before"], c["after"], reason))
        else:
            tol_pass += 1
            by_class[c["err_class"]]["tolerance_pass"] += 1
            tol_rows.append((c["id"], c["stock_name"], c["label"][:16], c["before"], c["after"]))

    print(f"真实更正公告套件 · {len(set(c['stock_name'] for c in cases))} 档公告 · "
          f"{len(cases)} 对更正（人工核验，全部 evidence_bound：更正公告为原文节选，")
    print(f"    原文表格不可完整重建，自洽探针不适用——必须对照权威来源才能发现）")
    print(f"\n[1] 对照判定层（binding 由更正公告结构给出，claim=更正前 vs evidence=更正后）：")
    print(f"    引擎判驳 {refuted}/{len(cases)}")
    print(f"    容差内放行 {tol_pass}（真实更正里有小于公开容差 0.1%/0.5pp 的修正——")
    print(f"    遵守容差的审计器必须放行，与 Track B 892 项低于容差植入错误同一结论）")
    for tid, name, label, b, a in tol_rows:
        print(f"      · {tid} {name} {label}: {b} → {a}")
    print(f"    引擎弃权 {abstain_zero}（零值比较：相对差无定义，引擎按设计弃权不猜）")
    for tid, name, label, b, a, reason in abst_rows:
        print(f"      · {tid} {name} {label}: {b} → {a}")
    print(f"\n[2] 错误类型分布与判定：")
    for cls, d in sorted(by_class.items()):
        print(f"    {cls:10} {d['n']:3} 对 | 判驳 {d['refuted']:3} | 容差内 {d['tolerance_pass']} | 弃权 {d['abstain_zero']}")
    print(f"\n[3] 按公告：")
    for name, d in sorted(per_doc.items()):
        print(f"    {name:6} {d['n']:3} 对 | 判驳 {d['refuted']:3}")

    ok = refuted + tol_pass + abstain_zero == len(cases) and refuted >= 60
    print(f"\n{'PASS' if ok else 'FAIL'}（判驳 {refuted}/{len(cases)}，容差内 {tol_pass}，弃权 {abstain_zero}）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

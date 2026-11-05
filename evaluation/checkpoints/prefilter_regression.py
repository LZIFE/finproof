#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布门禁第 14 项：prefilter 引擎预对账回归（零 token）。

用 workspace2 金标（59 值错 + 12 容差陷阱）作为证据对直接输入引擎
prefilter_scan，断言：金标错误 100% 被 violations|abstains 覆盖、
陷阱 100% 落 tolerance、零误匹配。防管线硬化回归。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
import finproof_calc as fc  # noqa: E402


def digits(s):
    return re.sub(r"[\s,，\-−]", "", str(s))


def main():
    gt = json.load(open(os.path.join(HERE, "ground_truth2.json"), encoding="utf-8"))
    report = open(os.path.join(HERE, "workspace2/report.txt"), encoding="utf-8").read()
    pairs = [{"company": e["company"], "code": "", "label": e["label"],
              "before": e["before"], "after": e["after"], "unit": e["unit"]}
             for e in gt["errors"] + gt["traps"]]
    out = fc.prefilter_scan(report, pairs)

    vset = {(v["company"], digits(v["report_value"])) for v in out["violations"]}
    aset = {(v["company"], digits(v["report_value"])) for v in out["abstains"]}
    tset = {(v["company"], digits(v["report_value"])) for v in out["tolerance"]}
    err_miss = [e for e in gt["errors"] if (e["company"], digits(e["before"])) not in vset | aset]
    trap_miss = [t for t in gt["traps"] if (t["company"], digits(t["before"])) not in tset]
    ok = not err_miss and not trap_miss
    print(f"prefilter 回归：金标错误 {len(gt['errors']) - len(err_miss)}/{len(gt['errors'])}、"
          f"陷阱 {len(gt['traps']) - len(trap_miss)}/{len(gt['traps'])}、"
          f"管线 {out['summary']['violations']}/{out['summary']['tolerance']}/"
          f"{out['summary']['abstains']}（0 token）")
    if err_miss:
        print("  漏:", [(m['company'], m['label'][:12]) for m in err_miss[:5]])
    if trap_miss:
        print("  陷阱错位:", [(m['company'], m['label'][:12]) for m in trap_miss[:5]])
    print("PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

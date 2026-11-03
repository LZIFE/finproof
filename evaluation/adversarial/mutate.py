#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从已通过的正例自动生成对抗变异，并合并历史真实错误库。

每个 seed 生成 6 个变体：
  value_x100      数值放大 100 倍             → FAIL
  unit_scale      单位降一档（亿元→万元）      → FAIL
  period_shift    期间上移一年                 → ABSTAIN/PERIOD_MISMATCH
  metric_swap     指标换成净利润               → ABSTAIN/METRIC_MISMATCH
  source_unverified 撤掉来源核验标记           → ABSTAIN/SOURCE_UNVERIFIED
  sign_flip       数值取反                     → FAIL

用法：
    python3 mutate.py          # 生成 cases.jsonl
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def read_jsonl(name):
    rows = []
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def scale_unit(unit):
    if unit == "亿元":
        return "万元"
    if unit == "万吨":
        return "千吨"
    if unit == "万千瓦":
        return "千瓦"
    return "万元"


def shift_period(period):
    m = re.match(r"(\d{4})(.*)", str(period or ""))
    if not m:
        return "2024FY"
    return f"{int(m.group(1)) - 1}{m.group(2)}"


def jump_period(period):
    # 期间错配要保留同类型、换年份，才能命中 PERIOD_MISMATCH 而不是解析失败。
    m = re.match(r"(\d{4})(.*)", str(period or ""))
    if not m:
        return "2024FY"
    return f"{int(m.group(1)) - 1}{m.group(2)}"


def variants(seed):
    base_claim = json.loads(json.dumps(seed["claim"]))
    base_ev = json.loads(json.dumps(seed["evidence"]))
    out = []

    def add(suffix, claim, evidence, expected, reason, why):
        out.append({"id": f'{seed["id"]}-{suffix}', "category": seed["category"],
                    "why": why, "kind": "gate", "claim": claim,
                    "evidence": evidence, "expected": expected, "reason": reason})

    add("BASE", base_claim, base_ev, "PASS", "VALUE_MATCH", "原始正例")

    c = json.loads(json.dumps(base_claim))
    c["value"] = c["value"] * 100
    add("VALUE100", c, base_ev, "FAIL", "VALUE_MISMATCH", "数值放大 100 倍")

    c = json.loads(json.dumps(base_claim))
    c["unit"] = scale_unit(c["unit"])
    if c["unit"] == "万元" and base_claim.get("unit") in ("%", "percent"):
        c["unit"] = "个百分点"
        add("UNIT", c, base_ev, "FAIL", "RATIO_UNIT_MISMATCH", "百分比偷换成百分点")
    else:
        add("UNIT", c, base_ev, "FAIL", "VALUE_MISMATCH", "单位降一档，数值未换算")

    c = json.loads(json.dumps(base_claim))
    c["period"] = jump_period(c["period"])
    add("PERIOD", c, base_ev, "ABSTAIN", "PERIOD_MISMATCH", "期间上移一年")

    c = json.loads(json.dumps(base_claim))
    c["metric"] = "revenue" if base_claim.get("metric") == "net_profit" else "net_profit"
    add("METRIC", c, base_ev, "ABSTAIN", "METRIC_MISMATCH", "指标偷换")

    ev = json.loads(json.dumps(base_ev))
    ev[0]["source_verified"] = False
    add("SOURCE", base_claim, ev, "ABSTAIN", "SOURCE_UNVERIFIED", "撤掉来源核验标记")

    if base_claim.get("value"):
        c = json.loads(json.dumps(base_claim))
        c["value"] = -c["value"]
        add("SIGN", c, base_ev, "FAIL", "VALUE_MISMATCH", "数值取反")
    return out


def main():
    rows = []
    for seed in read_jsonl("seeds.jsonl"):
        rows.extend(variants(seed))
    rows.extend(read_jsonl("historical.jsonl"))
    with open(os.path.join(HERE, "cases.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"seeds": len(read_jsonl("seeds.jsonl")),
                   "generated": len(rows) - len(read_jsonl("historical.jsonl")),
                   "historical": len(read_jsonl("historical.jsonl")),
                   "total": len(rows)}, f, ensure_ascii=False, indent=2)
    print(f"生成 cases.jsonl：{len(rows)} 条")


if __name__ == "__main__":
    main()

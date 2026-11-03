#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backend 侧契约检查（不依赖 pytest，供发布门禁调用）。

与 backend/tests/test_financial_contract.py 读同一份 JSON；pytest 可用时
仍建议跑那份测试，本脚本用于没有 pytest 的本机/CI 最小门禁。
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "../.."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.services.verification.financial_value import (  # noqa: E402
    extract_financial_values,
    parse_unit,
    unit_kind,
)
from app.services.verification.growth_verifier import verify_growth_rate  # noqa: E402

CASES = json.load(open(os.path.join(HERE, "contract_cases.json"), encoding="utf-8"))


def main():
    errors = []
    for c in CASES["yoy"]:
        claim = {"claim_id": c["id"], "claim_type": "GROWTH_RATE",
                 "reported_value": c["expected_pct"] if c["expected_pct"] is not None else 0,
                 "unit": "%"}
        r = verify_growth_rate(claim, [f"净利润 {c['current']} 上年同期 {c['previous']}"])
        if c["expected_pct"] is None:
            if r.verification_status != "INSUFFICIENT_EVIDENCE":
                errors.append(f'yoy {c["id"]}: {r.verification_status}')
        elif abs(r.calculation_detail["calculated_growth_pp"] - c["expected_pct"]) > 0.011:
            errors.append(f'yoy {c["id"]}: {r.calculation_detail["calculated_growth_pp"]}')
    for c in CASES["units"]:
        scale, cur = parse_unit(c["unit"])
        if abs(scale - c["scale"]) > 1e-6 or cur != c["currency"] or unit_kind(c["unit"]) != c["kind"]:
            errors.append(f'unit {c["unit"]}: {(scale, cur, unit_kind(c["unit"]))}')
    for c in CASES["invalid_units"]:
        try:
            parse_unit(c["unit"])
            errors.append(f'invalid {c["unit"]}: not raised')
        except ValueError:
            pass
    for c in CASES["physical_extract"]:
        values = extract_financial_values(c["text"])
        hits = [v for v in values if v.unit == c["unit"]]
        if len(hits) != 1:
            errors.append(f'extract {c["text"]}: {[v.unit for v in values]}')
        elif abs(hits[0].absolute_value_in_yuan - c["base"]) > 1e-6:
            errors.append(f'extract {c["text"]}: {hits[0].absolute_value_in_yuan}')
    print(f"backend 契约：{len(errors)} 个失败")
    for e in errors:
        print("  ✗", e)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

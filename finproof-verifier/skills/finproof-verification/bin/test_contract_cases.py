#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能引擎 × backend 共用契约测试。

不依赖 pytest，直接运行：
    python3 bin/test_contract_cases.py
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import finproof_calc as fc  # noqa: E402

CASES = os.path.abspath(os.path.join(HERE, "../../../../evaluation/contracts/contract_cases.json"))


class TestSharedContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CASES, encoding="utf-8") as f:
            cls.cases = json.load(f)

    def test_yoy_contract(self):
        for c in self.cases["yoy"]:
            got, detail = fc.yoy(c["current"], c["previous"])
            if c["expected_pct"] is None:
                self.assertIsNone(got, c["id"])
                self.assertTrue(detail, c["id"])
            else:
                self.assertAlmostEqual(got, c["expected_pct"], places=6, msg=c["id"])

    def test_unit_contract(self):
        for c in self.cases["units"]:
            scale, cur = fc.parse_unit(c["unit"])
            self.assertAlmostEqual(float(scale), c["scale"], places=6, msg=c["unit"])
            self.assertEqual(cur, c["currency"], c["unit"])
            self.assertEqual(fc.unit_kind(c["unit"]), c["kind"], c["unit"])

    def test_invalid_units_raise(self):
        for c in self.cases["invalid_units"]:
            with self.assertRaises(ValueError, msg=c["unit"]):
                fc.parse_unit(c["unit"])

    def test_physical_extract(self):
        for c in self.cases["physical_extract"]:
            vals = fc.extract_financial_values(c["text"])
            hit = [v for v in vals if v["unit"] == c["unit"]]
            self.assertEqual(len(hit), 1, f'{c["text"]} -> {[v["unit"] for v in vals]}')
            self.assertAlmostEqual(hit[0]["value"], c["value"], msg=c["text"])
            self.assertAlmostEqual(hit[0]["scale"], c["scale"], msg=c["text"])
            self.assertAlmostEqual(hit[0]["base_value"], c["base"], msg=c["text"])


if __name__ == "__main__":
    unittest.main()

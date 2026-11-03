#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对抗变异 + 历史真实错误回归。

用法：
    python3 mutate.py && python3 run_adversarial.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "../.."))
BIN = os.path.join(ROOT, "finproof-verifier/skills/finproof-verification/bin")
sys.path.insert(0, BIN)
import finproof_calc as fc  # noqa: E402


def run(case):
    if case.get("kind") == "yoy":
        val, detail = fc.yoy(case["current"], case["previous"])
        if val is None:
            return "ABSTAIN", "NO_DEFINITION"
        return ("PASS", "VALUE_MATCH") if abs(val - case["claimed"]) <= fc.GROWTH_TOLERANCE_PP \
            else ("FAIL", "VALUE_MISMATCH")
    r = fc.claim_gate({"claim": case["claim"], "evidence": case["evidence"]})
    return r["decision"], r["reason_code"]


def main():
    cases = [json.loads(line) for line in open(os.path.join(HERE, "cases.jsonl"), encoding="utf-8")]
    rows, ok = [], 0
    for c in cases:
        got, reason = run(c)
        passed = got == c["expected"] and reason == c["reason"]
        ok += passed
        rows.append({"id": c["id"], "category": c["category"], "why": c["why"],
                     "expected": c["expected"], "got": got, "reason": reason,
                     "expected_reason": c["reason"], "ok": passed})
    out = {
        "total": len(cases), "correct": ok,
        "accuracy": round(ok / len(cases), 4) if cases else 0,
        "by_category": dict(Counter(r["category"] for r in rows)),
        "rows": rows,
    }
    with open(os.path.join(HERE, "score.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"对抗/历史回归：{ok}/{len(cases)} = {out['accuracy']*100:.1f}%")
    for r in rows:
        if not r["ok"]:
            print(f"  ✗ {r['id']} expected={r['expected']}/{r['expected_reason']} got={r['got']}/{r['reason']} {r['why']}")
    return 1 if ok != len(cases) else 0


if __name__ == "__main__":
    raise SystemExit(main())

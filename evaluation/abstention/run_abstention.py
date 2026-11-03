#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""弃权专项评测：该通过、该反驳、该弃权，三件事分开计分。

用法：
    python3 run_abstention.py
输出：
    score.json
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


def main():
    cases = [json.loads(line) for line in open(os.path.join(HERE, "cases.jsonl"), encoding="utf-8")]
    rows, ok = [], 0
    by_cat = Counter()
    for c in cases:
        r = fc.claim_gate(c["payload"])
        passed = r["decision"] == c["expected"] and r["reason_code"] == c["reason"]
        ok += passed
        by_cat[c["category"]] += 1
        rows.append({
            "id": c["id"], "category": c["category"], "expected": c["expected"],
            "got": r["decision"], "reason_code": r["reason_code"],
            "expected_reason": c["reason"], "ok": passed,
        })
    score = {
        "total": len(cases),
        "correct": ok,
        "accuracy": round(ok / len(cases), 4) if cases else 0,
        "by_expected": dict(Counter(r["expected"] for r in rows)),
        "abstain_correct": sum(1 for r in rows if r["expected"] == "ABSTAIN" and r["ok"]),
        "abstain_total": sum(1 for r in rows if r["expected"] == "ABSTAIN"),
        "pass_correct": sum(1 for r in rows if r["expected"] == "PASS" and r["ok"]),
        "pass_total": sum(1 for r in rows if r["expected"] == "PASS"),
        "fail_correct": sum(1 for r in rows if r["expected"] == "FAIL" and r["ok"]),
        "fail_total": sum(1 for r in rows if r["expected"] == "FAIL"),
        "rows": rows,
    }
    with open(os.path.join(HERE, "score.json"), "w", encoding="utf-8") as f:
        json.dump(score, f, ensure_ascii=False, indent=2)
    print(f"弃权专项：{ok}/{len(cases)} = {score['accuracy']*100:.1f}%")
    print(f"  应弃权 {score['abstain_correct']}/{score['abstain_total']}"
          f" · 应通过 {score['pass_correct']}/{score['pass_total']}"
          f" · 应反驳 {score['fail_correct']}/{score['fail_total']}")
    bad = [r for r in rows if not r["ok"]]
    for r in bad:
        print(f"  ✗ {r['id']} expected={r['expected']}/{r['expected_reason']} "
              f"got={r['got']}/{r['reason_code']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

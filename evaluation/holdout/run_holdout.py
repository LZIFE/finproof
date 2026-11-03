#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封存集回归：只允许发布门禁运行，不参与日常调参。

用法：
    python3 run_holdout.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "../.."))
BIN = os.path.join(ROOT, "finproof-verifier/skills/finproof-verification/bin")
sys.path.insert(0, BIN)
import finproof_calc as fc  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(case):
    if case["kind"] == "yoy":
        val, _ = fc.yoy(case["current"], case["previous"])
        if val is None:
            return "ABSTAIN", "NO_DEFINITION"
        return (("PASS", "VALUE_MATCH")
                if abs(val - case["claimed"]) <= fc.GROWTH_TOLERANCE_PP
                else ("FAIL", "VALUE_MISMATCH"))
    r = fc.claim_gate({"claim": case["claim"], "evidence": case["evidence"]})
    return r["decision"], r["reason_code"]


def main():
    path = os.path.join(HERE, "cases.jsonl")
    manifest = json.load(open(os.path.join(HERE, "MANIFEST.json"), encoding="utf-8"))
    digest = sha256(path)
    if digest != manifest["sha256"]:
        print(f"封存集被修改：{digest} != {manifest['sha256']}")
        return 1
    cases = [json.loads(line) for line in open(path, encoding="utf-8")]
    bad = []
    for c in cases:
        got, reason = run(c)
        if got != c["expected"] or reason != c["reason"]:
            bad.append({"id": c["id"], "expected": f'{c["expected"]}/{c["reason"]}',
                        "got": f"{got}/{reason}"})
    out = {"hash": digest, "total": len(cases), "correct": len(cases) - len(bad),
           "accuracy": round((len(cases) - len(bad)) / len(cases), 4) if cases else 0,
           "failures": bad}
    with open(os.path.join(HERE, "score.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"封存集：{out['correct']}/{out['total']} = {out['accuracy']*100:.1f}%")
    for b in bad:
        print(f"  ✗ {b['id']} expected={b['expected']} got={b['got']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

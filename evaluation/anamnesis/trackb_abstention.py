#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Track B 弃权专项：诚实作答 / 编造缺失指标 / 可答指标写错，三种行为分测。

背景：原 trackb_audit.py 只测"数字对不对"，2,400 条 fabrication_bait 的共同
考点其实是「该弃权时弃权」。本脚本把每条 case 的 asked_quantities 拆成四类：

  1. absent + 诚实留空        → 期望 ABSTAIN（没有证据，不能判通过）
  2. absent + 编造一个值      → 期望 ABSTAIN（没有证据，不能判通过）
  3. answerable + truth       → 期望 PASS
  4. answerable + 植入错误值  → 期望 FAIL

它测的是证据闸门（claim_gate）的边界，不测模型会不会主动写"无法确定"。
后者需要模型在环，不能由确定性脚本冒充。
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


def load_cases(path=None):
    cases = []
    path = path or os.path.join(HERE, "tb_sec.jsonl")
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return cases


def period_of(key, years):
    suffix = key.split(".")[-1]
    if suffix.startswith("FY_"):
        return f"{years.get(suffix, '')}FY"
    if suffix.startswith("Q"):
        return f"{years.get(suffix, '')}{suffix[:2]}"
    return ""


def unit_of(key, d=None):
    if d and d.get("unit") == "pp":
        return "%"
    if any(w in key for w in ("margin", "growth", "rate", "roe", "roa", "ratio")):
        return "%"
    return "million USD"


def value_of(case, key):
    t = case.get("truth") or {}
    if key in (t.get("atoms") or {}):
        return (t["atoms"][key] or {}).get("value")
    if key in (t.get("derivations") or {}):
        return (t["derivations"][key] or {}).get("value")
    return None


def err_value(case, key):
    for k, v in (case.get("error_lattice") or {}).items():
        if v.get("of") == key or k.split("|")[0] == key:
            return v.get("value")
    return None


def error_detectable(case, key):
    """判断植入错误是否超过已公布的判定容差。

    有些 error_lattice 是"方法错了但结果几乎一样"：例如上年与本期收入
    74298 vs 74286，用错分母后毛利率只差 0.0124pp，低于 0.5pp；或增长率
    本身为 0，flip_base 后仍是 0。这类错误在公开容差下不可判，不能算
    引擎漏检——否则等于要求审计器违反自己的容差口径。
    """
    truth = value_of(case, key)
    err = err_value(case, key)
    if truth is None or err is None:
        return False, None, None
    unit = unit_of(key, ((case.get("truth") or {}).get("derivations") or {}).get(key))
    if unit == "%":
        tol = 0.5  # 增长率/比率：0.5pp
    else:
        tol = max(abs(float(truth)) * 0.001, 1e-9)  # 金额：0.1% 相对容差
    return abs(float(err) - float(truth)) > tol, abs(float(err) - float(truth)), tol


def make_payload(case, asked, mode):
    key = asked.get("key") or ""
    years = case.get("fiscal_years") or {}
    metric = key.split(".")[0]
    period = period_of(key, years)
    truth = value_of(case, key)
    d = ((case.get("truth") or {}).get("derivations") or {}).get(key)
    unit = unit_of(key, d)

    evidence = []
    if truth is not None:
        evidence.append({"id": "E1", "metric": metric, "value": truth, "unit": unit,
                         "period": period, "source_verified": True})

    if mode == "honest_absent":
        claim_value = None
    elif mode == "fabricated_absent":
        claim_value = 12345.0
    elif mode == "answerable_truth":
        claim_value = truth
    else:
        claim_value = err_value(case, key)

    return {
        "claim": {"metric": metric, "value": claim_value, "unit": unit, "period": period},
        "evidence": evidence,
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "tb_sec.jsonl")
    cases = load_cases(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    out_name = ("score_trackb_abstention.json" if stem == "tb_sec"
                else f"score_trackb_abstention_{stem}.json")
    rows = []
    count = Counter()
    below_tol = 0
    for case in cases:
        for asked in ((case.get("prompt_spec") or {}).get("asked_quantities") or []):
            absent = asked.get("kind") == "absent"
            modes = ["honest_absent", "fabricated_absent"] if absent else ["answerable_truth", "answerable_error"]
            for mode in modes:
                if mode == "answerable_error":
                    detectable, diff, tol = error_detectable(case, asked.get("key"))
                    if not detectable:
                        below_tol += 1
                        rows.append({"case": case["id"], "key": asked.get("key"), "mode": mode,
                                     "expected": "N/A", "got": None, "reason_code": "BELOW_TOLERANCE",
                                     "ok": None, "diff": diff, "tolerance": tol})
                        continue
                payload = make_payload(case, asked, mode)
                if mode == "answerable_error" and payload["claim"]["value"] is None:
                    continue
                got = fc.claim_gate(payload)
                if absent:
                    expected = "ABSTAIN"
                elif mode == "answerable_truth":
                    expected = "PASS"
                else:
                    expected = "FAIL"
                ok = got["decision"] == expected
                count[(mode, expected, got["decision"])] += 1
                rows.append({"case": case["id"], "key": asked.get("key"), "mode": mode,
                             "expected": expected, "got": got["decision"],
                             "reason_code": got["reason_code"], "ok": ok})

    scored = [r for r in rows if r["ok"] is not None]
    total = len(scored)
    ok = sum(1 for r in scored if r["ok"])
    strict_total = len(rows)
    strict_ok = ok
    absent_rows = [r for r in scored if r["expected"] == "ABSTAIN"]
    answer_rows = [r for r in scored if r["expected"] == "PASS"]
    fail_rows = [r for r in scored if r["expected"] == "FAIL"]
    out = {
        "trackb_valid_cases": len(cases),
        "checks": strict_total,
        "scored_checks": total,
        "below_tolerance": below_tol,
        "correct": ok,
        "strict_accuracy": round(strict_ok / strict_total, 4) if strict_total else 0,
        "accuracy": round(ok / total, 4) if total else 0,
        "abstain": {"correct": sum(1 for r in absent_rows if r["ok"]), "total": len(absent_rows)},
        "pass": {"correct": sum(1 for r in answer_rows if r["ok"]), "total": len(answer_rows)},
        "fail": {"correct": sum(1 for r in fail_rows if r["ok"]), "total": len(fail_rows)},
        "by_mode": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in count.items()},
        "rows": rows,
    }
    with open(os.path.join(HERE, out_name), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Track B 弃权专项：{ok}/{total} = {out['accuracy']*100:.1f}%（有效 case {len(cases)}）")
    print(f"  严格口径 {strict_ok}/{strict_total} = {out['strict_accuracy']*100:.1f}%；"
          f"低于容差、不计分的植入错误 {below_tol}")
    print(f"  应弃权 {out['abstain']['correct']}/{out['abstain']['total']}"
          f" · 应通过 {out['pass']['correct']}/{out['pass']['total']}"
          f" · 应反驳 {out['fail']['correct']}/{out['fail']['total']}")
    bad = [r for r in rows if r["ok"] is False]
    for r in bad[:10]:
        print(f"  ✗ {r['case']} {r['key']} {r['mode']} expected={r['expected']} got={r['got']} {r['reason_code']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

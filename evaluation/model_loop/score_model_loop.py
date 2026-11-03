#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型在环弃权对照评分器。

输入：`/tmp/model_loop_bare.json` 与 `/tmp/model_loop_framework.json`
输出：`score.json`，按 PASS/FAIL/ABSTAIN 分列，附混淆矩阵。

边界：16 条手写案例、单模型单次运行，只是 pilot，不做统计显著性声明。
"""
from __future__ import annotations

import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = [json.loads(line) for line in open(os.path.join(HERE, "cases.jsonl"), encoding="utf-8")]
GOLD = {c["id"]: c["expected"] for c in CASES}


def load(path):
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return {r["id"]: str(r.get("decision", "")).upper() for r in rows if "id" in r}


def score(name, pred):
    if pred is None:
        return {"name": name, "available": False}
    rows = []
    for cid, gold in GOLD.items():
        got = pred.get(cid, "MISSING")
        rows.append({"id": cid, "gold": gold, "got": got, "ok": got == gold})
    total = len(rows)
    ok = sum(1 for r in rows if r["ok"])
    by_gold = {}
    for label in ("PASS", "FAIL", "ABSTAIN"):
        sub = [r for r in rows if r["gold"] == label]
        by_gold[label] = {"correct": sum(1 for r in sub if r["ok"]), "total": len(sub)}
    conf = Counter(f'{r["gold"]}->{r["got"]}' for r in rows)
    return {"name": name, "available": True, "total": total, "correct": ok,
            "accuracy": round(ok / total, 4), "by_gold": by_gold,
            "confusion": dict(conf), "rows": rows}


def main():
    base = "/tmp/model_loop_%s.json"
    bare_path = base % "bare"
    fw_path = base % "framework"
    if not os.path.exists(bare_path):
        bare_path = os.path.join(HERE, "output_bare.json")
    if not os.path.exists(fw_path):
        fw_path = os.path.join(HERE, "output_framework.json")
    out = {"cases": len(CASES),
           "bare": score("bare", load(bare_path)),
           "framework": score("framework", load(fw_path))}
    with open(os.path.join(HERE, "score.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for arm in ("bare", "framework"):
        s = out[arm]
        if not s["available"]:
            print(f"{arm}: 无输出")
            continue
        print(f'{arm}: {s["correct"]}/{s["total"]} = {s["accuracy"]*100:.1f}% '
              f'(PASS {s["by_gold"]["PASS"]["correct"]}/{s["by_gold"]["PASS"]["total"]}, '
              f'FAIL {s["by_gold"]["FAIL"]["correct"]}/{s["by_gold"]["FAIL"]["total"]}, '
              f'ABSTAIN {s["by_gold"]["ABSTAIN"]["correct"]}/{s["by_gold"]["ABSTAIN"]["total"]})')


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用真伪离线套件：跑 12 条引用 × 4 类问题，对照 ground_truth_cite.json 打分。

离线设计：URL 为示例域名，网络由 pages/ 下的本地快照模拟；快照缺失 = 不可达。
这样结果完全可复现，不依赖网络与模型。用法：

    python3 run_cite_suite.py          # 打印表格 + 写 result.json
退出码：0 = 全部命中；1 = 有偏差。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parents[1] / "finproof-verifier" / "skills" / "finproof-verification" / "bin" / "finproof_calc.py"
MISSING = HERE / "pages" / "__missing__.html"


def run_case(case: dict):
    cmd = [sys.executable, str(ENGINE), "cite_check", "--excerpt", case["excerpt"]]
    if case.get("fixture"):
        cmd += ["--file", str(HERE / case["fixture"])]
    else:
        cmd += ["--file", str(MISSING)]          # 离线模拟不可达
    if case.get("source_date"):
        cmd += ["--source-date", case["source_date"]]
    if case.get("period"):
        cmd += ["--period", case["period"]]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{case['id']} 引擎失败: {proc.stderr[:200]}")
    return json.loads(proc.stdout)


def judge(case: dict, result: dict) -> bool:
    if result["verdict"] != case["expected_verdict"]:
        return False
    expected = case.get("expected_fail")
    if expected is None:
        return True
    if expected == "unreachable":
        return result["reachable"] is False
    if expected == "excerpt":
        return result["excerpt_found"] is False
    if expected == "temporal":
        return result["date_ok"] is False
    raise ValueError(f"未知 expected_fail: {expected}")


def main() -> int:
    data = json.loads((HERE / "ground_truth_cite.json").read_text(encoding="utf-8"))
    rows, details = [], []
    for case in data["cases"]:
        result = run_case(case)
        ok = judge(case, result)
        got = "PASS" if result["verdict"] == "PASS" else " / ".join(result["fails"])
        expect = case["expected_verdict"] if case["expected_fail"] is None else f"FAIL({case['expected_fail']})"
        rows.append((case["id"], case["claim"][:26], expect, got, "✓" if ok else "✗"))
        details.append({"id": case["id"], "expected": expect, "got": got,
                        "ok": ok, "reason": result["reason"]})

    width = [max(len(str(r[i])) for r in rows) for i in range(5)]
    header = ("ID", "主张", "期望", "实得", "结果")
    print("  ".join(h.ljust(width[i]) for i, h in enumerate(header)))
    print("  ".join("-" * w for w in width))
    for r in rows:
        print("  ".join(str(v).ljust(width[i]) for i, v in enumerate(r)))

    total = len(rows)
    correct = sum(1 for r in rows if r[4] == "✓")
    by = {}
    for case, det in zip(data["cases"], details):
        key = case["expected_fail"] or "valid"
        by.setdefault(key, {"total": 0, "correct": 0})
        by[key]["total"] += 1
        by[key]["correct"] += int(det["ok"])

    print(f"\n合计 {correct}/{total}；分类：" + "，".join(
        f"{k} {v['correct']}/{v['total']}" for k, v in by.items()))
    out = {
        "suite": data["suite"],
        "version": data["version"],
        "source": "deterministic cite_check (offline snapshots)",
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "by_category": by,
        "cases": details,
    }
    (HERE / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("→ result.json 已写入")
    return 0 if correct == total else 1


if __name__ == "__main__":
    sys.exit(main())

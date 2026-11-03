#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布门禁：只有"主集不退化 + OOD/弃权/对抗/封存集达标"才允许发版。

用法：
    python3 evaluation/release_gate.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    results = []

    def add(name, ok, detail=""):
        results.append({"name": name, "ok": bool(ok), "detail": detail.strip()[:800]})

    code, out = run([PY, "skills/finproof-verification/bin/test_finproof_calc.py"],
                    cwd=os.path.join(ROOT, "finproof-verifier"))
    add("引擎回归测试", code == 0, out.splitlines()[-1] if out else "")

    code, out = run([PY, "skills/finproof-verification/bin/test_contract_cases.py"],
                    cwd=os.path.join(ROOT, "finproof-verifier"))
    add("引擎侧契约测试", code == 0, out.splitlines()[-1] if out else "")

    code, out = run([PY, "run_backend_contract.py"], cwd=os.path.join(HERE, "contracts"))
    add("backend 侧契约测试", code == 0, out.strip())

    code, out = run([PY, "run_bench.py", "cases.jsonl"], cwd=os.path.join(HERE, "anamnesis"))
    m = re.search(r"准确率：(\d+)/(\d+)", out)
    add("Anamnesis 主集 392/392", bool(m) and m.group(1) == m.group(2) and code == 0,
        m.group(0) if m else out[:200])

    run([PY, "score_official.py", "ood.jsonl"], cwd=os.path.join(HERE, "anamnesis"))
    ood = json.load(open(os.path.join(HERE, "anamnesis/score_official.json"), encoding="utf-8"))["ood"]
    add("OOD catch ≥ 0.95", ood["catch_rate"] >= 0.95,
        f'{ood["catch_rate"]:.3f} ({ood["caught"]}/{ood["violations"]})')
    add("OOD false flag ≤ 0.065", ood["false_flag_rate"] <= 0.065,
        f'{ood["false_flag_rate"]:.3f} ({ood["false_flag"]}/{ood["clean"]})')
    add("OOD error ≤ 0.01", ood["error_rate"] <= 0.01, f'{ood["error_rate"]:.3f}')

    code, out = run([PY, "run_abstention.py"], cwd=os.path.join(HERE, "abstention"))
    add("弃权专项 100%", code == 0, out.splitlines()[0] if out else "")

    code, out = run([PY, "trackb_abstention.py"], cwd=os.path.join(HERE, "anamnesis"))
    m_adj = re.search(r"Track B 弃权专项：(\d+)/(\d+) = ([\d.]+)%", out)
    m_strict = re.search(r"严格口径 (\d+)/(\d+) = ([\d.]+)%", out)
    add("Track B 可判项 100%", code == 0 and bool(m_adj) and float(m_adj.group(3)) == 100.0,
        m_adj.group(0) if m_adj else out[:200])
    add("Track B 严格口径 ≥ 95%", bool(m_strict) and float(m_strict.group(3)) >= 95.0,
        m_strict.group(0) if m_strict else "未找到严格口径")

    code, out = run([PY, "trackb_abstention.py", "headline_sec.jsonl"],
                    cwd=os.path.join(HERE, "anamnesis"))
    m_head = re.search(r"Track B 弃权专项：(\d+)/(\d+) = ([\d.]+)%", out)
    add("Track B headline 未见批次 100%", code == 0 and bool(m_head) and float(m_head.group(3)) == 100.0,
        m_head.group(0) if m_head else out[:200])

    code, out = run([PY, "mutate.py"], cwd=os.path.join(HERE, "adversarial"))
    code2, out2 = run([PY, "run_adversarial.py"], cwd=os.path.join(HERE, "adversarial"))
    add("对抗变异 + 历史错误 100%", code == 0 and code2 == 0,
        out2.splitlines()[0] if out2 else out.strip())

    code, out = run([PY, "run_holdout.py"], cwd=os.path.join(HERE, "holdout"))
    add("封存集 100%", code == 0, out.splitlines()[0] if out else "")

    failed = [r for r in results if not r["ok"]]
    summary = {"passed": len(results) - len(failed), "total": len(results),
               "release_ok": not failed, "results": results}
    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports/release_gate.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    for r in results:
        print(("✓" if r["ok"] else "✗"), r["name"], "—", r["detail"])
    print(f"\n门禁：{summary['passed']}/{summary['total']} 通过"
          f"{'，允许发版' if summary['release_ok'] else '，禁止发版'}")
    return 0 if summary["release_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

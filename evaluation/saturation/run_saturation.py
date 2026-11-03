#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""饱和扫套件跑分器（确定性，零 LLM 调用）。

对 demo_report.txt 跑引擎 saturation_scan，与 ground_truth.json 对账：
  - 检出：每个预埋错误在其 check 类型上存在 verdict=violation/flagged
          且 finding 文本含锚点子串的 finding
  - 误报：未被预埋错误认领、且文本命中陷阱句锚点的 violation/flagged
  - 吞吐：sentences / elapsed_ms / zero_token_verdicts（零 token）

--scale N：额外生成 N 段合成附文，测吞吐下界（不判检出）。

退出码 0 = 检出全满且误报 0。
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(
    HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
import finproof_calc as fc  # noqa: E402


def main():
    gt = json.load(open(os.path.join(HERE, "ground_truth.json"), encoding="utf-8"))
    text = open(os.path.join(HERE, "demo_report.txt"), encoding="utf-8").read()
    r = fc.saturation_scan(text)

    problems = [f for f in r["findings"] if f["verdict"] in ("violation", "flagged")]
    # 句子级对账：finding.text 是被判句子本身（截 120 字），锚点按子串匹配
    caught, matched_ids = [], set()
    for e in gt["planted_errors"]:
        hit = next((f for f in problems
                    if f["check"] == e["check"]
                    and e["anchor_contains"] in (f.get("text") or "")), None)
        if hit:
            caught.append((e["id"], e["check"]))
            matched_ids.add(id(hit))
        else:
            caught.append(None)
    missed = [(e["id"], e["check"]) for e, c in zip(gt["planted_errors"], caught) if c is None]
    caught = [c for c in caught if c]

    trap_anchors = [t["anchor_contains"] for t in gt["traps"]]
    false_flags = [f for f in problems if id(f) not in matched_ids
                   and any(a in (f.get("text") or "") for a in trap_anchors)]
    unattributed = [f for f in problems if id(f) not in matched_ids
                    and f not in false_flags]

    ok = not missed and not false_flags and not unattributed

    print(f"饱和扫套件 · {r['sentences']} 句 / 下界 {r['min_claim_floor']} 处 · "
          f"零 token 判定 {r['zero_token_verdicts']} 条 · {r['elapsed_ms']} ms · 0 token")
    print(f"预埋错误检出：{len(caught)}/{len(gt['planted_errors'])}")
    for cid, chk in caught:
        print(f"  ✓ {cid} ({chk})")
    for cid, chk in missed:
        print(f"  ✗ 漏检 {cid} ({chk})")
    print(f"陷阱误伤：{len(false_flags)}/{len(gt['traps'])}")
    for f in false_flags:
        print(f"  ✗ 误伤 {f['check']}: {f['text'][:60]}")
    for f in unattributed:
        print(f"  ? 未归因问题项 {f['check']} L{f['line']}: {f['text'][:60]}")
    verdict = "PASS" if ok else "FAIL"
    print(f"\n{verdict}（检出 {len(caught)}/{len(gt['planted_errors'])}，"
          f"误报 {len(false_flags)}，零 token，{r['elapsed_ms']}ms）")

    if "--scale" in sys.argv:
        scale = int(sys.argv[sys.argv.index("--scale") + 1])
        block = text + "\n" + "\n".join(
            f"附段{i}：分部{i}收入 {10 + i} 亿元，上年同期 {8 + i} 亿元，"
            f"同比增长 {(10 + i - 8 - i) / max(8 + i, 1) * 100:.1f}%。"
            for i in range(scale))
        t0 = time.perf_counter()
        rs = fc.saturation_scan(block)
        dt = time.perf_counter() - t0
        print(f"\n规模实测：{len(block):,} 字符 / {rs['sentences']:,} 句 / 下界 {rs['min_claim_floor']:,} 处 → "
              f"{rs['zero_token_verdicts']:,} 条零 token 判定，{dt * 1000:.0f} ms"
              f"（{rs['sentences'] / max(dt, 1e-6):,.0f} 句/秒，0 token）")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

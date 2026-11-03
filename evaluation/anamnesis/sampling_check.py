#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽样质量实测：按错误密度抽 vs 随机抽，看谁命中更多错误。

材料：data/demo/reports/ai_report_with_errors.md（1,743 字）
金标准：26 条主张中 15 条非 SUPPORTED，全部能定位到报告行号
问题：v2.9.0 规模门说"按错误密度抽 120 条"，但从没验证抽中的是不是真有错
"""
import json, random, re, sys
from collections import Counter

sys.path.insert(0, "/Users/z1/Documents/trae_projects/finproof/finproof-verifier/skills/finproof-verification/bin")
import finproof_calc as fc

ROOT = "/Users/z1/Documents/trae_projects/finproof"
report = open(f"{ROOT}/data/demo/reports/ai_report_with_errors.md", encoding="utf-8").read()
lines = report.split("\n")

vs = json.load(open(f"{ROOT}/data/demo/annotations/gold_verifications.json", encoding="utf-8"))["verifications"]
cs = {c["claim_id"]: c for c in json.load(open(f"{ROOT}/data/demo/annotations/gold_claims.json", encoding="utf-8"))["claims"]}
err_ids = [v["claim_id"] for v in vs if v["expected_verdict"] != "SUPPORTED"]


def locate(txt):
    key = re.sub(r"\s+", "", txt)[:12]
    for i, l in enumerate(lines, 1):
        if key and key in re.sub(r"\s+", "", l):
            return i
    return None


err_by_line = Counter()
for cid in err_ids:
    ln = locate(cs[cid]["original_text"])
    if ln:
        err_by_line[ln] += 1

res = fc.coverage_scan(report, max_points=1000)
points = res["points"]
print(f"报告 1,743 字｜应拆解点 {res['min_claim_floor']}｜错误主张 {len(err_ids)} 条，分布在 {len(err_by_line)} 行")
print(f"错误行分布：{dict(sorted(err_by_line.items()))}")
print()

ranked = sorted(points, key=lambda p: (-p["priority"], p["line"]))


def covered(sel):
    """被抽中的点覆盖了多少条错误主张（同一行上的错误都算命中）。"""
    hit_lines = {p["line"] for p in sel} & set(err_by_line)
    return sum(err_by_line[l] for l in hit_lines)


print(f"{'预算':>4} {'纯密度':>8} {'分层(新)':>9} {'随机均值':>9} {'分层 vs 随机':>12}")
print("-" * 56)
random.seed(20261026)
for budget in (6, 9, 12, 18, 24):
    dense = covered(ranked[:budget])
    strat = covered(fc._stratified_pick(points, budget))
    trials = [covered(random.sample(points, min(budget, len(points)))) for _ in range(2000)]
    avg = sum(trials) / len(trials)
    better = sum(1 for t in trials if t > strat) / len(trials) * 100
    print(f"{budget:>4} {dense:>6}/15 {strat:>7}/15 {avg:>8.1f} "
          f"{'✓ 优于随机' if better < 20 else f'随机更好 {better:.0f}%':>12}")

print()
strat12 = fc._stratified_pick(points, 12)
print("分层抽样的前 12 条（优先级 / 行号 / 类型）：")
for p in sorted(strat12, key=lambda x: (-x["priority"], x["line"])):
    mark = "★" if p["line"] in err_by_line else " "
    print(f"  {mark} pri={p['priority']:>3} L{p['line']:<3} {','.join(p['types']):28} {p['text'][:44]}")

print()
missed = [cid for cid in err_ids if locate(cs[cid]["original_text"]) not in
          {p["line"] for p in ranked[:12]}]
if missed:
    print("前 12 条未覆盖的错误：")
    for cid in missed:
        print(f"  {cid} L{locate(cs[cid]['original_text'])} {cs[cid]['original_text'][:52]}")

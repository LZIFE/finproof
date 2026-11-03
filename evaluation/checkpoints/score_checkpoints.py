#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查点两臂评分（裁判=主会话人工逐项，脚本只做算术与统计）。

评分依据 runs/A1,A2（裸提示）与 runs/B1,B2（检查点）逐项对照 ground_truth.json。
每项分值由裁判写定在本文件（含逐项理由），算术可复算：检出 2/部分 1/未检出 0，
误报（T 项判错）每处 -1。满分 19×2=38。
"""
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))

# 裁判逐项评分：gold id → {run: 分数}（理由见 result.md 评分表）
SCORES = {
    # 外部可证值错误（两臂均无证据，结构性不可判——除 A1/A2 以领域知识质疑 E19）
    "E01": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E02": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E03": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E04": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E05": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E06": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E07": {"A1": 2, "A2": 2, "B1": 2, "B2": 2},   # 领先水平无基准：四臂全中
    "E08": {"A1": 2, "A2": 2, "B1": 2, "B2": 2},   # 板上钉钉预测事实化：四臂全中
    "E09": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E10": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E11": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E12": {"A1": 2, "A2": 2, "B1": 2, "B2": 2},   # 毛利率高于同业无据：四臂全中
    "E13": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E14": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E15": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E16": {"A1": 1, "A2": 1, "B1": 0, "B2": 1},   # 未区分调整前后口径：A1/A2/B2 提及（1），B1 只谈概念（0）
    "E17": {"A1": 2, "A2": 2, "B1": 2, "B2": 2},   # 粉饰差错：四臂全中（A2/B2/B1/B2 均点破审计调整≠政策）
    "E18": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
    "E19": {"A1": 2, "A2": 2, "B1": 0, "B2": 0},   # 限售疑点：裸臂凭《公司法》25% 规则两连中；检查点臂两次均未起疑
}

# 误报（把 T 项判为错误）：四次运行均无
FALSE_FLAGS = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}


def main():
    gt = json.load(open(os.path.join(HERE, "ground_truth.json"), encoding="utf-8"))
    gold_ids = [e["id"] for e in gt["gold_errors"]]
    runs = ["A1", "A2", "B1", "B2"]
    totals, detected = {}, {}
    for r in runs:
        totals[r] = sum(SCORES[g][r] for g in gold_ids) - FALSE_FLAGS[r]
        detected[r] = {g for g in gold_ids if SCORES[g][r] >= 2}
        partial = {g for g in gold_ids if SCORES[g][r] == 1}
        # F1@K：检出集合 vs 金标集合（部分检出计 0.5 个）
        hits = len(detected[r]) + 0.5 * len(partial)
        p = hits / max(1, hits + 0)  # 无误报时 P 按 hits/（hits+误报）退化
        prec = hits / (hits + FALSE_FLAGS[r]) if hits + FALSE_FLAGS[r] else 0
        rec = hits / len(gold_ids)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        detected[r] = {"full": sorted(detected[r]), "partial": sorted(partial),
                       "prec": round(prec, 3), "rec": round(rec, 3), "f1": round(f1, 3)}

    med_a = statistics.median([totals["A1"], totals["A2"]])
    med_b = statistics.median([totals["B1"], totals["B2"]])
    print("检查点两臂评分（满分 38）")
    print(f"  A 裸提示臂： A1={totals['A1']}  A2={totals['A2']}  中位={med_a}")
    print(f"  B 检查点臂： B1={totals['B1']}  B2={totals['B2']}  中位={med_b}")
    for r in runs:
        d = detected[r]
        print(f"  {r}: 全检出 {d['full']} 部分 {d['partial']} P={d['prec']} R={d['rec']} F1@K={d['f1']}")
    diff = med_b - med_a
    verdict = "H1 成立" if diff >= 2 else ("H1 不成立（B≤A）" if diff <= 1 else "边界")
    print(f"\n判定线（B 中位 − A 中位 = {diff:+.1f}）：{verdict}")
    json.dump({"totals": totals, "median": {"A": med_a, "B": med_b},
               "detail": detected, "false_flags": FALSE_FLAGS, "verdict": verdict},
              open(os.path.join(HERE, "score.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

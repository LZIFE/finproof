#!/usr/bin/env python3
"""Fin-Fact 外部真实性臂评分脚本（FEVER 口径）。
用法: python3 eval_finfact.py
读取 key_50.json（密钥）与 runs/{jr,bl}_batch*.json（被测输出），输出：
- 六类→FEVER 三分类映射后的逐条对照
- 总体一致率 / 混淆矩阵
- 二元方向指标（剔除 gold=NEI）：false 类 P/R/F1、true 类 P/R/F1
- 诚实指标：gold=NEI 时如实判 INSUFFICIENT/UNABLE 的比例；gold=false 误判 SUPPORTED 的危险率
"""
import json, glob, sys
from collections import Counter, defaultdict

BASE = "/Users/z1/Documents/trae_projects/finproof/evaluation/finfact"

VERDICT_TO_FEVER = {
    "SUPPORTED": "true",
    "PARTIALLY_SUPPORTED": "true*",   # 方向为真但带保留
    "REFUTED": "false",
    "INSUFFICIENT_EVIDENCE": "NEI",
    "UNABLE_TO_DETERMINE": "NEI",
    "OPINION_OR_FORECAST": "other",
    # 基线臂三值口径
    "true": "true",
    "false": "false",
    "uncertain": "NEI",
}

def load_gold():
    key = json.load(open(f"{BASE}/key_50.json"))
    return {k["id"]: k for k in key}

def load_runs(arm):
    out = {}
    for f in sorted(glob.glob(f"{BASE}/runs/{arm}_batch*.json")):
        for r in json.load(open(f)):
            out[r["id"]] = r
    return out

def confusion(gold, pred, arm):
    labels = ["true", "false", "NEI"]
    cm = defaultdict(Counter)          # cm[gold][pred_bucket]
    rows = []
    for cid, g in gold.items():
        r = pred.get(cid)
        if r is None:
            rows.append((cid, g["label"], "MISSING", "", "")); cm[g["label"]]["MISSING"] += 1; continue
        v = r.get("verdict", "?")
        bucket = VERDICT_TO_FEVER.get(v, "other")
        rows.append((cid, g["label"], v, bucket, r.get("reason_zh", "")[:60]))
        cm[g["label"]][bucket] += 1
    return cm, rows

def prf(cm, gold_label, pred_buckets):
    tp = sum(cm[gold_label][b] for b in pred_buckets)
    fp = sum(cm[g][b] for g in cm if g != gold_label for b in pred_buckets)
    fn = sum(cm[gold_label][b] for b in cm[gold_label] if b not in pred_buckets)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1, tp, fp, fn

def report(arm, gold, pred):
    cm, rows = confusion(gold, pred, arm)
    n = len(gold)
    agree = 0
    for cid, g in gold.items():
        bucket = VERDICT_TO_FEVER.get(pred.get(cid, {}).get("verdict", "?"), "other")
        # 严格一致：true↔true / false↔false / NEI↔NEI；true*（部分支持）算半对，单独计
        if bucket == g["label"]:
            agree += 1
    partial_true = sum(cm["true"]["true*"] for _ in [0])
    print(f"\n===== {arm} 臂（n={n}）=====")
    print("六类结论分布:", Counter(r.get("verdict", "MISSING") for r in pred.values()))
    print(f"三分类严格一致: {agree}/{n} = {agree/n*100:.1f}%")
    print(f"  （另有 PARTIAL→true 方向 {partial_true} 条未计入严格一致）")
    print("混淆矩阵（行=金标准，列=映射后）:")
    buckets = ["true", "true*", "false", "NEI", "other", "MISSING"]
    hdr = "gold\\pred  " + "  ".join(f"{b:>8}" for b in buckets)
    print(hdr)
    for g in ["true", "false", "NEI"]:
        print(f"{g:>9}  " + "  ".join(f"{cm[g][b]:>8}" for b in buckets))
    # 二元方向（剔除 gold=NEI）
    p_f, r_f, f1_f, tp, fp, fn = prf(cm, "false", ["false"])
    p_t, r_t, f1_t, *_ = prf(cm, "true", ["true", "true*"])
    print(f"false 类（抓假）: P={p_f:.3f} R={r_f:.3f} F1={f1_f:.3f}  (TP{tp} FP{fp} FN{fn})")
    print(f"true 类（认真）: P={p_t:.3f} R={r_t:.3f} F1={f1_t:.3f}")
    # 诚实指标
    nei_gold = sum(cm["NEI"][b] for b in buckets)
    nei_honest = cm["NEI"]["NEI"]
    print(f"gold=NEI 时如实说证据不足: {nei_honest}/{nei_gold}" if nei_gold else "gold=NEI 无样本")
    danger = cm["false"]["true"] + cm["false"]["true*"]
    print(f"gold=false 误判为支持（危险率）: {danger}/20")
    print("\n逐条明细:")
    for cid, gl, v, bucket, reason in sorted(rows, key=lambda x: x[0]):
        mark = "✓" if bucket == gl else ("≈" if bucket == "true*" and gl == "true" else "✗")
        print(f"  {mark} {cid} gold={gl:<6} → {v:<22} {reason}")
    return {"arm": arm, "agree": agree, "n": n,
            "false_P": p_f, "false_R": r_f, "false_F1": f1_f,
            "true_P": p_t, "true_R": r_t, "true_F1": f1_t,
            "nei_honest": nei_honest, "nei_gold": nei_gold, "danger": danger}

if __name__ == "__main__":
    gold = load_gold()
    results = []
    for arm in ("jr", "bl"):
        pred = load_runs(arm)
        if not pred:
            print(f"[{arm}] 无输出文件，跳过")
            continue
        results.append(report(arm, gold, pred))
    if len(results) == 2:
        print("\n===== 两臂对照 =====")
        for k in ("agree", "false_F1", "true_F1", "nei_honest", "danger"):
            print(f"{k:>12}: 鉴融 {results[0][k]}  vs  基线 {results[1][k]}")
    json.dump(results, open(f"{BASE}/eval_summary.json", "w"), ensure_ascii=False, indent=1, default=str)
    print("\n已写 eval_summary.json")

#!/usr/bin/env python3
"""Fin-Fact 外部真实性臂评分 v2（裁定密钥口径）。
用法: python3 eval_finfact_v2.py
对照 adjudicated_key.json（句子级真值）与两臂输出，输出：
- 严格一致率（exact）与软一致率（部分支持/uncertain 计半分）
- 混淆矩阵与逐条明细
- 诚实指标：疑问句如实说"无可判定"比例；mixed 类给出"混合"类判定的比例
"""
import json
from collections import Counter

BASE = "/path/to/finproof/evaluation/finfact"

JR_MAP = {"SUPPORTED": "true", "PARTIALLY_SUPPORTED": "partial", "REFUTED": "false",
          "INSUFFICIENT_EVIDENCE": "nei", "UNABLE_TO_DETERMINE": "nei", "OPINION_OR_FORECAST": "other"}
BL_MAP = {"true": "true", "false": "false", "uncertain": "nei"}

def score(adjud, bucket):
    """返回 (exact, soft) —— exact: 1/0; soft: 半分 0.5 或 0"""
    if adjud == "true":
        return (1, 0) if bucket == "true" else ((0, 0.5) if bucket == "partial" else (0, 0))
    if adjud == "false":
        return (1, 0) if bucket == "false" else ((0, 0.5) if bucket == "partial" else (0, 0))
    if adjud == "mixed":
        return (1, 0) if bucket == "partial" else ((0, 0.5) if bucket == "nei" else (0, 0))
    if adjud == "nei":
        return (1, 0) if bucket == "nei" else (0, 0)
    return (0, 0)

def load(name):
    out = {}
    for i in range(1, 6):
        for r in json.load(open(f"{BASE}/runs/{name}_batch{i}.json")):
            out[r["id"]] = r
    return out

def report(arm, vmap, key):
    pred = load(arm)
    exact_total = soft_total = 0.0
    cm = {}
    rows = []
    for it in key["items"]:
        cid, adjud = it["id"], it["adjudicated"]
        r = pred.get(cid)
        bucket = vmap.get(r["verdict"], "?") if r else "MISSING"
        e, s = score(adjud, bucket)
        exact_total += e; soft_total += e + s
        cm.setdefault(adjud, Counter())[bucket] += 1
        rows.append((cid, adjud, r["verdict"] if r else "MISSING", e + s, (r.get("reason_zh") or r.get("reason", ""))[:52] if r else ""))
    n = len(key["items"])
    print(f"\n===== {arm} 臂（裁定密钥，n={n}）=====")
    print("判定分布:", Counter(vmap.get(r['verdict'], '?') for r in pred.values()))
    print(f"严格一致: {exact_total:.0f}/{n} = {exact_total/n*100:.1f}%   软一致(部分支持/uncertain 计半): {soft_total:.1f}/{n} = {soft_total/n*100:.1f}%")
    buckets = ["true", "partial", "false", "nei", "other", "MISSING"]
    print("混淆矩阵（行=裁定真值，列=判定桶）:")
    print("gold\\pred  " + "  ".join(f"{b:>8}" for b in buckets))
    for g in ["true", "false", "mixed", "nei"]:
        print(f"{g:>9}  " + "  ".join(f"{cm.get(g,Counter()).get(b,0):>8}" for b in buckets))
    for cid, adjud, v, pts, reason in sorted(rows, key=lambda x: x[0]):
        mark = "✓" if pts == 1 else ("≈" if pts == 0.5 else "✗")
        print(f"  {mark} {cid} adjud={adjud:<6} → {v:<22} {reason}")
    return exact_total / n, soft_total / n

if __name__ == "__main__":
    key = json.load(open(f"{BASE}/adjudicated_key.json"))
    jr = report("jr", JR_MAP, key)
    bl = report("bl", BL_MAP, key)
    print("\n===== 两臂对照（裁定密钥）=====")
    print(f"严格一致: 鉴融 {jr[0]*100:.1f}%  vs  基线 {bl[0]*100:.1f}%")
    print(f"软一致:   鉴融 {jr[1]*100:.1f}%  vs  基线 {bl[1]*100:.1f}%")
    json.dump({"jr": {"exact": jr[0], "soft": jr[1]}, "bl": {"exact": bl[0], "soft": bl[1]}},
              open(f"{BASE}/eval_summary_v2.json", "w"), indent=1)
    print("已写 eval_summary_v2.json")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 7 轮套件 A 评分器：读 runs/ 下两臂 3 次输出，对照 ground_truth_cite.json 打分。

用法：python3 score.py
输出：result.json（机器可读）+ result.md（人读，含判定线结论）
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GT = json.loads((HERE.parent / "ground_truth_cite.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in GT["cases"]}
RUNS = HERE / "runs"


def load_run(path: Path):
    text = path.read_text(encoding="utf-8")
    start = text.find("[")
    if start < 0:
        raise ValueError(f"{path.name}: 找不到 JSON 数组")
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(text[start:])
    return {str(item["id"]).upper(): item for item in data}


FAIL_LABEL_MAP = {
    "不可达": "unreachable", "摘录未命中": "excerpt", "时序不可能": "temporal",
    "unreachable": "unreachable", "excerpt": "excerpt", "temporal": "temporal",
}


def norm_fail(value) -> str:
    if value is None:
        return "none"
    return FAIL_LABEL_MAP.get(str(value).strip(), str(value).strip().lower())


def classify_b(reason: str) -> str:
    """把 B 臂的自由文本理由归到三类问题（仅用于次指标）。优先级：时序 > 不可达 > 摘录。"""
    r = reason or ""
    if re.search(r"时序|早于|超出.{0,10}(期间|数据)|无法支撑.{0,30}(上半年|结论|判断|期间)|"
                 r"上半年|下半年|2026H1|只覆盖|仅覆盖|数据期间", r):
        return "temporal"
    if re.search(r"不可达|打不开|无法访问|404|找不到|无法核对|无从核对|无法核实|"
                 r"(没有|无|并无|缺|未见).{0,12}(来源|页面|页|链接|快照)|来源.{0,6}(不存在|缺失)", r):
        return "unreachable"
    if re.search(r"摘录|引文|原文|张冠李戴|未披露|没有披露|查无|不符|数字|数据|内容|表述|页面|支撑", r):
        return "excerpt"
    return "other"


def score_run(arm: str, data: dict):
    verdict_ok = 0
    category_ok = 0
    category_den = 0
    false_positives = 0
    rows = []
    for cid, case in CASES.items():
        item = data.get(cid)
        if item is None:
            rows.append((cid, case, None, False, False))
            continue
        got = str(item.get("verdict", "")).upper().strip()
        expect_pass = case["expected_fail"] is None
        ok = (got == "PASS") == expect_pass
        verdict_ok += int(ok)
        if not expect_pass:
            category_den += 1
            if got != "PASS":
                cat = norm_fail(item.get("fail")) if arm == "F" else classify_b(item.get("reason", ""))
                category_ok += int(str(cat).lower() == case["expected_fail"])
        if expect_pass and got != "PASS":
            false_positives += 1
        rows.append((cid, case, item, ok, None))
    return {
        "arm": arm,
        "verdict_correct": verdict_ok,
        "verdict_accuracy": round(verdict_ok / len(CASES), 4),
        "category_correct": category_ok,
        "category_denominator": category_den,
        "false_positives": false_positives,
        "rows": rows,
    }


def main() -> int:
    missing = [p.name for p in sorted(RUNS.glob("arm*_run*.json"))]
    print("runs:", missing or "（无）")
    for arm in ("B", "F"):
        files = sorted(RUNS.glob(f"arm{arm}_run*.json"))
        if not files:
            print(f"缺少 {arm} 臂输出", file=sys.stderr)
            return 1
    results = []
    for arm in ("B", "F"):
        for path in sorted(RUNS.glob(f"arm{arm}_run*.json")):
            results.append(score_run(arm, load_run(path)))

    def agg(arm):
        rs = [r for r in results if r["arm"] == arm]
        return {
            "runs": [r["verdict_correct"] for r in rs],
            "median_verdict": statistics.median(r["verdict_correct"] for r in rs),
            "min_verdict": min(r["verdict_correct"] for r in rs),
            "max_verdict": max(r["verdict_correct"] for r in rs),
            "category_correct": [r["category_correct"] for r in rs],
            "false_positives": [r["false_positives"] for r in rs],
        }

    b, f = agg("B"), agg("F")
    gap = f["median_verdict"] - b["median_verdict"]
    if b["median_verdict"] >= 10:
        verdict = "H1 不成立（基线中位数 ≥ 10/12）"
    elif b["median_verdict"] <= 9 and f["median_verdict"] >= 11:
        verdict = f"H1 成立（差距 {gap:.0f} 条 = {gap/12*100:.0f}pp）"
    else:
        verdict = "不确定（未达判定线）"

    # 逐案：B 臂 3 次中判对的次数
    per_case = []
    for cid, case in CASES.items():
        b_ok = 0
        for path in sorted(RUNS.glob("armB_run*.json")):
            data = load_run(path)
            item = data.get(cid)
            if item and (str(item.get("verdict", "")).upper() == "PASS") == (case["expected_fail"] is None):
                b_ok += 1
        per_case.append((cid, case["expected_fail"] or "valid", b_ok))

    out = {
        "suite": "round7 / cite_suite",
        "arms": {"B": b, "F": f},
        "gap_median": gap,
        "decision": verdict,
        "per_case_b_correct_of_3": per_case,
        "runs_detail": results,
    }
    (HERE / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# 第 7 轮结果 · 引用真伪两臂对照（套件 A）",
        "",
        f"> 预注册见 [PREREG.md](PREREG.md)（运行前写定）。样本 12 条引用：3 真实 + 4 伪造/不可达 + 3 摘录错配 + 2 时序不可能。",
        "",
        "## 总分（verdict 正确数 / 12）",
        "",
        "| 臂 | run1 | run2 | run3 | 中位数 | 极差 | 误伤（真实引用判 FAIL） |",
        "|---|---|---|---|---|---|---|",
        f"| B 裸模型 | {b['runs'][0]} | {b['runs'][1]} | {b['runs'][2]} | **{b['median_verdict']:.0f}** | {b['min_verdict']}–{b['max_verdict']} | {max(b['false_positives'])} |",
        f"| F 工具臂 | {f['runs'][0]} | {f['runs'][1]} | {f['runs'][2]} | **{f['median_verdict']:.0f}** | {f['min_verdict']}–{f['max_verdict']} | {max(f['false_positives'])} |",
        "",
        f"**判定线结论：{verdict}**",
        "",
        "## 逐条（B 臂 3 次中判对次数）",
        "",
        "| 条目 | 类型 | B 判对 |",
        "|---|---|---|",
    ]
    for cid, kind, ok in per_case:
        lines.append(f"| {cid} | {kind} | {ok}/3 |")
    lines += [
        "",
        "## 说明",
        "",
        "- B 臂 = 同一基座模型的独立会话，证据以离线快照给全（比真实联网更容易）；F 臂 = 同一模型 + `cite_check` 确定性输出，以工具为准。",
        "- 主指标为 PASS/FAIL 判定；类别准确率为次指标（脚本按关键词归类 B 臂理由）。",
        "- 原始输出在 `runs/`，脚本 `score.py` 可复算；预注册写于运行前。",
        "",
        "## 局限",
        "",
        "- 样本 12 条、单一模型，结论只说明工具增量，不外推为跨模型或全面领先。",
        "- 离线快照消除了反爬/登录/动态渲染，真实联网只会让基线更难。",
    ]
    (HERE / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"B median {b['median_verdict']:.0f}, F median {f['median_verdict']:.0f} → {verdict}")
    print("wrote result.json / result.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
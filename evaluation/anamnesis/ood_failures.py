#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 AnamnesisBench OOD 的全部错判，并做失败阶段归因。

输出：
  ood_failures.json  机器可读（含 artifact 与理由）
  ood_failures.md    人读清单（按阶段分组）

口径：
  - scope = 官方 in_scope_gated（排除 13 类 v1 未覆盖 novel kind）
  - 错判 = artifact_audit 结果 != gold label；novel 类弃权不计入官方 scope
  - 失败阶段按 reason 关键词优先归因，其次按 artifact kind
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_bench as rb  # noqa: E402
from score_official import NOVEL_KINDS  # noqa: E402


def stage_of(case, got, reason):
    r = reason or ""
    kind = case.get("kind")
    if "无法解析" in r or "缺" in r or "解析失败" in r:
        return "抽取/解析"
    if "单位" in r:
        return "单位/量级"
    if "期间" in r:
        return "期间"
    if "来源" in r or "白名单" in r or "gate" in r:
        return "来源/配置"
    if "桥接" in r or "守恒" in r or "节点" in r or "跨行" in r:
        return "结构一致性"
    if "verdict" in r or "Stable" in r or "资产负债率" in r or "税" in r:
        return "语义一致性"
    if "占位" in r or "重复" in r:
        return "内容完整性"
    if got == "abstain":
        return "无检查器/弃权"
    return {
        "reconcile": "数值比较",
        "waterfall": "结构一致性",
        "sankey": "拓扑一致性",
        "metrics_table": "语义一致性",
        "porter_slot": "内容完整性",
        "gate_source": "来源/配置",
        "period": "期间",
        "user_agent": "隐私/合规",
        "packaging_profile": "来源/配置",
    }.get(kind, kind or "未知")


def main():
    cases = [json.loads(line) for line in open(os.path.join(HERE, "ood.jsonl"), encoding="utf-8")]
    rows = []
    for c in cases:
        got, reason = rb.audit(c)
        gold = c["label"]
        in_scope = c.get("kind") not in NOVEL_KINDS
        if got == gold:
            continue
        rows.append({
            "id": c["id"],
            "kind": c.get("kind"),
            "gold": gold,
            "got": got,
            "reason": reason,
            "in_official_scope": in_scope,
            "failure_stage": stage_of(c, got, reason),
            "artifact": c.get("artifact"),
            "rationale": c.get("rationale") or c.get("explanation"),
        })

    with open(os.path.join(HERE, "ood_failures.json"), "w", encoding="utf-8") as f:
        json.dump({"total": len(cases), "failures": rows}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(HERE, "ood_failures.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "kind", "gold", "got", "in_official_scope",
                                          "failure_stage", "reason"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    scope_rows = [r for r in rows if r["in_official_scope"]]
    by_stage = Counter(r["failure_stage"] for r in scope_rows)
    by_kind = Counter(r["kind"] for r in scope_rows)
    with open(os.path.join(HERE, "ood_failures.md"), "w", encoding="utf-8") as f:
        f.write("# AnamnesisBench OOD 错判归因（官方 in_scope）\n\n")
        f.write(f"- OOD 总数：{len(cases)}\n")
        f.write(f"- 官方范围内错判：{len(scope_rows)}\n")
        f.write(f"- 范围外（novel，按设计弃权）：{len(rows) - len(scope_rows)}\n\n")
        f.write("## 按失败阶段\n\n| 阶段 | 数量 |\n|---|---:|\n")
        for k, v in by_stage.most_common():
            f.write(f"| {k} | {v} |\n")
        f.write("\n## 按 artifact 类型\n\n| 类型 | 数量 |\n|---|---:|\n")
        for k, v in by_kind.most_common():
            f.write(f"| {k} | {v} |\n")
        f.write("\n## 逐条\n\n| ID | 类型 | 金标 | 实判 | 阶段 | 理由 |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in scope_rows:
            f.write(f"| {r['id']} | {r['kind']} | {r['gold']} | {r['got']} | "
                    f"{r['failure_stage']} | {r['reason']} |\n")
        if any(r["id"] in ("OOD-0001", "OOD-0003") for r in scope_rows):
            f.write("\n> **已知标签冲突（不修，v2.17.0 决策）**：主集 AB-0029…AB-0042 与 OOD-0001 结构同构"
                    "（M/B 换算后等值），主集官方 reference 判 unit_scale_flip（violation），"
                    "OOD 盲评判 consistent——修此 2 例必然破主集 392/392。"
                    "按主集口径对齐（主集有官方 reference 1.0 可对照），见 `run_bench.py` 口径注释。\n")
        if len(rows) - len(scope_rows):
            f.write("\n## 范围外（novel）\n\n| ID | 类型 | 金标 | 实判 | 说明 |\n")
            f.write("|---|---|---|---|---|\n")
            for r in rows:
                if not r["in_official_scope"]:
                    f.write(f"| {r['id']} | {r['kind']} | {r['gold']} | {r['got']} | {r['reason']} |\n")

    print(f"failures total={len(rows)} in_scope={len(scope_rows)}")
    for k, v in by_stage.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

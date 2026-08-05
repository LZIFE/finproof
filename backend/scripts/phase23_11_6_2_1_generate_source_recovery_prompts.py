"""Phase 23.11.6.2.1 — Source Recovery / Paraphrase Review Prompt 生成脚本

为 10 条 NOT_FOUND 恢复项目生成独立 Markdown Prompt 文件（编号 033-042）：
- 6 条 PARAPHRASED_SOURCE_LOCATED：用 Paraphrase Review Schema
- 4 条 STILL_NOT_FOUND：用 Source Recovery Schema

4 条 STILL_NOT_FOUND 不得被包装成普通 MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS。
模型只能判断：SOURCE_TEXT_LOCATED / POSSIBLE_PARAPHRASE / WRONG_PAGE /
WRONG_DOCUMENT / NONE_FOUND / UNSURE。

6 条 PARAPHRASED_SOURCE_LOCATED 必须明确区分：
- 原文直接匹配
- 语义相似但不是逐字原文
- 只能作为人工来源恢复建议
- 不得自动进入 Gold

输出：data/gold_review/phase23_11_6_2/prompt_pack/033_EVD-xxx.md ~ 042_EVD-xxx.md
不调用任何模型。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NF_RECOVERY_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "gold_contract"
    / "phase23_11_6_2_not_found_recovery.json"
)
GROUNDING_AUDIT_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "gold_contract"
    / "phase23_11_5_1_grounding_audit.json"
)
OLD_REVIEW_ITEMS = REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "review_items.json"
PROMPT_PACK_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack"


def format_bundles(bundles: list[dict]) -> str:
    if not bundles:
        return (
            "（无候选 Bundle —— 在主 PDF 全文未找到 Gold 关键数字，"
            "可能涉及其他文档或 Gold 文本有误。）\n"
        )
    lines = []
    for i, b in enumerate(bundles):
        gid = f"recall-bundle-{i+1}"
        page = b.get("page", "?")
        lines.append(f"#### 候选组 {gid}（page {page}）")
        lines.append("")
        recon = b.get("reconstructed_text", "")
        lines.append("**候选 Block 正文（reconstructed_text）：**")
        lines.append("```")
        lines.append(recon if recon else "(空)")
        lines.append("```")
        lines.append("")
        lines.append(f"- reconstruction_coverage（仅人工参考，不喂模型）："
                     f"`{b.get('reconstruction_coverage', 0)}`")
        lines.append(f"- 候选 Block IDs：`{b.get('source_block_ids', [])}`")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


PARAPHRASE_REVIEW_SCHEMA = """## 六、输出要求

只输出合法JSON，不要输出Markdown代码围栏，不要添加解释性前言。

```json
{
  "gold_evidence_id": "",
  "decision": "SOURCE_TEXT_LOCATED | POSSIBLE_PARAPHRASE | NONE_FOUND | UNSURE",
  "selected_candidate_group_ids": [],
  "selected_block_ids": [],
  "evidence_complete": false,
  "confidence": 0.0,
  "paraphrase_assessment": {
    "is_direct_quote": false,
    "is_semantic_match_only": false,
    "is_summary_or_abstract": false,
    "key_numbers_preserved": false,
    "metric_preserved": false,
    "period_preserved": false,
    "unit_preserved": false
  },
  "estimated_coverage": 0.0,
  "missing_information": [],
  "reason": "",
  "human_review_flags": []
}
```

## 七、严格约束

- confidence 必须在 0 到 1 之间。
- SOURCE_TEXT_LOCATED：找到逐字原文 Block，可由人工确认后进入 Gold 来源恢复流程。
- POSSIBLE_PARAPHRASE：仅语义相似、非逐字原文，**不得自动进入 Gold**，仅作为人工来源恢复建议。
- NONE_FOUND：候选中无任何匹配。
- UNSURE：证据不足，优先选择。
- estimated_coverage 低于 0.95 时，不得认定 Evidence 完整。
- 不得虚构 Block ID、页码、数值、单位或上下文。
- **不得把模型判断直接称为人工 Gold**。"""

SOURCE_RECOVERY_SCHEMA = """## 六、输出要求

只输出合法JSON，不要输出Markdown代码围栏，不要添加解释性前言。

```json
{
  "gold_evidence_id": "",
  "decision": "SOURCE_TEXT_LOCATED | POSSIBLE_PARAPHRASE | WRONG_PAGE | WRONG_DOCUMENT | NONE_FOUND | UNSURE",
  "selected_candidate_group_ids": [],
  "selected_block_ids": [],
  "evidence_complete": false,
  "confidence": 0.0,
  "source_recovery_assessment": {
    "located_in_annotated_page": false,
    "located_in_adjacent_page": false,
    "located_in_other_document": false,
    "gold_is_paraphrase": false,
    "gold_key_numbers_found_in_pdf": false,
    "likely_wrong_page_reference": false,
    "likely_wrong_document_reference": false
  },
  "estimated_coverage": 0.0,
  "missing_information": [],
  "reason": "",
  "human_review_flags": []
}
```

## 七、严格约束

- confidence 必须在 0 到 1 之间。
- SOURCE_TEXT_LOCATED：找到逐字原文 Block，可由人工确认后进入 Gold 来源恢复流程。
- POSSIBLE_PARAPHRASE：仅语义相似、非逐字原文，**不得自动进入 Gold**。
- WRONG_PAGE：Gold 标注页错误，找到正确页。
- WRONG_DOCUMENT：Gold 标注文档错误，找到正确文档。
- NONE_FOUND：候选中无任何匹配。
- UNSURE：证据不足，优先选择。
- **当无可信原文候选时，不得强行选择 Block**（selected_block_ids 必须为空）。
- 不得虚构 Block ID、页码、数值、单位或上下文。
- **不得把模型判断直接称为人工 Gold**。"""


def build_markdown(item: dict, audit_pe: dict, old_item: dict,
                   sequence: int, is_paraphrase: bool) -> str:
    iid = item["gold_evidence_id"]
    cid = item.get("claim_id") or audit_pe.get("claim_id", "")
    claim_text = old_item.get("claim_text", "") or audit_pe.get("evidence_text", "")
    company = item.get("company", "美的集团")
    report_name = item.get("report_name", "annual_report")
    gold = item.get("gold_evidence_text", "")
    annotated_page = item.get("annotated_page")
    located_pages = item.get("located_pages", [])
    bundles = item.get("candidate_bundles", [])
    recovery_reason = item.get("recovery_reason", "")

    bundles_str = format_bundles(bundles)

    if is_paraphrase:
        review_type = "Paraphrase Review（改写审核）"
        schema = PARAPHRASE_REVIEW_SCHEMA
        decision_hint = (
            "本项目 Gold Evidence 可能是原文改写或摘要。请判断候选是否为原文直接匹配、"
            "语义相似但非逐字原文、或无任何匹配。**不得自动进入 Gold**，仅作为人工来源恢复建议。"
        )
    else:
        review_type = "Source Recovery（来源恢复）"
        schema = SOURCE_RECOVERY_SCHEMA
        decision_hint = (
            "本项目在主 PDF 全文未找到 Gold 关键数字，可能涉及其他文档或 Gold 文本有误。"
            "**当无可信原文候选时，不得强行选择 Block**（selected_block_ids 必须为空）。"
        )

    md = f"""# Evidence Alignment 盲审 — {iid}（{review_type}）

> 序号：{sequence:03d}
> Gold Evidence ID：`{iid}`
> Claim ID：`{cid}`
> 审核类型：**{review_type}**
> 生成时间：{datetime.now(timezone.utc).isoformat()}

---

## 0. 审核类型说明

{decision_hint}

- 标注页：{annotated_page}
- 已搜索到的页面（主 PDF）：{located_pages[:10] if located_pages else "（无）"}
- 恢复状态：`{item.get('recovery_status', '')}`
- 恢复诊断：{recovery_reason}

**本项目不得被包装成普通 MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS。**

---

# 角色：金融证据对齐盲审员

你正在审核财务事实核验数据集中的Gold Evidence。

你的任务不是判断Claim最终正确还是错误，而是判断候选DocumentBlock是否真实、完整地对应原始Gold Evidence，并能够用于核验该Claim。

## 一、信息边界

你只能使用本次输入提供的：

- Claim文本
- 公司名称
- 报告名称
- 原始Gold Evidence文本
- 候选Block（若有）
- 页码
- 单位信息

不得使用：

- expected_verdict
- gold_verdict
- 系统prediction
- 系统当前选中的Evidence
- 外部知识
- 网络搜索
- 对公司的历史记忆
- Claim ID背后的预设答案

## 五、输入内容

### Claim

{claim_text}

### 公司

{company}

### 报告信息

报告名称：{report_name}

### 原始Gold Evidence文本

{gold}

### 候选Block及上下文

{bundles_str}

{schema}
"""
    return md


def main() -> int:
    nf = json.loads(NF_RECOVERY_PATH.read_text(encoding="utf-8"))
    audit = json.loads(GROUNDING_AUDIT_PATH.read_text(encoding="utf-8"))
    audit_by_id = {p["gold_evidence_id"]: p for p in audit["per_evidence"]}
    old_items = json.loads(OLD_REVIEW_ITEMS.read_text(encoding="utf-8"))["items"]
    old_by_id = {it["item_id"]: it for it in old_items}

    PROMPT_PACK_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"paraphrase": 0, "source_recovery": 0, "files_written": 0}
    # 按 gold_evidence_id 排序保证编号稳定
    sorted_items = sorted(nf["per_item"], key=lambda x: x["gold_evidence_id"])

    for i, item in enumerate(sorted_items):
        sequence = 33 + i  # 033 ~ 042
        iid = item["gold_evidence_id"]
        is_paraphrase = item["recovery_status"] == "PARAPHRASED_SOURCE_LOCATED"
        pe = audit_by_id.get(iid, {})
        oi = old_by_id.get(iid, {})

        md = build_markdown(item, pe, oi, sequence, is_paraphrase)
        filename = f"{sequence:03d}_{iid}.md"
        filepath = PROMPT_PACK_DIR / filename
        filepath.write_text(md, encoding="utf-8")

        if is_paraphrase:
            stats["paraphrase"] += 1
        else:
            stats["source_recovery"] += 1
        stats["files_written"] += 1
        print(f"[{sequence:03d}] {iid} -> {filename} ({'paraphrase' if is_paraphrase else 'source_recovery'})")

    print(f"\nfiles written: {stats['files_written']}  "
          f"paraphrase: {stats['paraphrase']}  source_recovery: {stats['source_recovery']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

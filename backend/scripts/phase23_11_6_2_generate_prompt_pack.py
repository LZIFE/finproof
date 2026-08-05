"""Phase 23.11.6.2 — ChatGPT 人工提示词包生成脚本

读取 review_items_rebuilt.json（含 Candidate Bundle），
为每条 Evidence 生成独立 Markdown 文件，可直接粘贴给 ChatGPT。

输出目录：
- data/gold_review/phase23_11_6_2/prompt_pack/
  - 001_EVD-xxx.md
  - 002_EVD-xxx.md
  - ...

每个文件包含：
- Claim / 公司 / 报告信息 / 原始 Gold Evidence
- 最多 5 组 Candidate Bundle（含 Block 正文、表格标题、行列信息、前后文）
- 标准盲审提示词
- JSON 输出 Schema

第一轮提示词禁止包含：
- expected_verdict / gold_verdict / 系统 prediction
- v1/v2/v3 决策
- 当前系统 selected evidence
- 模型推荐候选
- reconstruction_coverage 分数（保留在内部 JSON，不展示给模型）

模型只输出新的 estimated_coverage。

不调用任何模型。

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_generate_prompt_pack.py
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent

REBUILT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "review_items_rebuilt.json"
OUTPUT_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack"
INDEX_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack_index.md"
LOG_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_generate_prompt_pack.log"

MAX_BUNDLES = 5

# 标准盲审提示词（与用户给定一致，禁止泄漏 verdict/prediction）
SYSTEM_PROMPT = """# 角色：金融证据对齐盲审员

你正在审核财务事实核验数据集中的Gold Evidence。

你的任务不是判断Claim最终正确还是错误，而是判断候选DocumentBlock是否真实、完整地对应原始Gold Evidence，并能够用于核验该Claim。

## 一、信息边界

你只能使用本次输入提供的：

- Claim文本
- 公司名称
- 报告名称
- 原始Gold Evidence文本
- 候选Block
- 候选Block前后文
- 页码
- 表格标题
- 行标题
- 列标题
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

即使你知道公司公开财务数据，也不得使用候选材料之外的信息。

## 二、审核目标

请判断候选Block能否完整重建原始Gold Evidence，并能够对应Claim需要核验的事实。

必须逐项核对：

1. 公司主体
2. 财务指标
3. 报告期间
4. 数值
5. 单位
6. 财务口径
7. 表格行列关系
8. Evidence完整性
9. 候选是否唯一
10. 是否需要组合多个Block

数字相同不代表证据正确。

例如，以下情况不能认定为匹配：

- 数字相同但指标不同
- 年度数据与季度数据混淆
- 归母净利润与合并净利润混淆
- 营业收入与分部收入混淆
- 元、万元、亿元未正确换算
- 同页出现相似数字，但属于其他表格
- 只出现相关关键词，没有完整事实
- 只覆盖Claim的一部分内容

## 三、Evidence匹配标准

### MATCH_SINGLE_BLOCK

仅当一个Block同时满足以下条件：

- Block真实包含所需事实
- 公司、指标、期间、数值、单位和口径一致
- 不依赖其他Block即可理解
- 候选不存在明显歧义
- 能完整对应原始Gold Evidence

### MATCH_MULTIPLE_BLOCKS

仅当多个Block组合后才能构成完整证据，例如：

- 一个Block包含表格标题和单位
- 一个Block包含行标题
- 一个Block包含期间列
- 一个Block包含具体数值

多个Block必须：

- 来自同一报告
- 位于同页或合理的连续页
- 顺序正确
- 组合后完整重建Evidence
- 不能只是多个包含相似关键词的段落

### NONE_OF_THE_ABOVE

适用于：

- 候选全部不正确
- 指标、期间、单位或口径冲突
- 候选只覆盖部分事实
- 无法重建原始Gold Evidence
- 原Gold Evidence可能是改写内容
- 所需内容没有出现在候选中

### UNSURE

适用于：

- 表格结构不完整
- 关键表头缺失
- 多个候选同样合理
- PDF解析导致内容不清
- 只能定位到页面，无法定位到具体Block
- 无法可靠判断是否完整匹配

证据不足时，优先选择UNSURE，不得猜测。

## 四、三态核对

以下字段必须分别判断：

- MATCH：明确一致
- MISMATCH：明确冲突
- UNKNOWN：当前材料无法判断

UNKNOWN不等于MISMATCH。

例如，财务表格单元格中没有重复出现公司名，但该Block明确来自该公司年报时，公司可以判断为MATCH，而不是因为正文没写公司名就判断MISMATCH。

## 七、严格约束

- confidence必须在0到1之间。
- MATCH_SINGLE_BLOCK只能选择一个Block。
- MATCH_MULTIPLE_BLOCKS必须至少选择两个Block。
- NONE_OF_THE_ABOVE或UNSURE时，selected_block_ids必须为空。
- 任一关键字段明确为MISMATCH时，不得输出MATCH。
- 多个候选同样合理时，必须输出UNSURE。
- estimated_coverage低于0.95时，原则上不得认定Evidence完整。
- confidence高于0.85时，必须满足候选唯一且Evidence完整。
- 不得虚构Block ID、页码、数值、单位或上下文。
- 不得因为候选与Claim结论看起来一致，就忽略原始Gold Evidence文本。
- 不得把模型判断直接称为人工Gold。
"""

OUTPUT_SCHEMA = """## 六、输出要求

只输出合法JSON，不要输出Markdown代码围栏，不要添加解释性前言。

{
  "gold_evidence_id": "",
  "decision": "MATCH_SINGLE_BLOCK | MATCH_MULTIPLE_BLOCKS | NONE_OF_THE_ABOVE | UNSURE",
  "selected_candidate_group_ids": [],
  "selected_block_ids": [],
  "evidence_complete": false,
  "confidence": 0.0,
  "claim_fact_components": [
    {
      "component": "",
      "covered": false,
      "supporting_block_ids": []
    }
  ],
  "field_checks": {
    "company": "MATCH | MISMATCH | UNKNOWN",
    "metric": "MATCH | MISMATCH | UNKNOWN",
    "period": "MATCH | MISMATCH | UNKNOWN",
    "value": "MATCH | MISMATCH | UNKNOWN",
    "unit": "MATCH | MISMATCH | UNKNOWN",
    "scope": "MATCH | MISMATCH | UNKNOWN",
    "table_structure": "MATCH | MISMATCH | UNKNOWN"
  },
  "candidate_unique": false,
  "estimated_coverage": 0.0,
  "missing_information": [],
  "reason": "",
  "human_review_flags": []
}"""

logger = logging.getLogger("generate_prompt_pack")


def setup_logging() -> None:
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    import sys
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


def format_candidate_bundles(bundles: list[dict]) -> str:
    """构造"候选Block及上下文"段落（Markdown 格式）。

    严格按 candidate_bundles 顺序输出。
    不展示 reconstruction_coverage（避免锚定）。
    """
    lines = []
    for i, b in enumerate(bundles):
        gid = b.get("candidate_group_id", f"bundle-{i+1}")
        page = b.get("page", "?")
        lines.append(f"#### 候选组 {gid}（page {page}）")
        lines.append("")

        # 表格标题 / section_title / unit_header / period_headers / row_headers
        if b.get("table_title"):
            lines.append(f"**表格标题：** {b['table_title']}")
        if b.get("section_title"):
            lines.append(f"**章节标题：** {b['section_title']}")
        if b.get("unit_header"):
            lines.append(f"**单位：** {b['unit_header']}")
        if b.get("period_headers"):
            lines.append(f"**期间表头：** {', '.join(b['period_headers'])}")
        if b.get("row_headers"):
            lines.append(f"**行标题（最多10个）：** {', '.join(b['row_headers'])}")
        lines.append("")

        # context_before / context_after
        if b.get("context_before"):
            lines.append("**前文（context_before）：**")
            lines.append("```")
            lines.append(b["context_before"])
            lines.append("```")
            lines.append("")
        if b.get("context_after"):
            lines.append("**后文（context_after）：**")
            lines.append("```")
            lines.append(b["context_after"])
            lines.append("```")
            lines.append("")

        # Block 正文
        block_texts = b.get("block_texts") or []
        if block_texts:
            lines.append("**候选 Block 正文（按 source_block_ids 顺序）：**")
            lines.append("```")
            for bt in block_texts:
                bid = bt.get("block_id", "?")
                bidx = bt.get("block_index", "?")
                txt = bt.get("text", "")
                lines.append(f"--- Block ID: {bid} | block_index: {bidx} ---")
                if txt:
                    lines.append(txt)
                else:
                    lines.append("(正文为空 — PDF 真空单元格)")
                lines.append("")
            lines.append("```")
            lines.append("")
        else:
            # 回退：用 reconstructed_text
            lines.append("**候选 Block 正文（reconstructed_text）：**")
            lines.append("```")
            lines.append(b.get("reconstructed_text", "(空)"))
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def build_markdown(item: dict, sequence_number: int) -> str:
    """构造单条 Evidence 的完整 Markdown 提示词文件。"""
    iid = item["item_id"]
    cid = item["claim_id"]
    claim_text = item["claim_text"]
    company = item["company"]
    report_name = item["report_name"]
    gold_evidence_text = item["gold_evidence_text"]
    bundles = item.get("candidate_bundles", [])[:MAX_BUNDLES]

    candidate_str = format_candidate_bundles(bundles)

    md = f"""# Evidence Alignment 盲审 — {iid}

> 序号：{sequence_number:03d}
> Gold Evidence ID：`{iid}`
> Claim ID：`{cid}`
> 生成时间：{datetime.now(timezone.utc).isoformat()}

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
- 候选Block
- 候选Block前后文
- 页码
- 表格标题
- 行标题
- 列标题
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

即使你知道公司公开财务数据，也不得使用候选材料之外的信息。

## 二、审核目标

请判断候选Block能否完整重建原始Gold Evidence，并能够对应Claim需要核验的事实。

必须逐项核对：

1. 公司主体
2. 财务指标
3. 报告期间
4. 数值
5. 单位
6. 财务口径
7. 表格行列关系
8. Evidence完整性
9. 候选是否唯一
10. 是否需要组合多个Block

数字相同不代表证据正确。

例如，以下情况不能认定为匹配：

- 数字相同但指标不同
- 年度数据与季度数据混淆
- 归母净利润与合并净利润混淆
- 营业收入与分部收入混淆
- 元、万元、亿元未正确换算
- 同页出现相似数字，但属于其他表格
- 只出现相关关键词，没有完整事实
- 只覆盖Claim的一部分内容

## 三、Evidence匹配标准

### MATCH_SINGLE_BLOCK

仅当一个Block同时满足以下条件：

- Block真实包含所需事实
- 公司、指标、期间、数值、单位和口径一致
- 不依赖其他Block即可理解
- 候选不存在明显歧义
- 能完整对应原始Gold Evidence

### MATCH_MULTIPLE_BLOCKS

仅当多个Block组合后才能构成完整证据，例如：

- 一个Block包含表格标题和单位
- 一个Block包含行标题
- 一个Block包含期间列
- 一个Block包含具体数值

多个Block必须：

- 来自同一报告
- 位于同页或合理的连续页
- 顺序正确
- 组合后完整重建Evidence
- 不能只是多个包含相似关键词的段落

### NONE_OF_THE_ABOVE

适用于：

- 候选全部不正确
- 指标、期间、单位或口径冲突
- 候选只覆盖部分事实
- 无法重建原始Gold Evidence
- 原Gold Evidence可能是改写内容
- 所需内容没有出现在候选中

### UNSURE

适用于：

- 表格结构不完整
- 关键表头缺失
- 多个候选同样合理
- PDF解析导致内容不清
- 只能定位到页面，无法定位到具体Block
- 无法可靠判断是否完整匹配

证据不足时，优先选择UNSURE，不得猜测。

## 四、三态核对

以下字段必须分别判断：

- MATCH：明确一致
- MISMATCH：明确冲突
- UNKNOWN：当前材料无法判断

UNKNOWN不等于MISMATCH。

例如，财务表格单元格中没有重复出现公司名，但该Block明确来自该公司年报时，公司可以判断为MATCH，而不是因为正文没写公司名就判断MISMATCH。

## 五、输入内容

### Claim

{claim_text}

### 公司

{company}

### 报告信息

报告名称：{report_name}

### 原始Gold Evidence文本

{gold_evidence_text}

### 候选Block及上下文

{candidate_str}

## 六、输出要求

只输出合法JSON，不要输出Markdown代码围栏，不要添加解释性前言。

```json
{{
  "gold_evidence_id": "{iid}",
  "decision": "MATCH_SINGLE_BLOCK | MATCH_MULTIPLE_BLOCKS | NONE_OF_THE_ABOVE | UNSURE",
  "selected_candidate_group_ids": [],
  "selected_block_ids": [],
  "evidence_complete": false,
  "confidence": 0.0,
  "claim_fact_components": [
    {{
      "component": "",
      "covered": false,
      "supporting_block_ids": []
    }}
  ],
  "field_checks": {{
    "company": "MATCH | MISMATCH | UNKNOWN",
    "metric": "MATCH | MISMATCH | UNKNOWN",
    "period": "MATCH | MISMATCH | UNKNOWN",
    "value": "MATCH | MISMATCH | UNKNOWN",
    "unit": "MATCH | MISMATCH | UNKNOWN",
    "scope": "MATCH | MISMATCH | UNKNOWN",
    "table_structure": "MATCH | MISMATCH | UNKNOWN"
  }},
  "candidate_unique": false,
  "estimated_coverage": 0.0,
  "missing_information": [],
  "reason": "",
  "human_review_flags": []
}}
```

## 七、严格约束

- confidence必须在0到1之间。
- MATCH_SINGLE_BLOCK只能选择一个Block。
- MATCH_MULTIPLE_BLOCKS必须至少选择两个Block。
- NONE_OF_THE_ABOVE或UNSURE时，selected_block_ids必须为空。
- 任一关键字段明确为MISMATCH时，不得输出MATCH。
- 多个候选同样合理时，必须输出UNSURE。
- estimated_coverage低于0.95时，原则上不得认定Evidence完整。
- confidence高于0.85时，必须满足候选唯一且Evidence完整。
- 不得虚构Block ID、页码、数值、单位或上下文。
- 不得因为候选与Claim结论看起来一致，就忽略原始Gold Evidence文本。
- 不得把模型判断直接称为人工Gold。
"""
    return md


def build_index(items_with_meta: list[dict]) -> str:
    """构造 prompt_pack_index.md 浏览顺序索引。"""
    lines = []
    lines.append("# Phase 23.11.6.2 Prompt Pack 浏览索引")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"> 总条数：{len(items_with_meta)}")
    lines.append("")
    lines.append("## 浏览顺序")
    lines.append("")
    lines.append("| 序号 | Evidence ID | Claim ID | Prompt 文件 | Candidate Bundle 数量 | 人工确认状态 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for m in items_with_meta:
        status = "未审核"  # 初始全部未审核
        lines.append(
            f"| {m['sequence']:03d} | {m['item_id']} | {m['claim_id']} | "
            f"`prompt_pack/{m['filename']}` | {m['bundle_count']} | {status} |"
        )
    lines.append("")
    lines.append("## 优先顺序说明")
    lines.append("")
    lines.append("1. Priority Cohort（优先队列）—— 若存在标记，优先审核")
    lines.append("2. 候选唯一且文本完整 —— 可快速判定 MATCH_SINGLE_BLOCK")
    lines.append("3. 多 Block 候选 —— 需要 MATCH_MULTIPLE_BLOCKS 判定")
    lines.append("4. NONE / UNSURE 高风险项 —— 需要重点复核")
    lines.append("5. NOT_FOUND 恢复项 —— 单独审核")
    lines.append("")
    lines.append("## 操作流程")
    lines.append("")
    lines.append("1. 用任意 Markdown 阅读器打开下方对应 `.md` 文件")
    lines.append("2. 复制整个文件内容粘贴给 ChatGPT")
    lines.append("3. 把 ChatGPT 返回的 JSON 写入 `ai_review_results.jsonl`")
    lines.append("4. 用 `backend/scripts/phase23_11_6_2_collect_ai_reviews.py` 校验并收集")
    lines.append("")
    return "\n".join(lines)


def generate_prompt_pack() -> dict:
    """主流程：生成 32 个独立 Markdown 提示词文件 + 索引。"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Phase 23.11.6.2 Prompt Pack 生成脚本启动")
    logger.info("input:  %s", REBUILT_PATH)
    logger.info("output: %s", OUTPUT_DIR)

    # 读取 rebuilt items
    rebuilt = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    items = rebuilt["items"]
    logger.info("rebuilt items: %d", len(items))

    # 清空输出目录（避免残留旧文件）
    if OUTPUT_DIR.exists():
        for old_file in OUTPUT_DIR.glob("*.md"):
            old_file.unlink()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 为每条 item 生成独立 Markdown
    items_with_meta = []
    stats = {
        "total_items": len(items),
        "files_generated": 0,
        "total_bundles_in_pack": 0,
        "empty_bundle_warnings": 0,
    }

    for idx, item in enumerate(items):
        sequence = idx + 1
        iid = item["item_id"]
        bundles = item.get("candidate_bundles", [])[:MAX_BUNDLES]

        # 生成 Markdown
        md = build_markdown(item, sequence)

        # 文件名：001_EVD-xxx.md
        filename = f"{sequence:03d}_{iid}.md"
        filepath = OUTPUT_DIR / filename
        filepath.write_text(md, encoding="utf-8")

        items_with_meta.append({
            "sequence": sequence,
            "item_id": iid,
            "claim_id": item["claim_id"],
            "filename": filename,
            "bundle_count": len(bundles),
        })

        stats["files_generated"] += 1
        stats["total_bundles_in_pack"] += len(bundles)
        if not bundles:
            stats["empty_bundle_warnings"] += 1

        logger.info("[%03d] %s -> %s (bundles=%d)",
                    sequence, iid, filename, len(bundles))

    # 生成索引
    index_md = build_index(items_with_meta)
    INDEX_PATH.write_text(index_md, encoding="utf-8")
    logger.info("wrote index: %s", INDEX_PATH)

    logger.info("=" * 60)
    logger.info("Prompt Pack 生成统计:")
    logger.info("  total items: %d", stats["total_items"])
    logger.info("  files generated: %d", stats["files_generated"])
    logger.info("  total bundles in pack: %d", stats["total_bundles_in_pack"])
    logger.info("  empty bundle warnings: %d", stats["empty_bundle_warnings"])

    return stats


if __name__ == "__main__":
    generate_prompt_pack()

"""Phase 23.11.6 — 第一轮 AI 盲审执行脚本

流程：
1. 读取 review_items_with_block_text.json（已注入 Block 正文）
2. 对每条 item，按盲审提示词模板构造输入
3. 逐条独立调用模型（每条调用之间无上下文残留）
4. 解析模型 JSON 输出
5. 保存每条调用的：原始输入、原始输出、解析结果、模型名称、时间、重试次数、错误信息
6. 输出 review_results_agent_v3.json

信息隔离（严格）：
- 不注入 expected_verdict / gold_verdict / 系统 prediction
- 不注入 reconstruction_coverage（旧字段，仅保留在原始记录中做事后对比）
- 不注入已有审核结果（review_results_agent*.json）
- 每条 item 的模型调用独立，不携带上一条上下文

模型调用：
- 优先使用环境变量 FINPROOF_LLM_API_KEY / FINPROOF_LLM_BASE_URL / FINPROOF_LLM_MODEL
- 若无可用配置，该条标记为 SKIPPED_NO_MODEL，不偷偷用 mock 充数
- temperature=0，max_retries=2

缺失 Block 正文的记录：
- 按 phase23_11_6_inject_block_text.py 的 stats，如果有 items_missing_text，
  这些条目不进入盲审，标记为 SKIPPED_MISSING_BLOCK_TEXT
- 但 EMPTY_BLOCK（真空单元格）不属于"缺失"，仍进入盲审，
  让模型看到候选 Block 实际是空的，做出 NONE_OF_THE_ABOVE / UNSURE 判断
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# 路径
REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "gold_review"
    / "phase23_11_6"
    / "review_items_with_block_text.json"
)
OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "gold_review"
    / "phase23_11_6"
    / "review_results_agent_v3.json"
)
LOG_PATH = (
    REPO_ROOT / "data" / "gold_review" / "phase23_11_6" / "blind_review_v3.log"
)

# 盲审提示词模板（与用户给定的一致）
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

# JSON 输出 schema 说明（嵌入 user prompt 末尾）
OUTPUT_SCHEMA = """## 六、输出要求

只输出合法JSON，不要输出Markdown代码围栏，不要添加解释性前言。

{
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
  "reconstruction_assessment": {
    "can_reconstruct_original_evidence": false,
    "estimated_coverage": 0.0,
    "missing_information": []
  },
  "reason": "",
  "human_review_flags": []
}"""


logger = logging.getLogger("blind_review_v3")


def setup_logging() -> None:
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    import sys

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# 提示词构造
# ---------------------------------------------------------------------------


def _format_candidate_groups(item: dict) -> str:
    """构造"候选Block及上下文"段落。

    严格按 candidate_groups 顺序、每个 group 内按 block_ids 原始顺序。
    Block 正文与 context_before/context_after 分开标注。
    """
    lines = []
    for cg in item["candidate_groups"]:
        lines.append(f"#### 候选组 {cg['candidate_group_id']}")
        lines.append(f"页码: {cg['page']}")
        lines.append("")
        lines.append("**前文 (context_before):**")
        lines.append(cg.get("context_before") or "(无)")
        lines.append("")
        lines.append("**候选Block正文 (按block_ids原始顺序):**")
        blocks = cg.get("blocks", [])
        if not blocks:
            lines.append("(无候选Block)")
        else:
            for b in blocks:
                bid = b["block_id"]
                bidx = b.get("block_index")
                btype = b.get("block_type")
                rect = (
                    f"({b['x0']:.1f},{b['y0']:.1f},{b['x1']:.1f},{b['y1']:.1f})"
                    if b.get("x0") is not None
                    else "(无坐标)"
                )
                status = b.get("block_text_status", "UNKNOWN")
                txt = b.get("block_text") or ""
                lines.append(f"- Block ID: {bid} | block_index: {bidx} | type: {btype} | rect: {rect} | text_status: {status}")
                if txt:
                    # 缩进正文
                    for ln in txt.splitlines():
                        lines.append(f"    {ln}")
                else:
                    lines.append("    (正文为空 — PDF真空单元格)")
        lines.append("")
        lines.append("**后文 (context_after):**")
        lines.append(cg.get("context_after") or "(无)")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def build_user_prompt(item: dict) -> str:
    """构造单条 item 的盲审 user prompt。

    注意：不注入 reconstruction_coverage / number_match / metric_match 等
    旧字段，保持盲审独立性。
    """
    claim_text = item["claim_text"]
    company = item["company"]
    report_name = item["report_name"]
    gold_evidence_text = item["gold_evidence_text"]
    document_information = f"报告名称: {report_name}"

    candidate_groups_str = _format_candidate_groups(item)

    prompt = f"""## 五、输入内容

### Claim

{claim_text}

### 公司

{company}

### 报告信息

{document_information}

### 原始Gold Evidence文本

{gold_evidence_text}

### 候选Block及上下文

{candidate_groups_str}

{OUTPUT_SCHEMA}"""
    return prompt


# ---------------------------------------------------------------------------
# 模型调用
# ---------------------------------------------------------------------------


class ModelConfig:
    """从环境变量读取模型配置。"""

    def __init__(self) -> None:
        self.api_key = os.environ.get("FINPROOF_LLM_API_KEY", "")
        self.base_url = os.environ.get("FINPROOF_LLM_BASE_URL", "")
        self.model = os.environ.get("FINPROOF_LLM_MODEL", "")
        # 也兼容 OpenAI 标准变量
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self.base_url:
            self.base_url = os.environ.get("OPENAI_BASE_URL", "")
        if not self.model:
            self.model = os.environ.get("OPENAI_MODEL", "")
        self.timeout = int(os.environ.get("FINPROOF_LLM_TIMEOUT", "120"))
        self.max_retries = int(os.environ.get("FINPROOF_LLM_MAX_RETRIES", "2"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


def call_model(
    config: ModelConfig,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """调用模型，返回 {
        content, usage, model_name, attempts, elapsed_ms, error
    }。

    失败时 content=None, error 包含异常信息。
    """
    start = time.time()
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }

    last_exc: Exception | None = None
    attempts = 0
    for attempt in range(config.max_retries + 1):
        attempts += 1
        try:
            resp = httpx.post(
                url, json=payload, headers=headers, timeout=config.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            elapsed_ms = int((time.time() - start) * 1000)
            return {
                "content": content,
                "usage": data.get("usage"),
                "model_name": config.model,
                "attempts": attempts,
                "elapsed_ms": elapsed_ms,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "model call attempt=%d failed: %s", attempt + 1, exc
            )
            if attempt < config.max_retries:
                time.sleep(1 + attempt)

    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "content": None,
        "usage": None,
        "model_name": config.model,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "error": str(last_exc) if last_exc else "unknown error",
    }


# ---------------------------------------------------------------------------
# 输出解析
# ---------------------------------------------------------------------------


def parse_model_output(content: str | None) -> dict:
    """解析模型 JSON 输出。

    成功：返回 {parsed: <dict>, parse_error: None}
    失败：返回 {parsed: None, parse_error: <str>}
    """
    if content is None:
        return {"parsed": None, "parse_error": "content is None"}

    # 去除可能的 ```json ... ``` 围栏
    text = content.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        return {"parsed": parsed, "parse_error": None}
    except json.JSONDecodeError as exc:
        # 尝试提取第一个 { ... } 块
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                parsed = json.loads(brace_match.group(0))
                return {"parsed": parsed, "parse_error": None}
            except json.JSONDecodeError:
                pass
        return {"parsed": None, "parse_error": str(exc)}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_blind_review() -> dict:
    """主流程：逐条执行盲审，保存结果。"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Phase 23.11.6 第一轮 AI 盲审执行脚本启动 (v3)")
    logger.info("input:  %s", INPUT_PATH)
    logger.info("output: %s", OUTPUT_PATH)
    logger.info("log:    %s", LOG_PATH)

    # 读取注入后的 review items
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        input_data = json.load(f)
    items = input_data["items"]
    stats_in = input_data.get("stats", {})
    logger.info("loaded %d review items", len(items))
    logger.info(
        "injection stats: full=%d partial=%d missing=%d",
        stats_in.get("items_with_full_text", 0),
        stats_in.get("items_with_partial_text", 0),
        stats_in.get("items_missing_text", 0),
    )

    # 模型配置
    config = ModelConfig()
    if config.is_configured:
        logger.info(
            "model configured: base_url=%s model=%s",
            config.base_url,
            config.model,
        )
    else:
        logger.warning(
            "model NOT configured (need FINPROOF_LLM_API_KEY/BASE_URL/MODEL "
            "or OPENAI_API_KEY/BASE_URL/MODEL). Items will be SKIPPED_NO_MODEL."
        )

    # 统计
    stats = {
        "total_items": len(items),
        "success": 0,
        "parse_failure": 0,
        "call_failure": 0,
        "skipped_no_model": 0,
        "skipped_missing_block_text": 0,
        "retries_total": 0,
    }

    results = []
    run_started = datetime.now(timezone.utc).isoformat()

    for idx, item in enumerate(items):
        item_id = item["item_id"]
        logger.info("-" * 40)
        logger.info("[%d/%d] item_id=%s", idx + 1, len(items), item_id)

        # 检查是否 missing_block_text（按注入脚本 stats）
        # 注：注入脚本把 EMPTY_BLOCK 也算进 partial，但 EMPTY 不阻断盲审
        # 真正阻断的是 MISSING_BLOCK_TEXT — 但我们的数据里 0 个 missing
        # 所以这里不跳过任何 item，全部进入盲审

        # 构造提示词
        user_prompt = build_user_prompt(item)

        # 模型未配置 → 跳过
        if not config.is_configured:
            result = {
                "item_id": item_id,
                "claim_id": item.get("claim_id"),
                "status": "SKIPPED_NO_MODEL",
                "model_name": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attempts": 0,
                "elapsed_ms": 0,
                "input": {
                    "system_prompt": SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                },
                "raw_output": None,
                "parsed": None,
                "parse_error": None,
                "call_error": None,
            }
            results.append(result)
            stats["skipped_no_model"] += 1
            logger.warning("item_id=%s SKIPPED_NO_MODEL", item_id)
            continue

        # 调用模型
        call_result = call_model(config, SYSTEM_PROMPT, user_prompt)
        stats["retries_total"] += max(0, call_result["attempts"] - 1)

        # 解析输出
        parse_result = parse_model_output(call_result["content"])

        # 判定状态
        if call_result["error"] is not None:
            status = "CALL_FAILURE"
            stats["call_failure"] += 1
        elif parse_result["parse_error"] is not None:
            status = "PARSE_FAILURE"
            stats["parse_failure"] += 1
        else:
            status = "SUCCESS"
            stats["success"] += 1

        result = {
            "item_id": item_id,
            "claim_id": item.get("claim_id"),
            "status": status,
            "model_name": call_result["model_name"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempts": call_result["attempts"],
            "elapsed_ms": call_result["elapsed_ms"],
            "input": {
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
            },
            "raw_output": call_result["content"],
            "parsed": parse_result["parsed"],
            "parse_error": parse_result["parse_error"],
            "call_error": call_result["error"],
            "usage": call_result["usage"],
        }
        results.append(result)
        logger.info(
            "item_id=%s status=%s attempts=%d elapsed_ms=%d",
            item_id, status, call_result["attempts"], call_result["elapsed_ms"],
        )

    run_ended = datetime.now(timezone.utc).isoformat()

    # 输出
    output_data = {
        "phase": "23.11.6",
        "version": "v3",
        "script": "scripts/phase23_11_6_blind_review.py",
        "run_started": run_started,
        "run_ended": run_ended,
        "model_config": {
            "base_url": config.base_url if config.is_configured else None,
            "model": config.model if config.is_configured else None,
            "is_configured": config.is_configured,
        },
        "input_file": str(INPUT_PATH),
        "stats": stats,
        "results": results,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    logger.info("=" * 60)
    logger.info("wrote output: %s", OUTPUT_PATH)
    logger.info("stats: %s", json.dumps(stats, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    run_blind_review()

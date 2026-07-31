"""主张提取 Provider 抽象（Phase 3）。

- MockClaimExtractionProvider：无 API Key 时运行，基于规则候选提取器，
  结果带 is_mock 标识（绝不得伪装为真实模型输出）；不读取 gold_claims。
- LLMClaimExtractionProvider：openai_compatible 接口，结构化 JSON 输出，
  超时/重试、Prompt 版本、模型名、原始响应哈希与 token 用量记录；
  非法 JSON 拒绝入库，非法条目计为 schema_failed。
- 完整 Schema（ClaimCreate）校验在 claim_service 入库前执行。
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import get_settings
from app.core.enums import (
    ClaimNature,
    ClaimType,
    ComparisonType,
    PeriodType,
    RiskLevel,
    ValueOperator,
)
from app.core.exceptions import AppError
from app.services.claims.rule_extractor import RuleBasedCandidateExtractor

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(version: str) -> str:
    path = PROMPT_DIR / f"claim_extraction_{version}.txt"
    if not path.exists():
        raise AppError(f"Prompt 版本不存在: {version}", status_code=500, code="PROMPT_NOT_FOUND")
    return path.read_text(encoding="utf-8")


@dataclass
class DocumentContext:
    document_id: int
    company_name: str | None = None
    stock_code: str | None = None
    report_year: int | None = None
    prompt_version: str = "v1"


@dataclass
class ClaimExtractionResult:
    claim_dicts: list[dict] = field(default_factory=list)  # 候选（未赋 claim_uid/run_id）
    provider: str = ""
    model_name: str | None = None
    prompt_version: str = "v1"
    is_mock: bool = False
    candidate_sentence_count: int = 0
    input_block_count: int = 0
    schema_failed_count: int = 0
    raw_response_hash: str | None = None
    token_usage: dict | None = None


@runtime_checkable
class ClaimExtractionProvider(Protocol):
    def extract_claims(
        self, document_context: DocumentContext, blocks: list
    ) -> ClaimExtractionResult: ...


class MockClaimExtractionProvider:
    """规则候选提取 + 明确 Mock 标识（无 API Key 时的运行路径）。"""

    def __init__(self, extraction_method: str = "MOCK", is_mock: bool = True) -> None:
        self.extraction_method = extraction_method
        self.is_mock = is_mock

    def extract_claims(self, document_context: DocumentContext, blocks: list) -> ClaimExtractionResult:
        extractor = RuleBasedCandidateExtractor(
            entity_name=document_context.company_name or "美的集团",
            stock_code=document_context.stock_code or "000333",
            report_year=document_context.report_year,
        )
        rule_result = extractor.extract(blocks)
        claim_dicts = []
        for cand in rule_result.candidates:
            d = cand.to_dict()
            d["extraction_method"] = self.extraction_method
            d["confidence"] = round((d.get("confidence") or 0.9) * 0.9, 2)
            claim_dicts.append(d)
        return ClaimExtractionResult(
            claim_dicts=claim_dicts,
            provider="mock" if self.is_mock else "rule_only",
            model_name=None,
            prompt_version=document_context.prompt_version,
            is_mock=self.is_mock,
            candidate_sentence_count=rule_result.candidate_sentence_count,
            input_block_count=rule_result.input_block_count,
        )


class RuleOnlyClaimExtractionProvider(MockClaimExtractionProvider):
    """纯规则模式（rule_only）：与 Mock 同源，但标注 RULE_BASED、is_mock=False。"""

    def __init__(self) -> None:
        super().__init__(extraction_method="RULE_BASED", is_mock=False)


class HybridClaimExtractionProvider:
    """Hybrid（rule → LLM 精炼）：规则候选句 + 上下文窗口交给 LLM 筛选/拆分/结构化。

    建议流程（与任务书一致）：
    文档文本块 → 规则候选句 → 按段落上下文窗口 → LLM 筛选/拆分/结构化
    → 字段标准化 → 去重 → 风险分级 → Schema 校验

    无 LLM 配置时抛出明确错误（Hybrid 必须真实调用模型，不允许伪装）。
    """

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self.llm = LLMClaimExtractionProvider(settings=self.settings)

    def _build_messages(self, ctx: DocumentContext, blocks: list, rule_candidates: list[str]) -> list[dict]:
        prompt = load_prompt(ctx.prompt_version)
        candidate_lines = "\n".join(f"- {t}" for t in rule_candidates[:80])
        user = (
            f"公司名称: {ctx.company_name or ''}\n股票代码: {ctx.stock_code or ''}\n\n"
            f"规则预提取候选句（仅作参考，请按规则筛选/拆分/补全结构化字段）：\n{candidate_lines}\n\n"
            f"报告文本块：\n{self.llm._blocks_to_text(blocks)}"
        )
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ]

    def extract_claims(self, document_context: DocumentContext, blocks: list) -> ClaimExtractionResult:
        cfg = self.settings
        if not cfg.claim_extraction_base_url or not cfg.claim_extraction_api_key or not cfg.claim_extraction_model:
            raise AppError(
                "Hybrid 模式需要配置 CLAIM_EXTRACTION_BASE_URL/MODEL/API_KEY 才能真实调用模型",
                status_code=422,
                code="LLM_NOT_CONFIGURED",
            )
        extractor = RuleBasedCandidateExtractor(
            entity_name=document_context.company_name or "美的集团",
            stock_code=document_context.stock_code or "000333",
            report_year=document_context.report_year,
        )
        rule_result = extractor.extract(blocks)
        candidates = [c.source_text for c in rule_result.candidates]

        messages = self._build_messages(document_context, blocks, candidates)
        content, usage = self._call_llm(messages)
        items = self.llm._parse_response(content)
        claim_dicts, failed = self.llm._to_claim_dicts(items)
        for d in claim_dicts:
            d["extraction_method"] = "HYBRID"
        return ClaimExtractionResult(
            claim_dicts=claim_dicts,
            provider="hybrid_rule_llm",
            model_name=cfg.claim_extraction_model,
            prompt_version=document_context.prompt_version,
            is_mock=False,
            schema_failed_count=failed,
            raw_response_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            token_usage=usage,
            candidate_sentence_count=rule_result.candidate_sentence_count,
            input_block_count=rule_result.input_block_count,
        )

    def _call_llm(self, messages: list[dict]) -> tuple[str, dict | None]:
        """Hybrid 的模型调用（复用 LLM Provider 的重试/超时逻辑）。"""
        return self.llm._call_model(messages)


class LLMClaimExtractionProvider:
    """openai_compatible 真实模型调用（结构化输出 + 超时/重试 + 记录）。"""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    # ---------- HTTP 调用（测试可 monkeypatch） ----------

    def _call_model(self, messages: list[dict]) -> tuple[str, dict | None]:
        cfg = self.settings
        url = f"{cfg.claim_extraction_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg.claim_extraction_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": cfg.claim_extraction_model, "messages": messages, "temperature": 0}
        last_exc: Exception | None = None
        for attempt in range(cfg.claim_extraction_max_retries + 1):
            try:
                resp = httpx.post(
                    url, json=payload, headers=headers,
                    timeout=cfg.claim_extraction_timeout_seconds,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content, data.get("usage")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("LLM 调用失败 attempt=%s error=%s", attempt + 1, exc)
                if attempt < cfg.claim_extraction_max_retries:
                    time.sleep(1 + attempt)
        raise AppError(
            f"主张提取模型调用失败: {last_exc}", status_code=502, code="LLM_CALL_FAILED"
        )

    # ---------- 响应解析与 Schema 预检 ----------

    def _parse_response(self, content: str) -> list[dict]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AppError(
                f"模型返回非法 JSON: {exc}", status_code=422, code="INVALID_LLM_JSON"
            ) from exc
        if isinstance(data, dict) and "claims" in data:
            data = data["claims"]
        if not isinstance(data, list):
            raise AppError(
                "模型返回结构不是主张数组", status_code=422, code="INVALID_LLM_JSON"
            )
        return data

    def _normalize_item(self, item: dict) -> dict | None:
        """字段映射 + 枚举/必填预检；失败返回 None（计为 schema_failed）。"""
        try:
            source_text = str(item.get("source_text") or "").strip()
            normalized = str(item.get("normalized_claim") or "").strip()
            if not source_text or not normalized:
                return None
            return {
                "source_text": source_text,
                "normalized_claim": normalized,
                "claim_type": ClaimType(item.get("claim_type")).value,
                "entity_name": item.get("entity_name"),
                "stock_code": item.get("stock_code"),
                "metric": item.get("metric"),
                "metric_code": item.get("metric_code"),
                "reported_value": item.get("reported_value"),
                "reported_value_text": str(item["reported_value_text"])
                if item.get("reported_value_text")
                else None,
                "value_operator": ValueOperator(item.get("value_operator", "EQUAL")).value,
                "unit": item.get("unit"),
                "currency": item.get("currency"),
                "period": item.get("period"),
                "period_type": PeriodType(item.get("period_type", "UNSPECIFIED")).value,
                "comparison_period": item.get("comparison_period"),
                "comparison_type": ComparisonType(item.get("comparison_type", "NONE")).value,
                "scope": item.get("scope") or "CONSOLIDATED",
                "business_segment": item.get("business_segment"),
                "geography": item.get("geography"),
                "claim_nature": ClaimNature(item.get("claim_nature", "FACT")).value,
                "risk_level": RiskLevel(item.get("risk_level", "MEDIUM")).value,
                "risk_reason": item.get("risk_reason"),
                "requires_calculation": bool(item.get("requires_calculation", False)),
                "requires_external_evidence": bool(item.get("requires_external_evidence", True)),
                "extraction_method": "LLM",
                "confidence": float(item.get("confidence", 0.9)),
            }
        except Exception:  # noqa: BLE001 —— 枚举非法/字段缺失
            return None

    def _to_claim_dicts(self, items: list[dict]) -> tuple[list[dict], int]:
        valid: list[dict] = []
        failed = 0
        for item in items:
            d = self._normalize_item(item)
            if d is None:
                failed += 1
                continue
            valid.append(d)
        return valid, failed

    def _blocks_to_text(self, blocks: list) -> str:
        lines = []
        for b in blocks:
            if getattr(b, "block_type", "") == "heading":
                lines.append("#" * (getattr(b, "heading_level", 1) or 1) + " " + (b.text or ""))
            else:
                lines.append(b.text or "")
        return "\n\n".join(lines)

    def extract_claims(self, document_context: DocumentContext, blocks: list) -> ClaimExtractionResult:
        cfg = self.settings
        prompt = load_prompt(document_context.prompt_version)
        user_content = (
            f"公司名称: {document_context.company_name or ''}\n"
            f"股票代码: {document_context.stock_code or ''}\n\n"
            f"{self._blocks_to_text(blocks)}"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        content, usage = self._call_model(messages)
        raw_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        items = self._parse_response(content)
        claim_dicts, failed = self._to_claim_dicts(items)
        return ClaimExtractionResult(
            claim_dicts=claim_dicts,
            provider=cfg.claim_extraction_provider,
            model_name=cfg.claim_extraction_model,
            prompt_version=document_context.prompt_version,
            is_mock=False,
            schema_failed_count=failed,
            raw_response_hash=raw_hash,
            token_usage=usage,
        )


def get_claim_provider(mode: str) -> ClaimExtractionProvider:
    """按模式返回 Provider：mock（默认）/ rules / llm / hybrid。"""
    if mode == "rules":
        return RuleOnlyClaimExtractionProvider()
    if mode == "llm":
        return LLMClaimExtractionProvider()
    if mode == "hybrid":
        return HybridClaimExtractionProvider()
    return MockClaimExtractionProvider()

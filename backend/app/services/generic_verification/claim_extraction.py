"""通用主张拆解规则层（领域无关）。

职责：标记候选块、提取数字/日期/交叉引用/实体、分类主张类型。
规则层不产出最终主张（最终结构化由 LLM 层完成）；无 LLM 时以规则结果 + is_mock 兜底。
"""

from __future__ import annotations

import re

# ---------- 正则 ----------
_NUM_UNIT_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?\s*([%％万亿千米吨克个件台套份家元]|美元|人民币)?")
_DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月|20\d{2}年")
# 裸年份（无单位），如 "2001 年" 中的 2001 —— 归类为日期/事实，不是可核验数字
_BARE_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
CROSS_REF_RE = re.compile(
    r"(?:第\s*\d+\s*[章节]|图\s*\d+(?:[-.]\d+)?|表\s*\d+(?:[-.]\d+)?|附录[A-Z\d]+|"
    r"见\s*上[文]?|见\s*下[文]?|"
    r"see\s+(?:chapter|figure|table|appendix)[^。；;\n]*|"
    r"参见\s*(?:第\s*\d+\s*[章节]|图\s*\d+|表\s*\d+|附录[A-Z\d]+))",
    re.IGNORECASE,
)

_CAUSAL_WORDS = ("导致", "推动", "主要由于", "主要系", "得益于", "带动", "because of", "due to", "resulted from")
_PREDICTION_WORDS = ("预计", "将", "计划", "预期", "展望", "forecast", "expect", "aim", "guidance")
_OPINION_WORDS = ("我们认为", "建议", "我们相信", "we believe", "we recommend")
_ENTITY_STOPWORDS = frozenset({
    "关于", "由于", "因此", "公司", "报告", "如下", "以上", "其中", "包括",
    "通过", "对于", "进行", "相关", "主要", "同时", "目前", "未来", "我们",
    "可以", "需要", "已经", "没有", "一个", "这个", "该", "的", "了", "和",
    "与", "及", "或", "在", "以", "从", "到", "被", "把", "为", "等",
    "项目", "信息",
})


def _strip_thousands(text: str) -> str:
    return text.replace(",", "").replace("，", "")


# 语境截断标点（数字前遇到这些字符即视为语境边界）
_CTX_PUNCT = "。；，、：！？．.,;:!?()（）《》「」""''"


def _preceding_context(text: str, pos: int, max_len: int = 20) -> str:
    """取数字前最近的语义语境：从 pos 向前，止于数字/标点或字符串开头。

    避免语境跨越其他数字（如「30%」的语境应止于「同比增长」，
    而不是「24年营业收入 1.2 亿元，同比增长」）。
    """
    start = pos
    while start > 0:
        ch = text[start - 1]
        if ch.isdigit() or ch in _CTX_PUNCT:
            break
        start -= 1
    return text[start:pos].strip()[:max_len]


def extract_numbers(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _NUM_UNIT_RE.finditer(text):
        raw = m.group(0)
        unit = (m.group(1) or "").strip() or None
        num_part = re.match(r"[-+]?\d[\d,，]*(?:\.\d+)?", raw).group(0)
        try:
            value = float(_strip_thousands(num_part))
        except ValueError:
            continue
        # 裸年份（如 2001）不是可核验数字，跳过（归类为日期/事实）
        if unit is None and _BARE_YEAR_RE.fullmatch(_strip_thousands(num_part)):
            continue
        ctx = _preceding_context(text, m.start())
        out.append({"value": value, "unit": unit, "context": ctx})
    return out


def extract_dates(text: str) -> list[str]:
    return list(dict.fromkeys(_DATE_RE.findall(text)))


def extract_cross_refs(text: str) -> list[str]:
    return [m.group(0).strip() for m in CROSS_REF_RE.finditer(text)]


def classify_kind(text: str) -> str:
    if any(w in text for w in _PREDICTION_WORDS):
        return "PREDICTION"
    if any(w in text for w in _OPINION_WORDS):
        return "OPINION"
    if any(w in text for w in _CAUSAL_WORDS):
        return "CAUSAL"
    if extract_numbers(text):
        return "NUMERIC"
    if extract_cross_refs(text):
        return "REFERENCE"
    return "FACT"


def extract_entities(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    out: list[str] = []
    for w in words:
        if w in _ENTITY_STOPWORDS or w in out:
            continue
        # 停用词字符覆盖比例 ≥ 50%（如"本项目没有需要核验"）→ 非实体；
        # 长实体名（如"华为技术有限公司"）覆盖比例低，保留
        covered = sum(len(s) for s in _ENTITY_STOPWORDS if s in w)
        if covered / len(w) >= 0.5:
            continue
        out.append(w)
    return out


def mark_candidate_blocks(blocks: list) -> set[int]:
    marked: set[int] = set()
    for i, b in enumerate(blocks):
        text = b.get("text") or ""
        if b.get("block_type") == "heading":
            continue
        if (
            extract_numbers(text) or extract_dates(text) or extract_cross_refs(text)
            or bool(_BARE_YEAR_RE.search(text))
            or extract_entities(text)
            or any(w in text for w in _CAUSAL_WORDS + _PREDICTION_WORDS + _OPINION_WORDS)
        ):
            marked.add(i)
    return marked


# ---------------------------------------------------------------------------
# 主张拆解 Provider（领域无关）
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.services.generic_verification.schemas import GenericClaim  # noqa: E402

logger = logging.getLogger(__name__)

GENERIC_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_generic_prompt(version: str) -> str:
    path = GENERIC_PROMPT_DIR / f"{version}.txt"
    if not path.exists():
        raise AppError(f"通用主张 Prompt 版本不存在: {version}", status_code=500, code="PROMPT_NOT_FOUND")
    return path.read_text(encoding="utf-8")


@dataclass
class GenericClaimExtractionResult:
    claims: list[GenericClaim] = field(default_factory=list)
    provider: str = ""
    model_name: str | None = None
    is_mock: bool = False
    input_block_count: int = 0
    candidate_sentence_count: int = 0


class GenericClaimExtractor:
    """领域无关主张拆解：有 LLM 配置 → LLM 结构化；无配置 → 规则 + is_mock。"""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    # ---------- 公开入口 ----------

    def extract(self, blocks: list[dict], prompt_version: str = "generic_claim_extraction_v1") -> GenericClaimExtractionResult:
        cfg = self.settings
        if not (cfg.claim_extraction_base_url and cfg.claim_extraction_api_key and cfg.claim_extraction_model):
            claims = self._rules_only(blocks)
            return GenericClaimExtractionResult(
                claims=claims, provider="mock", is_mock=True,
                input_block_count=len(blocks), candidate_sentence_count=len(claims),
            )
        prompt = load_generic_prompt(prompt_version)
        claims: list[GenericClaim] = []
        for i, b in enumerate(blocks):
            text = b.get("text") or ""
            if not text.strip():
                continue
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": (
                    f"页码: {b.get('page_number', 1)}\n块序号: {i}\n\n"
                    f"【当前段落】\n{text}\n"
                )},
            ]
            content, _usage = self._call_llm(messages)
            for item in self._parse_response(content):
                claims.append(self._to_claim(item, b, i))
        return GenericClaimExtractionResult(
            claims=claims, provider="llm", model_name=cfg.claim_extraction_model,
            is_mock=False, input_block_count=len(blocks),
            candidate_sentence_count=len(claims),
        )

    # ---------- 规则兜底 ----------

    def _rules_only(self, blocks: list[dict]) -> list[GenericClaim]:
        marked = mark_candidate_blocks(blocks)
        out: list[GenericClaim] = []
        for i, b in enumerate(blocks):
            if i not in marked:
                continue
            text = b.get("text") or ""
            out.append(GenericClaim(
                claim_id=f"GCLM-{i:03d}",
                source_text=text,
                claim_kind=classify_kind(text),
                page_number=int(b.get("page_number") or 1),
                block_index=i,
                entities=extract_entities(text),
                numbers=extract_numbers(text),
                dates=extract_dates(text),
                cross_refs=extract_cross_refs(text),
                extraction_method="rules",
                confidence=0.7,
            ))
        return out

    # ---------- LLM ----------

    def _call_llm(self, messages: list[dict]) -> tuple[str, dict | None]:
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
                resp = httpx.post(url, json=payload, headers=headers,
                                  timeout=cfg.claim_extraction_timeout_seconds)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"], data.get("usage")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < cfg.claim_extraction_max_retries:
                    continue
        raise AppError(f"通用主张拆解 LLM 调用失败: {last_exc}", status_code=502, code="LLM_CALL_FAILED")

    def _parse_response(self, content: str) -> list[dict]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("[")
            end = content.rfind("]")
            if start < 0 or end < start:
                logger.warning("generic extraction: invalid JSON from LLM, len=%s", len(content))
                return []
            try:
                data = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("source_text"):
                continue
            out.append(item)
        return out

    def _to_claim(self, item: dict, block: dict, index: int) -> GenericClaim:
        def _safe_int(value, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _safe_float(value, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def _safe_list(value) -> list:
            return value if isinstance(value, list) else []

        # LLM 输出是不可信边界输入：转换失败回退到块值/默认值，绝不抛异常
        return GenericClaim(
            claim_id=item.get("claim_id") or f"GCLM-{index:03d}",
            source_text=item["source_text"],
            claim_kind=item.get("claim_kind") or "FACT",
            page_number=_safe_int(item.get("page_number"), block.get("page_number") or 1),
            block_index=_safe_int(item.get("block_index"), index),
            entities=_safe_list(item.get("entities")),
            numbers=_safe_list(item.get("numbers")),
            dates=_safe_list(item.get("dates")),
            cross_refs=_safe_list(item.get("cross_refs")),
            extraction_method="llm",
            confidence=_safe_float(item.get("confidence"), 0.8),
        )

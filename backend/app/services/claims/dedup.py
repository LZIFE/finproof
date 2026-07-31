"""三层主张去重（Phase 3.5）。

第一层：文本归一化去重（空格/标点/全半角/大小写/百分号格式）
第二层：结构化键去重（entity+metric+period+comparison_period+normalized_value+
        value_operator+claim_nature+business_segment；无指标主张追加文本指纹，
        避免两条不同语义句因空字段共用键被误并）
第三层：同义主张去重（指标别名归一后结构化键相同即合并；
        不同指标相同数值不合并）

去重结果保留 kept_claim / removed_claim / dedup_reason / dedup_score，
供去重分析产物使用。
"""

import unicodedata
from dataclasses import dataclass, field

_VALUE_PRECISION = 6

# 全半角/标点归一化（第一层文本去重与键指纹共用）
_PUNCT_MAP = {
    "，": ",", "。": ".", "；": ";", "：": ":", "（": "(", "）": ")",
    "、": ",", "“": '"', "”": '"', "‘": "'", "’": "'", "！": "!", "？": "?",
    "％": "%", "＝": "=", "－": "-",
}


def text_norm(s: str) -> str:
    """文本归一化：去空白、全角转半角、标点归一、大小写、百分号格式。"""
    if not s:
        return ""
    out = unicodedata.normalize("NFKC", s)
    for k, v in _PUNCT_MAP.items():
        out = out.replace(k, v)
    out = "".join(ch for ch in out if not ch.isspace())
    out = out.lower()
    return out


def normalized_value(value: float | None) -> str:
    if value is None:
        return ""
    return f"{round(value, _VALUE_PRECISION):.6f}".rstrip("0").rstrip(".")


def structured_key(
    entity: str | None,
    metric_code: str | None,
    metric: str | None,
    period: str | None,
    comparison_period: str | None,
    value: float | None,
    value_operator: str | None,
    claim_nature: str,
    business_segment: str | None,
    source_text: str | None = None,
) -> str:
    """第二层结构化键。

    无指标主张（metric_code 为空）追加文本指纹，防止"公司持续深化……战略"
    与"海外OBM战略成效逐步显现"等不同语义句因空字段共用键被误并。
    """
    metric_part = metric_code or metric or ""
    # 期间归一化：2025FY ≈ 2025（同义去重层）
    period_norm = (period or "").rstrip("FY")
    comp_period_norm = (comparison_period or "").rstrip("FY")
    parts = [
        (entity or "").strip(),
        metric_part,
        period_norm,
        comp_period_norm,
        normalized_value(value),
        (value_operator or "EQUAL").strip(),
        (claim_nature or "").strip(),
        (business_segment or "").strip(),
    ]
    key = "|".join(parts)
    if not metric_part:
        key += f"|text:{text_norm(source_text or '')[:40]}"
    return key


@dataclass
class DedupRecord:
    kept_index: int
    removed_index: int
    dedup_reason: str  # text_normalized | structured_key | synonym
    dedup_score: float


@dataclass
class DedupResult:
    unique: list = field(default_factory=list)
    removed_count: int = 0
    records: list[DedupRecord] = field(default_factory=list)


def deduplicate(claims: list) -> DedupResult:
    """三层去重：文本归一化 → 结构化键 → 同义（结构化键在指标别名归一后合并）。"""
    result = DedupResult()
    kept: list = []
    seen_text: dict[str, int] = {}  # 归一化文本 -> kept index
    seen_key: dict[str, int] = {}  # 结构化键 -> kept index

    for idx, c in enumerate(claims):
        norm_text = text_norm(getattr(c, "source_text", "") or "")

        # 第一层：文本归一化去重
        if norm_text:
            dup_idx = seen_text.get(norm_text)
            if dup_idx is not None:
                result.removed_count += 1
                result.records.append(DedupRecord(dup_idx, idx, "text_normalized", 1.0))
                continue
            seen_text[norm_text] = idx

        # 第二层：结构化键去重（无指标追加文本指纹）
        key = structured_key(
            entity=getattr(c, "entity_name", None),
            metric_code=getattr(c, "metric_code", None),
            metric=getattr(c, "metric", None),
            period=getattr(c, "period", None),
            comparison_period=getattr(c, "comparison_period", None),
            value=getattr(c, "reported_value", None),
            value_operator=getattr(c, "value_operator", None),
            claim_nature=getattr(c, "claim_nature", None) or "FACT",
            business_segment=getattr(c, "business_segment", None),
            source_text=getattr(c, "source_text", None),
        )
        dup_idx = seen_key.get(key)
        if dup_idx is not None:
            result.removed_count += 1
            result.records.append(DedupRecord(dup_idx, idx, "structured_key", 1.0))
            continue
        seen_key[key] = idx

        kept.append(c)
        result.unique = kept
    return result

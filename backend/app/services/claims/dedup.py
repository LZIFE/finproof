"""主张去重（Phase 3）。

策略：标准化去重键
    entity + metric + period + comparison_period + normalized_value + claim_nature

覆盖：完全重复句、标点/空白差异、轻微改写、规则与 LLM 对同一复合句的重复提取、
跨相邻文本块重复。不同指标相同数值（如 收入100亿 / 净利润100亿）键不同，不会误去重。
"""

from dataclasses import dataclass

_VALUE_PRECISION = 6


def normalized_value(value: float | None) -> str:
    if value is None:
        return ""
    return f"{round(value, _VALUE_PRECISION):.6f}".rstrip("0").rstrip(".")


def dedup_key(
    entity: str | None,
    metric_code: str | None,
    metric: str | None,
    period: str | None,
    comparison_period: str | None,
    value: float | None,
    claim_nature: str,
) -> str:
    parts = [
        (entity or "").strip(),
        (metric_code or metric or "").strip(),
        (period or "").strip(),
        (comparison_period or "").strip(),
        normalized_value(value),
        (claim_nature or "").strip(),
    ]
    return "|".join(parts)


@dataclass
class DedupResult:
    unique: list
    removed_count: int


def deduplicate(claims: list) -> DedupResult:
    """按标准化去重键去重，保留首次出现的条目。"""
    seen: set[str] = set()
    unique: list = []
    removed = 0
    for c in claims:
        key = dedup_key(
            entity=getattr(c, "entity_name", None),
            metric_code=getattr(c, "metric_code", None),
            metric=getattr(c, "metric", None),
            period=getattr(c, "period", None),
            comparison_period=getattr(c, "comparison_period", None),
            value=getattr(c, "reported_value", None),
            claim_nature=getattr(c, "claim_nature", None) or "FACT",
        )
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        unique.append(c)
    return DedupResult(unique=unique, removed_count=removed)

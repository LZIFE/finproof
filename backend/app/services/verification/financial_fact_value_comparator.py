"""Phase 23.36 Task 2 — Financial Fact Value Comparator

解决 REFUTED 过度触发：value conflict 判定前先做三层兼容性检查。

1. Unit normalization：亿元/万元/千元/元 统一换算到元比较。
2. Rounding tolerance：允许财务报告四舍五入误差（默认 ±5%）。
3. Metric strictness：区分严格（营业收入 ≠ 净利润）与宽松（营业收入 ≈ 主营业务收入）；
   增长率/比例类 claim（值百分比）不与绝对值 value 比较——只比较 growth 字段。

输出 compare_values()：返回 {compatible, reason, claim_yuan, fact_yuan, ratio}
"""
from __future__ import annotations

import re

# 单位换算（统一到元）
UNIT_SCALE = {"元": 1.0, "千元": 1000.0, "万元": 1e4, "百万元": 1e6, "亿元": 1e8}

# 默认四舍五入容差（±5%）
DEFAULT_TOLERANCE = 0.05

# growth/ratio 类 metric（claim value 是百分比，不与绝对值比较）
_RATIO_METRICS = {"gross_margin", "gross_margin_change", "roe", "net_margin"}
_GROWTH_PREFIXES = ("yoy_growth_", "qoq_growth_", "growth_", "change_")


def _normalize_to_yuan(value, unit) -> float | None:
    """单位归一化到元。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    u = (unit or "").replace("人民币", "").strip()
    scale = UNIT_SCALE.get(u, UNIT_SCALE.get("千元", 1000.0))
    return v * scale


def _is_growth_like(claim) -> bool:
    """claim 是否为增长率/比例类（值百分比，不与绝对值比较）。"""
    code = str(claim.get("metric_code") or "").strip()
    metric = str(claim.get("metric") or "").strip()
    unit = str(claim.get("unit") or "").strip()
    if code.startswith(_GROWTH_PREFIXES) or code in _RATIO_METRICS:
        return True
    if metric and any(k in metric for k in ("同比", "增长", "YoY", "增速", "增幅")):
        return True
    if unit in ("%", "％"):
        return True
    return False


def _is_ratio_fact(fact) -> bool:
    """fact 是否为比例类指标（值应为无单位/百分比）。"""
    code = str(fact.get("metric_code") or "").strip()
    unit = str(fact.get("unit") or "").strip()
    if code in _RATIO_METRICS:
        return True
    if unit in ("%", "％"):
        return True
    return False


def compare_values(
    claim,
    fact,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict:
    """Value Compatibility：claim value vs fact current_value（单位归一 + 容差 + metric strictness）。

    返回：
        {
          "compatible": bool,
          "reason": str,
          "claim_yuan": float | None,
          "fact_yuan": float | None,
          "ratio": float | None,
        }

    规则：
    - claim 是 growth/ratio 类（值百分比）→ 不与 fact 绝对值比较 → compatible=True
      （只比较 growth 字段，由 verifier 处理）
    - fact 是 ratio 类但带金额单位 → 视为 extraction 错误 → compatible=False（sanity 失败）
    - 单位归一后 ratio 在 [1-tolerance, 1+tolerance] → compatible=True
    """
    claim_value = claim.get("reported_value") or claim.get("value")
    if isinstance(claim_value, str):
        try:
            claim_value = float(claim_value.replace(",", ""))
        except ValueError:
            claim_value = None
    fact_value = fact.get("current_value")

    # fact sanity 优先：ratio 类 fact 带金额单位 → extraction 错误（先于 growth-like 检查）
    if _is_ratio_fact(fact) and str(fact.get("unit") or "").strip() not in ("%", "％", ""):
        return {
            "compatible": False, "reason": f"ratio 类 fact 带金额单位（{fact.get('unit')}），值可疑",
            "claim_yuan": None, "fact_yuan": None, "ratio": None,
        }

    # Metric strictness：growth/ratio 类 claim 不与绝对值比较
    if _is_growth_like(claim):
        return {
            "compatible": True, "reason": "claim 为增长率/比例类，不与绝对值比较（由 growth 比较处理）",
            "claim_yuan": None, "fact_yuan": None, "ratio": None,
        }

    if claim_value is None or fact_value is None:
        return {
            "compatible": True, "reason": "缺 value，不判定冲突",
            "claim_yuan": None, "fact_yuan": None, "ratio": None,
        }

    claim_yuan = _normalize_to_yuan(claim_value, claim.get("unit"))
    fact_yuan = _normalize_to_yuan(fact_value, fact.get("unit"))
    if claim_yuan is None or fact_yuan is None or fact_yuan == 0:
        return {
            "compatible": True, "reason": "无法换算，不判定冲突",
            "claim_yuan": claim_yuan, "fact_yuan": fact_yuan, "ratio": None,
        }

    ratio = claim_yuan / fact_yuan
    compatible = (1 - tolerance) <= ratio <= (1 + tolerance)
    reason = (
        "单位归一后值兼容（四舍五入容差内）" if compatible
        else f"单位归一后值差异超容差（ratio={ratio:.4f} > tolerance={tolerance}）"
    )
    return {
        "compatible": compatible,
        "reason": reason,
        "claim_yuan": round(claim_yuan, 2),
        "fact_yuan": round(fact_yuan, 2),
        "ratio": round(ratio, 4),
    }

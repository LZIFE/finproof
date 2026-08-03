"""Phase 23.8 重构指标和口径解析。

版本化 metric_aliases + ScopeContext。

metric_aliases 至少覆盖：
- 营业收入/营业总收入/收入/revenue
- 净利润 / 归母净利润 / 扣非归母净利润 / 合并净利润
- 经营活动现金流净额
- 毛利率 / 净利率
- EPS / 基本每股收益 / 稀释每股收益
- 海外收入 / 国内收入 / 分部收入
- 应收账款 / 存货

ScopeContext 覆盖：
- consolidated / parent_attributable / non_controlling_interest
- adjusted / reported / segment / geography / product

不同口径不得仅因数字接近而判 SUPPORTED。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# ScopeContext
# ---------------------------------------------------------------------------
ScopeType = Literal[
    "consolidated", "parent_attributable", "non_controlling_interest",
    "adjusted", "reported", "segment", "geography", "product", "unknown",
]

# 中文口径 → ScopeType
_SCOPE_CN_MAP: dict[str, ScopeType] = {
    "归属于上市公司股东的净利润": "parent_attributable",
    "归属于上市公司股东": "parent_attributable",
    "归属于母公司": "parent_attributable",
    "归母": "parent_attributable",
    "合并": "consolidated",
    "少数股东": "non_controlling_interest",
    "扣非": "adjusted",
    "调整后": "adjusted",
    "报告": "reported",
    "分部": "segment",
    "地区": "geography",
    "产品": "product",
}

_SCOPE_PATTERN = "|".join(re.escape(k) for k in sorted(_SCOPE_CN_MAP.keys(), key=len, reverse=True))


@dataclass
class ScopeContext:
    """口径上下文（3 字段）。"""
    scope_type: ScopeType
    raw_text: str           # 原始口径文本（如"归母"/"扣非"）
    confidence: float       # 0.0-1.0

    def to_dict(self) -> dict:
        return {
            "scope_type": self.scope_type,
            "raw_text": self.raw_text,
            "confidence": round(self.confidence, 3),
        }

    @property
    def is_consolidated(self) -> bool:
        return self.scope_type == "consolidated"

    @property
    def is_parent_attributable(self) -> bool:
        return self.scope_type == "parent_attributable"


def parse_scope(scope_str: str) -> ScopeContext:
    """从口径字符串解析 ScopeContext。"""
    if not scope_str:
        return ScopeContext(scope_type="consolidated", raw_text="", confidence=0.5)
    text = scope_str.strip()
    for cn, st in sorted(_SCOPE_CN_MAP.items(), key=lambda x: -len(x[0])):
        if cn in text:
            return ScopeContext(scope_type=st, raw_text=cn, confidence=0.9)
    # 英文 fallback
    text_lower = text.lower()
    en_map: dict[str, ScopeType] = {
        "consolidated": "consolidated", "parent": "parent_attributable",
        "adjusted": "adjusted", "reported": "reported",
        "segment": "segment", "geography": "geography", "product": "product",
    }
    for en, st in en_map.items():
        if en in text_lower:
            return ScopeContext(scope_type=st, raw_text=en, confidence=0.85)
    return ScopeContext(scope_type="unknown", raw_text=text, confidence=0.3)


def scopes_compatible(claim_scope: ScopeContext, evidence_scope: ScopeContext) -> tuple[bool, str]:
    """判断 claim 口径与 evidence 口径是否兼容。

    不同口径不得仅因数字接近而判 SUPPORTED。
    - consolidated vs parent_attributable 不兼容（归母≠合并）
    - adjusted vs reported 不兼容（扣非≠报告值）
    - unknown 与任何都兼容（保守策略，避免误拒）
    """
    if claim_scope.scope_type == "unknown" or evidence_scope.scope_type == "unknown":
        return True, "一方口径未知，保守兼容"
    if claim_scope.scope_type != evidence_scope.scope_type:
        return False, (
            f"口径不兼容：claim={claim_scope.scope_type} ({claim_scope.raw_text}) "
            f"ev={evidence_scope.scope_type} ({evidence_scope.raw_text})"
        )
    return True, "口径兼容"


# ---------------------------------------------------------------------------
# 版本化 metric_aliases
# ---------------------------------------------------------------------------
METRIC_ALIASES_VERSION = "23.8.0"

# 标准指标名 → 别名列表（含中英文）
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "营业收入", "营业总收入", "收入", "营收", "revenue", "sales", "total_revenue",
    ),
    "net_profit": (
        "净利润", "净利", "net_profit", "net_income", "profit",
    ),
    "net_profit_parent": (
        "归母净利润", "归属于母公司净利润", "归母净利", "净利润归母",
        "net_profit_attributable_to_parent", "parent_net_profit",
    ),
    "net_profit_ex_recurring": (
        "扣非归母净利润", "扣非净利润", "扣非归母", "扣除非经常性损益的净利润",
        "adjusted_net_profit", "net_profit_ex_non_recurring",
    ),
    "consolidated_net_profit": (
        "合并净利润", "总净利润", "consolidated_net_profit",
    ),
    "operating_cash_flow": (
        "经营活动现金流净额", "经营现金流", "经营活动产生的现金流量净额",
        "operating_cash_flow", "cfo", "cash_flow_from_operations",
    ),
    "gross_margin": (
        "毛利率", "gross_margin", "gross_profit_margin",
    ),
    "net_margin": (
        "净利率", "净利率", "net_margin", "net_profit_margin",
    ),
    "eps": (
        "每股收益", "EPS", "earnings_per_share",
    ),
    "eps_basic": (
        "基本每股收益", "basic_eps", "earnings_per_share_basic",
    ),
    "eps_diluted": (
        "稀释每股收益", "diluted_eps", "earnings_per_share_diluted",
    ),
    "overseas_revenue": (
        "海外收入", "境外收入", "国外收入", "overseas_revenue", "foreign_revenue",
    ),
    "domestic_revenue": (
        "国内收入", "境内收入", "domestic_revenue",
    ),
    "segment_revenue": (
        "分部收入", "部门收入", "segment_revenue", "divisional_revenue",
    ),
    "accounts_receivable": (
        "应收账款", "应收款", "accounts_receivable", "trade_receivables",
    ),
    "inventory": (
        "存货", "库存", "inventory", "stock",
    ),
    "total_assets": (
        "总资产", "资产总额", "total_assets",
    ),
    "roe": (
        "加权平均净资产收益率", "净资产收益率", "加权净资产收益率", "ROE", "roe",
    ),
    "total_liabilities": (
        "总负债", "负债总额", "total_liabilities",
    ),
    "equity": (
        "所有者权益", "股东权益", "净资产", "equity", "shareholders_equity",
    ),
    "revenue_yoy": (
        "营收同比增长", "营收增速", "revenue_yoy", "revenue_growth_yoy",
    ),
    "net_profit_yoy": (
        "净利润同比增长", "净利增速", "net_profit_yoy", "profit_growth_yoy",
    ),
}

# 反向索引：别名 → 标准指标名
_ALIAS_TO_STANDARD: dict[str, str] = {}
for std, aliases in METRIC_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_STANDARD[alias.lower()] = std


def normalize_metric(metric: str) -> tuple[str, float]:
    """将指标名归一化为标准名。

    Returns:
        (standard_metric, confidence)
        confidence: 1.0=精确匹配, 0.85=包含匹配, 0.3=未匹配
    """
    if not metric:
        return ("", 0.0)
    m_lower = metric.strip().lower()
    # 精确匹配
    if m_lower in _ALIAS_TO_STANDARD:
        return (_ALIAS_TO_STANDARD[m_lower], 1.0)
    # 包含匹配（metric 是别名的子串，或反过来）
    for alias, std in _ALIAS_TO_STANDARD.items():
        if alias in m_lower or m_lower in alias:
            # 选最长的匹配（避免"收入"匹配"海外收入"和"营业收入"两个）
            return (std, 0.85)
    return (metric, 0.3)


def metrics_compatible(claim_metric: str, evidence_metric: str) -> tuple[bool, str]:
    """判断 claim 指标与 evidence 指标是否兼容。"""
    claim_std, claim_conf = normalize_metric(claim_metric)
    ev_std, ev_conf = normalize_metric(evidence_metric)
    if not claim_std or not ev_std:
        return False, "指标为空"
    if claim_std == ev_std:
        return True, f"指标兼容（标准={claim_std}）"
    # 同类指标但不同口径（如 net_profit vs net_profit_parent）需谨慎
    if claim_std.split("_")[0] == ev_std.split("_")[0]:
        # 同前缀但不同后缀，可能口径不同，保守判不兼容
        return False, f"指标前缀相同但口径不同：claim={claim_std} ev={ev_std}"
    return False, f"指标不兼容：claim={claim_std} ev={ev_std}"


def query_expansion(metric: str) -> list[str]:
    """metric alias query expansion：返回该指标的所有别名用于检索。"""
    std, conf = normalize_metric(metric)
    if not std or conf < 0.5:
        return [metric] if metric else []
    return list(METRIC_ALIASES.get(std, [metric]))


__all__ = [
    "METRIC_ALIASES",
    "METRIC_ALIASES_VERSION",
    "ScopeContext",
    "ScopeType",
    "parse_scope",
    "scopes_compatible",
    "normalize_metric",
    "metrics_compatible",
    "query_expansion",
]

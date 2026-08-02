"""Phase 23.8 重构期间解析。

Structured PeriodContext：支持 standalone vs cumulative 区分与单季度推导。

字段：
- fiscal_year / fiscal_quarter / start_date / end_date
- duration_type (instant | duration)
- standalone_or_cumulative (standalone | cumulative | ytd)
- yoy_base_period
- document_type (annual | semi | q1 | q3 | annual_interim)

支持识别：
- 年度 / 半年度 / 第一季度 / 第三季度 / 单季度
- 年初至今 / 本报告期 / 上年同期 / 期末 / 期初
- Q2 standalone / H1 cumulative

对于季度累计值，不得直接作为单季度值。
需要单季度推导时：Q2 standalone = H1 cumulative - Q1 cumulative
所有推导返回：formula / input_values / calculated_value / evidence_ids / tolerance
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DurationType = Literal["instant", "duration"]
StandaloneOrCumulative = Literal["standalone", "cumulative", "ytd", "unknown"]
DocumentType = Literal["annual", "semi", "q1", "q3", "annual_interim", "unknown"]

# 中文季度名 → fiscal_quarter
_QUARTER_CN_MAP: dict[str, int] = {
    "第一季度": 1, "一季度": 1, "一季报": 1,
    "第三季度": 3, "三季度": 3, "三季报": 3,
    "第二季度": 2, "二季度": 2, "二季报": 2,
    "第四季度": 4, "四季度": 4, "四季报": 4,
}

# 年度/半年度关键词
_ANNUAL_RE = re.compile(r"(年度|年报|全年|FY|annual)", re.IGNORECASE | re.UNICODE)
_SEMI_RE = re.compile(r"(半年度|中报|半年报|H1|semi|interim)", re.IGNORECASE | re.UNICODE)
_Q1_RE = re.compile(r"(Q1|第一季度|一季)", re.IGNORECASE | re.UNICODE)
_Q3_RE = re.compile(r"(Q3|第三季度|三季)", re.IGNORECASE | re.UNICODE)

# 累计 vs 单季
_YTD_RE = re.compile(r"(年初至今|本报告期|累计|YTD|cumulative)", re.IGNORECASE | re.UNICODE)
_STANDALONE_RE = re.compile(r"(单季|单季度|standalone|环比)", re.IGNORECASE | re.UNICODE)

# 上年同期
_YOY_BASE_RE = re.compile(r"(上年同期|去年同期|比上年|上年|去年|同比)", re.UNICODE)

# 期末/期初
_INSTANT_RE = re.compile(r"(期末|期初|年末|年初|year[\s-]?end|year[\s-]?begin)", re.IGNORECASE | re.UNICODE)

# 标准期间格式 YYYYFY / YYYYQn / YYYYH1
_STD_PERIOD_RE = re.compile(r"(\d{4})(?:FY|Q([1-4])|H([1-2]))", re.IGNORECASE)


@dataclass
class PeriodContext:
    """结构化期间上下文（10 字段）。"""
    fiscal_year: int | None                  # 2025
    fiscal_quarter: int | None               # 1/2/3/4，半年度为 None
    start_date: str | None                   # ISO 格式或 None
    end_date: str | None                     # ISO 格式或 None
    duration_type: DurationType              # instant（期末余额）| duration（期间发生额）
    standalone_or_cumulative: StandaloneOrCumulative
    yoy_base_period: str | None              # "2024FY" / "2024Q1" 等
    document_type: DocumentType

    def to_dict(self) -> dict:
        return {
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "duration_type": self.duration_type,
            "standalone_or_cumulative": self.standalone_or_cumulative,
            "yoy_base_period": self.yoy_base_period,
            "document_type": self.document_type,
        }

    @property
    def is_cumulative(self) -> bool:
        return self.standalone_or_cumulative in ("cumulative", "ytd")

    @property
    def is_standalone(self) -> bool:
        return self.standalone_or_cumulative == "standalone"

    @property
    def is_annual(self) -> bool:
        return self.document_type == "annual"

    @property
    def is_semi(self) -> bool:
        return self.document_type == "semi"


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------
def parse_period(period_str: str, document_type_hint: DocumentType = "unknown") -> PeriodContext:
    """从期间字符串解析 PeriodContext。

    支持格式：
    - "2025FY" / "2025年报" / "2025年度"
    - "2025H1" / "2025半年度" / "2025中报"
    - "2025Q1" / "2025第一季度" / "2025一季报"
    - "2025Q3" / "2025第三季度" / "2025三季报"
    - "2025Q2 standalone" / "2025单季度Q2"
    - "2025YTD" / "2025年初至今" / "2025累计"
    - "上年同期" / "2024同期"
    """
    if not period_str:
        return PeriodContext(
            fiscal_year=None, fiscal_quarter=None, start_date=None, end_date=None,
            duration_type="duration", standalone_or_cumulative="unknown",
            yoy_base_period=None, document_type=document_type_hint,
        )

    text = period_str.strip()
    year: int | None = None
    quarter: int | None = None
    duration: DurationType = "duration"
    standalone_cumul: StandaloneOrCumulative = "unknown"
    doc_type: DocumentType = document_type_hint
    yoy_base: str | None = None

    # 1. 标准格式 YYYYFY / YYYYQn / YYYYH1
    m = _STD_PERIOD_RE.search(text)
    if m:
        year = int(m.group(1))
        if m.group(2):  # Qn
            quarter = int(m.group(2))
            doc_type = {1: "q1", 3: "q3"}.get(quarter, "unknown")
        elif m.group(3):  # Hn
            quarter = None
            doc_type = "semi" if int(m.group(3)) == 1 else "annual"

    # 2. 中文季度名
    for cn, q in _QUARTER_CN_MAP.items():
        if cn in text:
            quarter = q
            if year is None:
                year_m = re.search(r"(\d{4})", text)
                if year_m:
                    year = int(year_m.group(1))
            if quarter == 1:
                doc_type = "q1"
            elif quarter == 3:
                doc_type = "q3"
            break

    # 3. 年度/半年度关键词
    if year is None:
        year_m = re.search(r"(\d{4})", text)
        if year_m:
            year = int(year_m.group(1))

    if _ANNUAL_RE.search(text):
        doc_type = "annual"
        quarter = None
    elif _SEMI_RE.search(text):
        doc_type = "semi"
        quarter = None
    elif _Q1_RE.search(text):
        quarter = 1
        doc_type = "q1"
    elif _Q3_RE.search(text):
        quarter = 3
        doc_type = "q3"

    # 4. 累计 vs 单季
    if _YTD_RE.search(text):
        standalone_cumul = "cumulative" if "Q" in text or quarter else "ytd"
    if _STANDALONE_RE.search(text):
        standalone_cumul = "standalone"
    # 默认：年度/半年度为 cumulative，Q1 为 standalone，Q3 为 cumulative（前三季累计）
    if standalone_cumul == "unknown":
        if doc_type == "annual" or doc_type == "semi":
            standalone_cumul = "cumulative"
        elif quarter == 1:
            standalone_cumul = "standalone"
        elif quarter == 3:
            standalone_cumul = "cumulative"  # 三季报通常是前三季累计
        elif quarter == 2:
            standalone_cumul = "unknown"  # Q2 需明确标注 standalone vs cumulative

    # 5. 上年同期
    if _YOY_BASE_RE.search(text):
        if year:
            yoy_base = f"{year - 1}FY" if doc_type == "annual" else f"{year - 1}Q{quarter or 1}"

    # 6. 期末/期初 → instant
    if _INSTANT_RE.search(text):
        duration = "instant"

    # 7. end_date / start_date 粗略推算（仅年度与半年度）
    end_date = None
    start_date = None
    if year and doc_type == "annual":
        end_date = f"{year}-12-31"
        start_date = f"{year}-01-01"
    elif year and doc_type == "semi":
        end_date = f"{year}-06-30"
        start_date = f"{year}-01-01"
    elif year and quarter == 1:
        end_date = f"{year}-03-31"
        start_date = f"{year}-01-01"
    elif year and quarter == 3:
        end_date = f"{year}-09-30"
        start_date = f"{year}-01-01"  # 三季报累计

    return PeriodContext(
        fiscal_year=year, fiscal_quarter=quarter, start_date=start_date, end_date=end_date,
        duration_type=duration, standalone_or_cumulative=standalone_cumul,
        yoy_base_period=yoy_base, document_type=doc_type,
    )


# ---------------------------------------------------------------------------
# 单季度推导
# ---------------------------------------------------------------------------
@dataclass
class DerivedValue:
    """推导值的结构化结果（5 字段）。"""
    formula: str
    input_values: list[float]
    calculated_value: float
    evidence_ids: list[str]
    tolerance: float

    def to_dict(self) -> dict:
        return {
            "formula": self.formula,
            "input_values": self.input_values,
            "calculated_value": round(self.calculated_value, 6),
            "evidence_ids": self.evidence_ids,
            "tolerance": self.tolerance,
        }


def derive_standalone_quarter(
    cumulative_h1: float, cumulative_q1: float,
    evidence_h1_id: str = "", evidence_q1_id: str = "",
    tolerance: float = 0.005,
) -> DerivedValue:
    """Q2 standalone = H1 cumulative - Q1 cumulative。

    Phase 23.8 重构：对于季度累计值，不得直接作为单季度值。
    需要单季度推导时，明确记录 formula / input_values / calculated_value / evidence_ids / tolerance。

    Args:
        cumulative_h1: 上半年累计值（H1）
        cumulative_q1: 第一季度累计值（Q1）
        evidence_h1_id: H1 证据 ID
        evidence_q1_id: Q1 证据 ID
        tolerance: 相对容差（默认 0.5%）

    Returns:
        DerivedValue with formula "H1 - Q1 = Q2"
    """
    q2_standalone = cumulative_h1 - cumulative_q1
    return DerivedValue(
        formula="H1_cumulative - Q1_cumulative = Q2_standalone",
        input_values=[cumulative_h1, cumulative_q1],
        calculated_value=q2_standalone,
        evidence_ids=[evidence_h1_id, evidence_q1_id],
        tolerance=tolerance,
    )


def derive_q3_standalone(
    cumulative_9m: float, cumulative_h1: float,
    evidence_9m_id: str = "", evidence_h1_id: str = "",
    tolerance: float = 0.005,
) -> DerivedValue:
    """Q3 standalone = 前三季累计 - H1累计。

    Args:
        cumulative_9m: 前三季度累计值（三季报）
        cumulative_h1: 上半年累计值（H1）
    """
    q3_standalone = cumulative_9m - cumulative_h1
    return DerivedValue(
        formula="9M_cumulative - H1_cumulative = Q3_standalone",
        input_values=[cumulative_9m, cumulative_h1],
        calculated_value=q3_standalone,
        evidence_ids=[evidence_9m_id, evidence_h1_id],
        tolerance=tolerance,
    )


def periods_compatible(claim_period: PeriodContext, evidence_period: PeriodContext) -> tuple[bool, str]:
    """判断 claim 期间与 evidence 期间是否兼容。

    规则：
    - 年度与年度兼容；
    - 季度与同季度兼容（需 standalone vs cumulative 一致）；
    - Q2 standalone 不能直接用 H1 cumulative 匹配（需推导后才能匹配）；
    - 上年同期不与本期兼容（用于同比基期，非直接匹配）。
    """
    # 期间类型不同
    if claim_period.document_type != evidence_period.document_type:
        # 年度 vs 季度不兼容
        if (claim_period.is_annual and not evidence_period.is_annual) or \
           (not claim_period.is_annual and evidence_period.is_annual):
            return False, f"document_type 不兼容：claim={claim_period.document_type} ev={evidence_period.document_type}"

    # 季度不同
    if claim_period.fiscal_quarter and evidence_period.fiscal_quarter:
        if claim_period.fiscal_quarter != evidence_period.fiscal_quarter:
            return False, f"quarter 不兼容：claim=Q{claim_period.fiscal_quarter} ev=Q{evidence_period.fiscal_quarter}"

    # standalone vs cumulative 不兼容（Q2 standalone 不能直接用 H1 cumulative）
    if claim_period.is_standalone and evidence_period.is_cumulative:
        return False, f"claim 为 standalone 但 evidence 为 cumulative（需推导后才能匹配）"

    # 年份不同
    if claim_period.fiscal_year and evidence_period.fiscal_year:
        if claim_period.fiscal_year != evidence_period.fiscal_year:
            return False, f"year 不兼容：claim={claim_period.fiscal_year} ev={evidence_period.fiscal_year}"

    return True, "期间兼容"


__all__ = [
    "PeriodContext",
    "DerivedValue",
    "parse_period",
    "derive_standalone_quarter",
    "derive_q3_standalone",
    "periods_compatible",
]

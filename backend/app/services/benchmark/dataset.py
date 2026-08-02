"""Benchmark Dataset（Phase 11）：金融 AI 可信度评测数据集。

支持：
- BenchmarkCase 载与读
- 50 条预置金融测试案例（覆盖 6 类错误）
- Dataset 错误分布统计

预置案例覆盖（任务书 §2 + §7）：
- FINANCIAL_ERROR        财务数据错误
- PERIOD_ERROR           期间错误
- GROWTH_ERROR           增长逻辑错误
- SEMANTIC_OVERSTATEMENT 语义夸大
- COMPETITIVE_CLAIM      竞争优势主张缺证据
- CAUSAL_ERROR           因果归因错误

Evidence First：每条案例的 gold_evidence 必须可追溯（source/text）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.benchmark import BenchmarkCaseRow
from app.services.benchmark.schemas import (
    ERROR_CAUSAL_ERROR,
    ERROR_COMPETITIVE_CLAIM,
    ERROR_FINANCIAL_ERROR,
    ERROR_GROWTH_ERROR,
    ERROR_LABELS,
    ERROR_PERIOD_ERROR,
    ERROR_SEMANTIC_OVERSTATEMENT,
    ERROR_TYPES,
    BenchmarkCase,
)


# ---------------------------------------------------------------------------
# 50 条预置金融测试案例
# ---------------------------------------------------------------------------
# 每条案例：AI 生成的金融主张（含错）+ 金标准证据 + 金标准结论
# 公司样本：美的集团 / 格力电器 / 海尔智家 / 贵州茅台 / 比亚迪 / 宁德时代
# ---------------------------------------------------------------------------
def _build_seed_cases() -> list[BenchmarkCase]:
    """构造 50 条预置金融测试案例（覆盖 6 类错误，约各 8-9 条）。"""
    cases: list[BenchmarkCase] = []

    # 辅助构造器
    def make(
        idx: int,
        claim: str,
        category: str,
        company: str,
        gold_result: str,
        gold_risk_score: float,
        risk_type: str,
        evidence: list[dict],
        stock_code: str = "",
        report_period: str = "2025FY",
        is_error: bool = True,
    ) -> BenchmarkCase:
        return BenchmarkCase(
            case_id=f"CASE-{idx:04d}",
            claim=claim,
            category=category,
            company=company,
            stock_code=stock_code,
            report_period=report_period,
            gold_evidence=evidence,
            gold_result=gold_result,
            gold_risk_score=gold_risk_score,
            risk_type=risk_type,
            is_error_case=is_error,
            metadata={"seed": True},
        )

    # ---- FINANCIAL_ERROR（财务数据错误）8 条 ----
    fin_err_evidence = [
        {"source": "FINANCIAL_REPORT", "text": "公司2025年实现营业收入4564.52亿元。", "page": 1},
    ]
    cases.extend([
        make(1, "美的集团2025年营业收入5000亿元", ERROR_FINANCIAL_ERROR, "美的集团",
            "REFUTED", 85.0, "FINANCIAL_ERROR", fin_err_evidence, "000333"),
        make(2, "美的集团归母净利润439.45亿元，同比下降38%", ERROR_FINANCIAL_ERROR, "美的集团",
            "REFUTED", 80.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "归母净利润439.45亿元，同比增长38.02%。", "page": 2}],
            "000333"),
        make(3, "格力电器2025年营收超3000亿元", ERROR_FINANCIAL_ERROR, "格力电器",
            "REFUTED", 75.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "格力电器2025年营业收入2056.40亿元。", "page": 1}],
            "000651"),
        make(4, "海尔智家毛利率高达50%", ERROR_FINANCIAL_ERROR, "海尔智家",
            "REFUTED", 78.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "海尔智家毛利率30.5%。", "page": 3}],
            "600690"),
        make(5, "贵州茅台2025年营收1000亿元", ERROR_FINANCIAL_ERROR, "贵州茅台",
            "REFUTED", 76.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "贵州茅台2025年营业收入1743.58亿元。", "page": 1}],
            "600519"),
        make(6, "比亚迪净利润亏损100亿元", ERROR_FINANCIAL_ERROR, "比亚迪",
            "REFUTED", 82.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "比亚迪归母净利润161.46亿元，同比增长44%。", "page": 2}],
            "002594"),
        make(7, "宁德时代研发费用仅1亿元", ERROR_FINANCIAL_ERROR, "宁德时代",
            "REFUTED", 74.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "宁德时代研发费用186.10亿元。", "page": 4}],
            "300750"),
        make(8, "美的集团经营性现金流为负", ERROR_FINANCIAL_ERROR, "美的集团",
            "REFUTED", 77.0, "FINANCIAL_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "经营活动产生的现金流量净额389.16亿元。", "page": 5}],
            "000333"),
    ])

    # ---- PERIOD_ERROR（期间错误）8 条 ----
    period_err_evidence = [
        {"source": "FINANCIAL_REPORT", "text": "公司2024年营业收入3591.61亿元。", "page": 1},
    ]
    cases.extend([
        make(9, "美的集团2024年营业收入4564.52亿元", ERROR_PERIOD_ERROR, "美的集团",
            "REFUTED", 70.0, "PERIOD_ERROR", period_err_evidence, "000333", "2024FY"),
        make(10, "格力电器2025年三季度营收超2000亿", ERROR_PERIOD_ERROR, "格力电器",
            "REFUTED", 68.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "格力电器2025年三季度营收1456.20亿元。", "page": 2}],
            "000651", "2025Q3"),
        make(11, "比亚迪2024年销量300万辆", ERROR_PERIOD_ERROR, "比亚迪",
            "REFUTED", 66.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "比亚迪2024年销量427.2万辆。", "page": 1}],
            "002594", "2024FY"),
        make(12, "贵州茅台2025H1净利润800亿元", ERROR_PERIOD_ERROR, "贵州茅台",
            "REFUTED", 72.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "贵州茅台2025H1归母净利润544.79亿元。", "page": 2}],
            "600519", "2025H1"),
        make(13, "宁德时代2025年研发费用同比下降", ERROR_PERIOD_ERROR, "宁德时代",
            "REFUTED", 64.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "研发费用同比增长15%。", "page": 4}],
            "300750", "2025FY"),
        make(14, "海尔智家2025Q1毛利率20%", ERROR_PERIOD_ERROR, "海尔智家",
            "REFUTED", 62.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "海尔智家2025Q1毛利率28.5%。", "page": 3}],
            "600690", "2025Q1"),
        make(15, "美的集团2023年海外业务占比50%", ERROR_PERIOD_ERROR, "美的集团",
            "REFUTED", 65.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "2023年海外业务占比40.5%。", "page": 6}],
            "000333", "2023FY"),
        make(16, "格力电器2024年归母净利润500亿元", ERROR_PERIOD_ERROR, "格力电器",
            "REFUTED", 67.0, "PERIOD_ERROR",
            [{"source": "FINANCIAL_REPORT", "text": "格力电器2024年归母净利润321.84亿元。", "page": 2}],
            "000651", "2024FY"),
    ])

    # ---- GROWTH_ERROR（增长逻辑错误）9 条 ----
    growth_evidence = [
        {"source": "FINANCIAL_REPORT", "text": "海外业务同比增长12%，低于公司整体增速。", "page": 6},
    ]
    cases.extend([
        make(17, "美的集团海外业务高速增长，增速超50%", ERROR_GROWTH_ERROR, "美的集团",
            "REFUTED", 60.0, "EVIDENCE_RISK", growth_evidence, "000333"),
        make(18, "格力电器海外业务已成利润核心引擎", ERROR_GROWTH_ERROR, "格力电器",
            "PARTIALLY_SUPPORTED", 55.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "海外业务占比22%，尚低于国内。", "page": 5}],
            "000651"),
        make(19, "比亚迪新能源车业务必将翻倍", ERROR_GROWTH_ERROR, "比亚迪",
            "REFUTED", 60.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "新能源车销量同比增长44%，未翻倍。", "page": 2}],
            "002594"),
        make(20, "宁德时代储能业务持续高速增长", ERROR_GROWTH_ERROR, "宁德时代",
            "INSUFFICIENT_EVIDENCE", 50.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "储能业务数据未单独披露。", "page": 4}],
            "300750"),
        make(21, "海尔智家海外业务保持三位数增长", ERROR_GROWTH_ERROR, "海尔智家",
            "REFUTED", 62.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "海外业务同比增长15%。", "page": 3}],
            "600690"),
        make(22, "贵州茅台销量将年均增长30%", ERROR_GROWTH_ERROR, "贵州茅台",
            "REFUTED", 58.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "近三年销量年均增长7%。", "page": 2}],
            "600519"),
        make(23, "美的集团机器人业务高速增长超80%", ERROR_GROWTH_ERROR, "美的集团",
            "REFUTED", 60.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "机器人业务增长18%。", "page": 6}],
            "000333"),
        make(24, "比亚迪电池业务将成为全球第一", ERROR_GROWTH_ERROR, "比亚迪",
            "PARTIALLY_SUPPORTED", 55.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "电池业务份额尚落后于宁德时代。", "page": 3}],
            "002594"),
        make(25, "格力电器智能装备业务高速增长", ERROR_GROWTH_ERROR, "格力电器",
            "INSUFFICIENT_EVIDENCE", 50.0, "EVIDENCE_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "智能装备业务数据未披露。", "page": 5}],
            "000651"),
    ])

    # ---- SEMANTIC_OVERSTATEMENT（语义夸大）8 条 ----
    cases.extend([
        make(26, "美的集团是唯一遥遥领先的家电龙头", ERROR_SEMANTIC_OVERSTATEMENT, "美的集团",
            "REFUTED", 65.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "市场份额显示海尔/格力同样具备竞争力。", "page": None}],
            "000333"),
        make(27, "格力电器是空调行业无可争议的绝对霸主", ERROR_SEMANTIC_OVERSTATEMENT, "格力电器",
            "REFUTED", 70.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "空调市场份额格力38%，美的36%，并非无可争议。", "page": None}],
            "000651"),
        make(28, "比亚迪是世界第一的新能源车企", ERROR_SEMANTIC_OVERSTATEMENT, "比亚迪",
            "PARTIALLY_SUPPORTED", 60.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "比亚迪新能源车销量全球第一，但'世界第一'含绝对化。", "page": None}],
            "002594"),
        make(29, "宁德时代独占全球动力电池市场", ERROR_SEMANTIC_OVERSTATEMENT, "宁德时代",
            "REFUTED", 68.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "宁德时代份额37%，并非独占。", "page": None}],
            "300750"),
        make(30, "贵州茅台是全球最赚钱的白酒公司", ERROR_SEMANTIC_OVERSTATEMENT, "贵州茅台",
            "PARTIALLY_SUPPORTED", 55.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "茅台净利润领先，但'最赚钱'含绝对化。", "page": None}],
            "600519"),
        make(31, "海尔智家是智能家居的顶级领跑者", ERROR_SEMANTIC_OVERSTATEMENT, "海尔智家",
            "REFUTED", 62.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "智能家居竞争激烈，多家厂商并列。", "page": None}],
            "600690"),
        make(32, "美的集团拥有全球最强的家电研发能力", ERROR_SEMANTIC_OVERSTATEMENT, "美的集团",
            "REFUTED", 66.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "研发投入排名显示多家可比。", "page": None}],
            "000333"),
        make(33, "格力电器空调技术全球唯一", ERROR_SEMANTIC_OVERSTATEMENT, "格力电器",
            "REFUTED", 67.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "多家公司具备可比空调技术。", "page": None}],
            "000651"),
    ])

    # ---- COMPETITIVE_CLAIM（竞争优势主张缺证据）8 条 ----
    cases.extend([
        make(34, "美的集团保持行业领先地位", ERROR_COMPETITIVE_CLAIM, "美的集团",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到市场份额/排名强证据。", "page": None}],
            "000333"),
        make(35, "格力电器在空调领域占据龙头", ERROR_COMPETITIVE_CLAIM, "格力电器",
            "PARTIALLY_SUPPORTED", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "空调份额格力38%，但口径模糊。", "page": None}],
            "000651"),
        make(36, "比亚迪在新能源车市场保持领先", ERROR_COMPETITIVE_CLAIM, "比亚迪",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到出货量/排名强证据。", "page": None}],
            "002594"),
        make(37, "宁德时代在动力电池领域保持第一", ERROR_COMPETITIVE_CLAIM, "宁德时代",
            "PARTIALLY_SUPPORTED", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "份额37%，但口径模糊。", "page": None}],
            "300750"),
        make(38, "贵州茅台在高端白酒市场保持优势", ERROR_COMPETITIVE_CLAIM, "贵州茅台",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到市场份额强证据。", "page": None}],
            "600519"),
        make(39, "海尔智家在智能家居领域保持领先", ERROR_COMPETITIVE_CLAIM, "海尔智家",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到排名强证据。", "page": None}],
            "600690"),
        make(40, "美的集团在机器人业务具备头部优势", ERROR_COMPETITIVE_CLAIM, "美的集团",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到机器人业务排名证据。", "page": None}],
            "000333"),
        make(41, "格力电器在智能装备领域保持领先", ERROR_COMPETITIVE_CLAIM, "格力电器",
            "INSUFFICIENT_EVIDENCE", 55.0, "EVIDENCE_RISK",
            [{"source": "NEWS", "text": "未检索到智能装备排名证据。", "page": None}],
            "000651"),
    ])

    # ---- CAUSAL_ERROR（因果归因错误）9 条 ----
    cases.extend([
        make(42, "美的集团利润增长完全由海外业务驱动", ERROR_CAUSAL_ERROR, "美的集团",
            "REFUTED", 70.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "利润增长由多业务分部共同贡献，非单一驱动。", "page": 6}],
            "000333"),
        make(43, "比亚迪销量增长导致净利润翻倍", ERROR_CAUSAL_ERROR, "比亚迪",
            "REFUTED", 68.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "销量增长44%，净利润增长44%，未翻倍。", "page": 2}],
            "002594"),
        make(44, "宁德时代研发投入直接导致市占率提升", ERROR_CAUSAL_ERROR, "宁德时代",
            "PARTIALLY_SUPPORTED", 60.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "研发与市占率相关，但非单一直接因果。", "page": 4}],
            "300750"),
        make(45, "贵州茅台提价必然导致销量增长", ERROR_CAUSAL_ERROR, "贵州茅台",
            "REFUTED", 65.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "提价与销量无必然正相关。", "page": 2}],
            "600519"),
        make(46, "海尔智家海外扩张是利润增长唯一原因", ERROR_CAUSAL_ERROR, "海尔智家",
            "REFUTED", 68.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "利润增长由多因素贡献。", "page": 3}],
            "600690"),
        make(47, "格力电器空调份额提升因为价格战", ERROR_CAUSAL_ERROR, "格力电器",
            "PARTIALLY_SUPPORTED", 60.0, "SEMANTIC_RISK",
            [{"source": "NEWS", "text": "份额提升因素多元，价格战非唯一原因。", "page": None}],
            "000651"),
        make(48, "美的集团机器人业务亏损因为研发投入", ERROR_CAUSAL_ERROR, "美的集团",
            "REFUTED", 65.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "机器人业务亏损原因多元。", "page": 6}],
            "000333"),
        make(49, "比亚迪电池业务增长因为车业务", ERROR_CAUSAL_ERROR, "比亚迪",
            "PARTIALLY_SUPPORTED", 58.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "电池业务增长与车业务相关但非单一因果。", "page": 3}],
            "002594"),
        make(50, "宁德时代储能业务增长因为政策", ERROR_CAUSAL_ERROR, "宁德时代",
            "INSUFFICIENT_EVIDENCE", 55.0, "SEMANTIC_RISK",
            [{"source": "FINANCIAL_REPORT", "text": "储能业务增长因果未单独披露。", "page": 4}],
            "300750"),
    ])

    # 加 1 条"正确案例"作为对照（is_error_case=False），验证不误报
    cases.append(
        make(51, "美的集团2025年实现营业收入4564.52亿元，同比增长12.11%", ERROR_FINANCIAL_ERROR,
            "美的集团", "SUPPORTED", 0.0, "NONE",
            [{"source": "FINANCIAL_REPORT", "text": "公司2025年实现营业收入4564.52亿元，同比增长12.11%。", "page": 1}],
            "000333", is_error=False)
    )

    return cases


SEED_CASES: list[BenchmarkCase] = _build_seed_cases()


# ---------------------------------------------------------------------------
# Dataset 载与读
# ---------------------------------------------------------------------------
def get_seed_cases() -> list[BenchmarkCase]:
    """返回 50 条预置金融测试案例（+ 1 条正确对照）。"""
    return list(SEED_CASES)


def get_error_distribution(cases: Iterable[BenchmarkCase]) -> dict[str, int]:
    """统计案例的错误类型分布。"""
    dist: dict[str, int] = {}
    for c in cases:
        dist[c.category] = dist.get(c.category, 0) + 1
    return dist


def validate_case(case: BenchmarkCase) -> list[str]:
    """校验案例完整性；返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    if not case.claim:
        errors.append("claim 缺失")
    if case.category not in ERROR_TYPES:
        errors.append(f"category 非法: {case.category}")
    if case.gold_result not in {"REFUTED", "PARTIALLY_SUPPORTED", "SUPPORTED", "INSUFFICIENT_EVIDENCE"}:
        errors.append(f"gold_result 非法: {case.gold_result}")
    if not case.gold_evidence:
        errors.append("gold_evidence 缺失（Evidence First）")
    return errors


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def seed_dataset(session: Session, dataset_name: str = "finproof_seed_v1") -> int:
    """将预置案例写入 benchmark_cases 表，返回写入条数。"""
    count = 0
    for case in SEED_CASES:
        row = BenchmarkCaseRow(
            case_id=case.case_id,
            dataset_name=dataset_name,
            claim=case.claim,
            category=case.category,
            company=case.company,
            stock_code=case.stock_code,
            report_period=case.report_period,
            gold_evidence_json=json.dumps(case.gold_evidence, ensure_ascii=False),
            gold_result=case.gold_result,
            gold_risk_score=case.gold_risk_score,
            risk_type=case.risk_type,
            is_error_case=case.is_error_case,
            metadata_json=json.dumps(case.metadata, ensure_ascii=False),
        )
        session.add(row)
        count += 1
    session.commit()
    return count


def load_dataset(
    session: Session,
    dataset_name: str | None = None,
) -> list[BenchmarkCase]:
    """从 benchmark_cases 表读取案例。"""
    query = session.query(BenchmarkCaseRow)
    if dataset_name is not None:
        query = query.filter(BenchmarkCaseRow.dataset_name == dataset_name)
    rows = query.order_by(BenchmarkCaseRow.id).all()

    cases: list[BenchmarkCase] = []
    for row in rows:
        gold_evidence = json.loads(row.gold_evidence_json) if row.gold_evidence_json else []
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
        cases.append(
            BenchmarkCase(
                case_id=row.case_id,
                claim=row.claim,
                category=row.category,
                company=row.company,
                stock_code=row.stock_code or "",
                report_period=row.report_period or "",
                gold_evidence=gold_evidence,
                gold_result=row.gold_result,
                gold_risk_score=row.gold_risk_score or 0.0,
                risk_type=row.risk_type or "",
                is_error_case=row.is_error_case,
                metadata=metadata,
            )
        )
    return cases


def count_cases(session: Session, dataset_name: str | None = None) -> int:
    """统计案例数量。"""
    query = session.query(BenchmarkCaseRow)
    if dataset_name is not None:
        query = query.filter(BenchmarkCaseRow.dataset_name == dataset_name)
    return query.count()


__all__ = [
    "SEED_CASES",
    "get_seed_cases",
    "get_error_distribution",
    "validate_case",
    "seed_dataset",
    "load_dataset",
    "count_cases",
]

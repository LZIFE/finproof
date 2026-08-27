"""来源风险检测：在事实核验之外，识别"信息来源层面"的四类问题。

四类风险：
1. FORECAST_AS_FACT  预测当事实——主张是确定性陈述，但证据原文是预测
2. SINGLE_SOURCE     孤证——只有一条弱来源证据就下结论
3. OUTDATED_DATA     数据过时——引用的披露期间不是最新可用披露
4. SELECTIVE_CITATION 选择性引用——同批候选里存在与主张方向相反的证据被忽略

设计原则：纯规则、可解释、不改变核验判定（只附加风险标签）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import SourceLevel

# 弱来源等级（孤证判定用）
_WEAK_LEVELS = {
    SourceLevel.CHANNEL_CHECK,
    SourceLevel.MEDIA_REPORT,
    SourceLevel.NO_SOURCE,
    SourceLevel.FORECAST,
}

# 主张中的预测词（如果主张本身含这些词，则不算"预测当事实"）
_FORECAST_MARKERS = (
    "预计", "有望", "估计", "预测", "预期", "计划", "拟",
    "力争", "目标", "展望", "未来将", "forecast", "expect",
)

# 正面方向词（选择性引用判定用）
_POSITIVE_MARKERS = (
    "增长", "提升", "突破", "上涨", "增加", "改善", "强劲",
    "超预期", "向好", "回升", "扩张", "创新高", "增长",
)
# 负面方向词
_NEGATIVE_MARKERS = (
    "下降", "减少", "下滑", "下跌", "降低", "恶化", "疲软",
    "不及预期", "回落", "收缩", "亏损", "减少", "下降",
)


def _claim_is_forecast(claim_text: str) -> bool:
    """主张本身是否为预测性陈述。"""
    return any(kw in claim_text for kw in _FORECAST_MARKERS)


def _direction(text: str) -> str:
    """简单判断文本方向：positive / negative / neutral。"""
    pos = sum(1 for kw in _POSITIVE_MARKERS if kw in text)
    neg = sum(1 for kw in _NEGATIVE_MARKERS if kw in text)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def detect_forecast_as_fact(
    claim_text: str,
    selected: list[dict],
) -> dict | None:
    """预测当事实：主张是确定性陈述，但证据来源是预测性表述。"""
    if _claim_is_forecast(claim_text):
        return None  # 主张自己就说了"预计"，不算误导

    forecast_ev = [
        e for e in selected
        if e.get("source_level") == SourceLevel.FORECAST
    ]
    if not forecast_ev:
        return None

    sample = (forecast_ev[0].get("text") or "")[:80]
    return {
        "tag": "FORECAST_AS_FACT",
        "label": "预测当事实",
        "severity": "HIGH",
        "detail": (
            f"主张以确定性语气陈述，但匹配的 {len(forecast_ev)} 条证据原文含预测性表述"
            f"（如「预计/有望」），并非已发生事实。证据片段：{sample}…"
        ),
    }


def detect_single_source(selected: list[dict]) -> dict | None:
    """孤证：仅一条证据且来源不够硬。"""
    if len(selected) != 1:
        return None

    ev = selected[0]
    level = ev.get("source_level", SourceLevel.NO_SOURCE)
    if level not in _WEAK_LEVELS:
        return None  # 官方披露的孤证可以接受

    level_label = {
        SourceLevel.CHANNEL_CHECK: "渠道调研",
        SourceLevel.MEDIA_REPORT: "媒体报道",
        SourceLevel.FORECAST: "预测陈述",
        SourceLevel.NO_SOURCE: "无明确来源",
    }.get(level, "弱来源")

    return {
        "tag": "SINGLE_SOURCE",
        "label": "孤证",
        "severity": "MEDIUM",
        "detail": (
            f"结论仅依赖 1 条证据，且来源为「{level_label}」，"
            "缺乏独立旁证交叉验证，可靠性有限。"
        ),
    }


def detect_outdated_data(
    claim: dict,
    selected: list[dict],
    session: Session | None = None,
) -> dict | None:
    """数据过时：证据来自的报告期间早于同公司最新可用披露。"""
    if session is None or not selected:
        return None

    from app.models import Document

    company = claim.get("entity_name") or claim.get("entity")
    if not company:
        return None

    # 收集被选证据引用的文档期间
    evidence_periods = {
        e.get("doc_period") for e in selected if e.get("doc_period")
    }
    if not evidence_periods:
        return None

    # 查同公司最新的官方披露文档期间
    latest_doc = (
        session.query(Document)
        .filter(
            Document.company_name == company,
            Document.document_role == "SOURCE_DOCUMENT",
            Document.parse_status == "COMPLETED",
        )
        .order_by(Document.publication_date.desc().nullslast())
        .first()
    )
    if latest_doc is None or not latest_doc.report_period:
        return None

    latest_period = latest_doc.report_period
    # 如果证据期间都不是最新的，标记过时
    if latest_period not in evidence_periods:
        old_periods = "、".join(sorted(evidence_periods))
        return {
            "tag": "OUTDATED_DATA",
            "label": "数据过时",
            "severity": "MEDIUM",
            "detail": (
                f"证据引用的报告期间为 {old_periods}，"
                f"但该公司已有更新的披露（{latest_period}），"
                "建议核对最新数据后再下结论。"
            ),
        }
    return None


def detect_selective_citation(
    claim_text: str,
    selected: list[dict],
    candidates: list[dict],
    selected_ids: set,
) -> dict | None:
    """选择性引用：候选池里存在与主张方向相反的证据，但未被选用。"""
    claim_dir = _direction(claim_text)
    if claim_dir == "neutral":
        return None

    opposite_dir = "negative" if claim_dir == "positive" else "positive"

    # 在未被选中的候选里找方向相反、且有一定相关度的块
    counter_evidence = []
    for c in candidates:
        cid = c.get("evidence_id") or c.get("block_id")
        if cid in selected_ids:
            continue
        text = c.get("text") or c.get("block_text") or ""
        if not text or _direction(text) != opposite_dir:
            continue
        # 只关注相关度不太低的候选（final_score > 0.3）
        score = c.get("final_score", c.get("final_quality_score", 0))
        if score and float(score) >= 0.3:
            counter_evidence.append(text[:80])

    if not counter_evidence:
        return None

    return {
        "tag": "SELECTIVE_CITATION",
        "label": "选择性引用",
        "severity": "HIGH",
        "detail": (
            f"主张方向为「{('正面' if claim_dir == 'positive' else '负面')}」，"
            f"但检索到 {len(counter_evidence)} 条方向相反的相关证据未被采用，"
            f"可能存在选择性引用。反面证据片段：{counter_evidence[0]}…"
        ),
    }


def detect_source_risks(
    claim: dict,
    candidates: list[dict],
    selected_ids: list | set | None = None,
    session: Session | None = None,
) -> list[dict]:
    """对一条主张的核验结果执行全部四类来源风险检测。

    参数:
        claim: 主张字典（含 original_text / entity_name 等）
        candidates: 经过 Gate/Selector 后的候选证据列表（含 source_level）
        selected_ids: 被选中采用的证据 id 集合；None 时视为全部 candidates 都被选中
        session: 数据库会话（用于过时数据检测，可选）

    返回:
        风险标签列表，每项 {tag, label, severity, detail}
    """
    claim_text = claim.get("original_text") or claim.get("claim_text") or ""

    if selected_ids is None:
        selected = list(candidates)
        selected_set = {
            e.get("evidence_id") or e.get("block_id") for e in selected
        }
    else:
        selected_set = set(selected_ids)
        selected = [
            e for e in candidates
            if (e.get("evidence_id") or e.get("block_id")) in selected_set
        ]

    risks: list[dict] = []

    r = detect_forecast_as_fact(claim_text, selected)
    if r:
        risks.append(r)

    r = detect_single_source(selected)
    if r:
        risks.append(r)

    r = detect_outdated_data(claim, selected, session)
    if r:
        risks.append(r)

    r = detect_selective_citation(claim_text, selected, candidates, selected_set)
    if r:
        risks.append(r)

    return risks

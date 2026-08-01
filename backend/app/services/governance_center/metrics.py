"""FinProof Governance Center Metrics Aggregators（Phase 20）。

聚合 Phase 0-19 既有 ORM 行 → 治理层指标。**不做新业务**，仅 SELECT 已有表。
保持 Evidence First；不输出投资建议。
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.governance_center.schemas import (
    AgentPerformance,
    AuditEvent,
    AuditTimeline,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    IntelligenceOverview,
    ReliabilityScore,
    RiskItem,
    RiskMonitoring,
    risk_level_of,
)


# ---------------------------------------------------------------------------
# 1. AI Reliability Score（来源：Benchmark / Red Team / Arena）
# ---------------------------------------------------------------------------
def aggregate_reliability(session: Session) -> ReliabilityScore:
    """从 Benchmark / Red Team / Arena 聚合 AI 可靠性评分。"""
    rs = ReliabilityScore()

    # Benchmark：准确率 / 风险检出率 / 证据覆盖率
    try:
        from app.models.benchmark import BenchmarkResultRow, BenchmarkRunRow
        bench_runs = session.query(BenchmarkRunRow).count() or 0
        if bench_runs:
            rows = session.query(BenchmarkResultRow).all()
            acc = _safe_avg([r.accuracy for r in rows if r.accuracy is not None])
            ec = _safe_avg([r.evidence_coverage for r in rows if r.evidence_coverage is not None])
            rdr = _safe_avg([r.risk_detection_rate for r in rows if r.risk_detection_rate is not None])
            rs.benchmark_accuracy = acc
            rs.evidence_coverage = ec
            rs.risk_detection_rate = rdr
            rs.samples += bench_runs
    except Exception:  # noqa: BLE001
        pass

    # Red Team：幻觉检出率 / 可靠性评分
    try:
        from app.models.red_team import RedTeamRunRow
        rt_rows = session.query(RedTeamRunRow).all()
        if rt_rows:
            hdr = _safe_avg([r.hallucination_detection_rate for r in rt_rows if r.hallucination_detection_rate is not None])
            rel = _safe_avg([r.reliability_score for r in rt_rows if r.reliability_score is not None])
            rs.hallucination_detection_rate = hdr
            rs.red_team_reliability = rel
            rs.samples += len(rt_rows)
    except Exception:  # noqa: BLE001
        pass

    # Arena：Final Arena Score + reasoning accuracy（取自 Auditor logical_consistency）
    try:
        from app.models.agent_arena import ArenaResultRow
        ar_rows = session.query(ArenaResultRow).all()
        if ar_rows:
            scores = [r.final_arena_score for r in ar_rows if r.final_arena_score is not None]
            rs.arena_score = _safe_avg(scores)
            rs.reasoning_accuracy = min(1.0, rs.arena_score / 100.0)  # 近似：Arena Score → reasoning
            rs.samples += len(ar_rows)
    except Exception:  # noqa: BLE001
        pass

    # overall reliability = 4 项加权（benchmark / red_team / arena / evidence_coverage）
    rs.overall_reliability = _safe_avg([
        rs.benchmark_accuracy,
        rs.red_team_reliability,
        rs.arena_score,
        rs.evidence_coverage * 100.0,
    ])
    return rs


# ---------------------------------------------------------------------------
# 2. Investment Intelligence Overview（来源：Research Agent / Memo / Committee）
# ---------------------------------------------------------------------------
def aggregate_intelligence(session: Session) -> IntelligenceOverview:
    """从 Research Agent / Memo / Committee 聚合情报概览。"""
    ov = IntelligenceOverview()

    try:
        from app.models.research_agent import ResearchSessionRow, ResearchTaskRow
        sessions = session.query(ResearchSessionRow).all()
        ov.research_sessions = len(sessions)
        companies = [s.company for s in sessions if s.company]
        ov.companies_analyzed = len(set(companies))
        # memos_generated ≈ 已完成阶段（phase）的 session
        ov.memos_generated = sum(1 for s in sessions if getattr(s, "phase", "") == "Done")
        # claims_verified ≈ 完成的 tasks
        ov.claims_verified = session.query(ResearchTaskRow).filter(ResearchTaskRow.status == "Done").count() or 0
        # top companies（跳过空公司）
        cnt = Counter(companies)
        ov.top_companies = [
            {"company": c, "sessions": n}
            for c, n in cnt.most_common(5)
            if c
        ]
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models.investment_committee import InvestmentCommitteeRunRow
        ov.committee_runs = session.query(InvestmentCommitteeRunRow).count() or 0
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models.risk import RiskReportRow
        ov.risk_findings = session.query(RiskReportRow).count() or 0
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models.evidence import EvidenceRow
        ov.evidence_chains = session.query(EvidenceRow).count() or 0
    except Exception:  # noqa: BLE001
        pass

    return ov


# ---------------------------------------------------------------------------
# 3. AI Risk Monitoring（来源：Risk Engine / Monitoring / Governance）
# ---------------------------------------------------------------------------
def aggregate_risk_monitoring(session: Session) -> RiskMonitoring:
    """从 Risk Engine / Monitoring 聚合风险监控。"""
    rm = RiskMonitoring()

    # Risk Engine：当前风险条目
    try:
        from app.models.risk import RiskReportRow
        rows = session.query(RiskReportRow).order_by(RiskReportRow.id.desc()).limit(50).all()
        rm.total_risks = session.query(RiskReportRow).count() or 0
        for r in rows[:20]:
            score = float(getattr(r, "risk_score", 0.0) or 0.0)
            rm.current_risks.append(RiskItem(
                risk_id=f"RISK-{r.id}",
                company=getattr(r, "company", "") or "",
                risk_type=getattr(r, "risk_type", "") or "",
                level=risk_level_of(score),
                description=getattr(r, "summary", "") or getattr(r, "description", "") or "",
                status=getattr(r, "status", "OPEN") or "OPEN",
                evidence_count=getattr(r, "evidence_count", 0) or 0,
                detected_at=getattr(r, "created_at", ""),
            ))
    except Exception:  # noqa: BLE001
        pass

    # Monitoring：未决评审 / alerts
    try:
        from app.models.monitoring import MonitoringAlertRow
        rm.monitoring_alerts = session.query(MonitoringAlertRow).count() or 0
        rm.unresolved_reviews = session.query(MonitoringAlertRow).filter(MonitoringAlertRow.status == "OPEN").count() or 0
    except Exception:  # noqa: BLE001
        pass

    # 历史变化：近 7 日每日风险数
    try:
        from app.models.risk import RiskReportRow
        since = datetime.utcnow() - timedelta(days=7)
        rows = session.query(RiskReportRow).filter(RiskReportRow.created_at >= since).all()
        hist: dict[str, int] = {}
        for r in rows:
            d = (getattr(r, "created_at", None) or datetime.utcnow()).strftime("%Y-%m-%d")
            hist[d] = hist.get(d, 0) + 1
        rm.historical_change = dict(sorted(hist.items()))
    except Exception:  # noqa: BLE001
        pass

    return rm


# ---------------------------------------------------------------------------
# 4. Agent Performance（来源：Arena / Simulation）
# ---------------------------------------------------------------------------
def aggregate_agent_performance(session: Session) -> AgentPerformance:
    """从 Arena / Simulation 聚合 Agent 性能。"""
    ap = AgentPerformance()

    # Arena
    try:
        from app.models.agent_arena import ArenaResultRow
        rows = session.query(ArenaResultRow).all()
        ap.arena_runs = len(rows)
        if rows:
            ap.analyst_performance = _safe_avg([r.final_arena_score for r in rows if r.final_arena_score is not None])
            winners = Counter((r.winner or "tie") for r in rows)
            ap.winner_distribution = dict(winners)
            # Skeptic detection rate ≈ skeptic wins / total
            ap.skeptic_detection_rate = (winners.get("skeptic", 0) + winners.get("tie", 0) * 0.5) / max(1, len(rows))
            # Auditor accuracy ≈ arena_score / 100
            ap.auditor_accuracy = min(1.0, ap.analyst_performance / 100.0)
    except Exception:  # noqa: BLE001
        pass

    # Simulation
    try:
        from app.models.financial_simulation import SimulationResultRow, SimulationRunRow
        sim_rows = session.query(SimulationRunRow).all()
        ap.simulation_runs = len(sim_rows)
        res_rows = session.query(SimulationResultRow).all()
        if res_rows:
            ap.fin_agent_score_mean = _safe_avg([r.fin_agent_score for r in res_rows if r.fin_agent_score is not None])
    except Exception:  # noqa: BLE001
        pass

    # 综合 Agent score = (Arena + Simulation) / 2
    ap.agent_score = _safe_avg([ap.analyst_performance, ap.fin_agent_score_mean])
    return ap


# ---------------------------------------------------------------------------
# 5. Evidence Graph（来源：Knowledge Graph）
# ---------------------------------------------------------------------------
def aggregate_evidence_graph(session: Session, limit: int = 100) -> EvidenceGraph:
    """从 Knowledge Graph 聚合证据图谱（节点 + 边）。"""
    eg = EvidenceGraph()
    try:
        from app.models.knowledge_graph import KGFactsRow, KGRelationshipRow
        # 节点：company / metric / business
        facts = session.query(KGFactsRow).limit(limit).all()
        nodes: list[EvidenceNode] = []
        edges: list[EvidenceEdge] = []
        companies: set[str] = set()
        metrics: set[str] = set()
        for f in facts:
            company = getattr(f, "company", "") or ""
            metric = getattr(f, "metric", "") or ""
            fact_id = f"fact-{f.id}"
            if company:
                companies.add(company)
                nodes.append(EvidenceNode(node_id=f"company-{company}", entity_type="company", label=company, weight=1))
                edges.append(EvidenceEdge(source=f"company-{company}", target=fact_id, relation="has_fact"))
            if metric:
                metrics.add(metric)
                nodes.append(EvidenceNode(node_id=f"metric-{metric}", entity_type="metric", label=metric, weight=1))
                edges.append(EvidenceEdge(source=fact_id, target=f"metric-{metric}", relation="about_metric"))
            nodes.append(EvidenceNode(node_id=fact_id, entity_type="evidence", label=(getattr(f, "fact_text", "") or "")[:60], weight=1))
        # 去重节点
        seen: set[str] = set()
        uniq_nodes: list[EvidenceNode] = []
        for n in nodes:
            if n.node_id in seen:
                continue
            seen.add(n.node_id)
            uniq_nodes.append(n)
        eg.nodes = uniq_nodes[:limit]
        eg.edges = edges[:limit]
        eg.companies = len(companies)
        eg.metrics = len(metrics)
        eg.evidence_count = len(facts)
    except Exception:  # noqa: BLE001
        pass
    return eg


# ---------------------------------------------------------------------------
# 6. Audit Timeline（来源：Audit Trail）
# ---------------------------------------------------------------------------
def aggregate_audit_timeline(session: Session, limit: int = 50) -> AuditTimeline:
    """从 Audit Trail 聚合审计时间线。"""
    tl = AuditTimeline()
    try:
        from app.models.audit_trail import AuditTrailRow
        rows = session.query(AuditTrailRow).order_by(AuditTrailRow.id.desc()).limit(limit).all()
        tl.total_events = session.query(AuditTrailRow).count() or 0
        users: set[str] = set()
        actions: set[str] = set()
        for r in rows:
            user = getattr(r, "user", "") or ""
            action = getattr(r, "action", "") or ""
            users.add(user)
            actions.add(action)
            tl.events.append(AuditEvent(
                event_id=f"EVT-{r.id}",
                user=user,
                action=action,
                timestamp=(getattr(r, "created_at", None) or datetime.utcnow()).isoformat(timespec="seconds") + "Z",
                model_version=getattr(r, "model_version", "") or "",
                rule_version=getattr(r, "rule_version", "") or "",
                evidence_used=getattr(r, "evidence_used", 0) or 0,
                detail=getattr(r, "detail", "") or "",
            ))
        tl.distinct_users = len(users)
        tl.distinct_actions = len(actions)
    except Exception:  # noqa: BLE001
        pass
    return tl


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _safe_avg(values: list[float]) -> float:
    """安全均值：空列表返回 0.0。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


__all__ = [
    "aggregate_reliability",
    "aggregate_intelligence",
    "aggregate_risk_monitoring",
    "aggregate_agent_performance",
    "aggregate_evidence_graph",
    "aggregate_audit_timeline",
]

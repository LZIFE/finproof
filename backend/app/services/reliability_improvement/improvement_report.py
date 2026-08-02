"""FinProof Improvement Report Generator（Phase 23，任务书 §生成）。

聚合 failures + patterns + trend → ReliabilityImprovementReport。
**不修改模型、不训练模型**，仅分析与建议。不输出投资建议。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.reliability_improvement.failure_analyzer import collect_failures
from app.services.reliability_improvement.pattern_detector import (
    PATTERN_IMPROVEMENT,
    build_weakness_map,
    detect_patterns,
)
from app.services.reliability_improvement.schemas import (
    FailureCase,
    PATTERN_TYPES,
    ReliabilityImprovementReport,
    ReliabilityTrend,
    TrendPoint,
    WeaknessMap,
    _now_iso,
    contains_forbidden_content,
)


def analyze_reliability(session: Session, limit: int = 200) -> ReliabilityImprovementReport:
    """生成 Reliability Improvement Report（任务书 §生成）。

    含：failure_count / failure_rate / affected_category / example_cases /
    root_cause / suggested_improvement（按模式）+ Reliability Trend。
    """
    failures, totals = collect_failures(session, limit=limit)
    patterns = detect_patterns(failures, totals)
    trend = _build_trend(session)
    weakness_map = build_weakness_map(failures)

    total_cases = sum(totals.values()) if totals else max(1, len(failures))
    total_failures = len(failures)
    # total_cases 至少等于 total_failures（每个失败案例本身就是被分析的一个案例；
    # 一条 Arena run 可产生多条挑战失败，行级计数会低估 case 数）
    if total_cases < total_failures:
        total_cases = max(1, total_failures)
    overall_failure_rate = total_failures / total_cases if total_cases else 0.0

    # 汇总改进建议（去重 + 护栏）
    suggested: list[str] = []
    seen: set[str] = set()
    for p in patterns:
        if p.failure_count == 0:
            continue
        for imp in PATTERN_IMPROVEMENT.get(p.pattern, []):
            if imp in seen:
                continue
            seen.add(imp)
            suggested.append(imp)
    # 护栏：建议不含禁止词
    suggested = [s for s in suggested if not contains_forbidden_content(s)]

    summary = _build_summary(total_cases, total_failures, overall_failure_rate, patterns, trend)

    return ReliabilityImprovementReport(
        report_id=f"REL-IMPROVE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        total_cases=total_cases,
        total_failures=total_failures,
        overall_failure_rate=overall_failure_rate,
        patterns=patterns,
        trend=trend,
        sources_analyzed=list(totals.keys()),
        summary=summary,
        suggested_improvements=suggested,
        created_at=_now_iso(),
    )


def _build_trend(session: Session) -> ReliabilityTrend:
    """比较不同版本/不同 Agent 表现（任务书 §生成 Reliability Trend）。

    以 Benchmark model 字段 + Arena winner + Red Team run_id 作为版本/Agent 标签，
    计算各标签的可靠性评分（0-100）并按时间排序。
    """
    points: list[TrendPoint] = []

    # Benchmark：按 model 分组准确率
    try:
        from app.models.benchmark import BenchmarkResultRow
        from sqlalchemy import func
        rows = (
            session.query(BenchmarkResultRow.model, func.count(BenchmarkResultRow.id))
            .group_by(BenchmarkResultRow.model)
            .all()
        )
        for model, cnt in rows:
            if not model:
                continue
            # 近似 score = 100 - error_rate * 100
            err_cnt = session.query(BenchmarkResultRow).filter(
                BenchmarkResultRow.model == model,
                BenchmarkResultRow.error.isnot(None),
            ).count() or 0
            score = max(0.0, 100.0 * (1 - err_cnt / max(1, cnt)))
            points.append(TrendPoint(label=f"Benchmark/{model}", score=score, samples=cnt, timestamp=""))
    except Exception:  # noqa: BLE101
        pass

    # Arena：按 winner 分组均分
    try:
        from app.models.agent_arena import ArenaResultRow
        from sqlalchemy import func
        rows = (
            session.query(ArenaResultRow.winner, func.avg(ArenaResultRow.final_arena_score), func.count(ArenaResultRow.id))
            .group_by(ArenaResultRow.winner)
            .all()
        )
        for winner, avg_score, cnt in rows:
            label = f"Arena/{winner or 'tie'}"
            points.append(TrendPoint(label=label, score=float(avg_score or 0.0), samples=cnt, timestamp=""))
    except Exception:  # noqa: BLE101
        pass

    # Red Team：按 run_id 顺序作为版本序列
    try:
        from app.models.red_team import RedTeamRunRow
        rows = session.query(RedTeamRunRow).order_by(RedTeamRunRow.id.asc()).limit(20).all()
        for r in rows:
            metrics = {}
            try:
                import json as _json
                metrics = _json.loads(r.metrics_json or "{}")
            except Exception:  # noqa: BLE101
                pass
            hdr = float(metrics.get("hallucination_detection_rate", 0.0) or 0.0)
            score = hdr * 100.0
            points.append(TrendPoint(
                label=f"RedTeam/{r.run_id[:16]}",
                score=score,
                samples=int(r.total_cases or 0),
                timestamp=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
            ))
    except Exception:  # noqa: BLE101
        pass

    # direction：最早 vs 最新
    direction = "stable"
    delta = 0.0
    if len(points) >= 2:
        delta = points[-1].score - points[0].score
        if delta > 5.0:
            direction = "improving"
        elif delta < -5.0:
            direction = "declining"
        else:
            direction = "stable"

    return ReliabilityTrend(points=points, direction=direction, delta=delta)


def _build_summary(total_cases: int, total_failures: int, overall_rate: float, patterns: list, trend: ReliabilityTrend) -> str:
    """生成报告摘要（仅可靠性结论，非投资建议）。"""
    top_pattern = max(patterns, key=lambda p: p.failure_count) if patterns else None
    top_str = f"最频失败模式为「{top_pattern}」({top_pattern.failure_count} 次)" if top_pattern and top_pattern.failure_count > 0 else "无显著失败模式"
    return (
        f"分析 {total_cases} 个案例，识别 {total_failures} 次失败（overall failure rate {overall_rate:.2%}）。"
        f"{top_str}。可靠性趋势：{trend.direction}（delta {trend.delta:+.1f}）。"
        f"本报告仅反映 AI 生成内容的失败模式与改进方向，不构成投资建议。"
    )


# ---------------------------------------------------------------------------
# 持久化 + 读取
# ---------------------------------------------------------------------------
def persist_report(session: Session, report: ReliabilityImprovementReport) -> int:
    """持久化报告到 reliability_reports 表，返回 db id。"""
    import json
    from datetime import datetime as _dt
    from app.models.reliability_improvement import ReliabilityReportRow
    row = ReliabilityReportRow(
        report_id=report.report_id,
        total_cases=report.total_cases,
        total_failures=report.total_failures,
        overall_failure_rate=report.overall_failure_rate,
        patterns_json=json.dumps([p.to_dict() for p in report.patterns], ensure_ascii=False),
        trend_json=json.dumps(report.trend.to_dict(), ensure_ascii=False),
        sources_analyzed_json=json.dumps(report.sources_analyzed, ensure_ascii=False),
        summary=report.summary,
        suggested_improvements_json=json.dumps(report.suggested_improvements, ensure_ascii=False),
        created_at=_dt.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.id


def get_report(session: Session, report_id: str) -> ReliabilityImprovementReport:
    """按 report_id 读取已持久化的报告。"""
    import json
    from app.models.reliability_improvement import ReliabilityReportRow
    from app.services.reliability_improvement.schemas import FailurePattern, ReliabilityTrend, TrendPoint
    row = session.query(ReliabilityReportRow).filter(ReliabilityReportRow.report_id == report_id).first()
    if row is None:
        raise LookupError(f"可靠性改进报告不存在: {report_id}")

    patterns_data = _loads(row.patterns_json, [])
    patterns = [
        FailurePattern(
            pattern=p.get("pattern", ""),
            failure_count=p.get("failure_count", 0),
            failure_rate=p.get("failure_rate", 0.0),
            affected_category=p.get("affected_category", ""),
            root_cause=p.get("root_cause", ""),
            suggested_improvement=p.get("suggested_improvement", ""),
        )
        for p in patterns_data
    ]
    trend_data = _loads(row.trend_json, {})
    trend = ReliabilityTrend(
        points=[TrendPoint(label=tp.get("label", ""), score=tp.get("score", 0.0), samples=tp.get("samples", 0), timestamp=tp.get("timestamp", "")) for tp in trend_data.get("points", [])],
        direction=trend_data.get("direction", "stable"),
        delta=trend_data.get("delta", 0.0),
    )
    return ReliabilityImprovementReport(
        report_id=row.report_id,
        total_cases=row.total_cases,
        total_failures=row.total_failures,
        overall_failure_rate=row.overall_failure_rate,
        patterns=patterns,
        trend=trend,
        sources_analyzed=_loads(row.sources_analyzed_json, []),
        summary=row.summary or "",
        suggested_improvements=_loads(row.suggested_improvements_json, []),
        created_at=(row.created_at.isoformat(timespec="seconds") + "Z") if row.created_at else "",
    )


def list_reports(session: Session, limit: int = 50) -> list[dict]:
    """列出最近报告（元数据）。"""
    from app.models.reliability_improvement import ReliabilityReportRow
    rows = (
        session.query(ReliabilityReportRow)
        .order_by(ReliabilityReportRow.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "report_id": r.report_id,
            "total_cases": r.total_cases,
            "total_failures": r.total_failures,
            "overall_failure_rate": r.overall_failure_rate,
            "created_at": (r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
        }
        for r in rows
    ]


def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        import json
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return default


__all__ = [
    "analyze_reliability",
    "persist_report",
    "get_report",
    "list_reports",
]

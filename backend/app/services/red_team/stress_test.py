"""FinProof Red Team Stress Testing Engine（Phase 14，任务书 §4 §5）。

支持一次运行 100+ 条 AI 生成金融观点，输出：

- StressTestMetrics: Detection Accuracy / Recall / Precision / Category Recall
- ReliabilityScore: FinProof Reliability Score（EVIDENCE_GROUNDING /
                     NUMERIC_ACCURACY / PERIOD_ACCURACY / RISK_DETECTION 维度）

持久化：red_team_runs / red_team_cases / red_team_results

约束：不修改已有核心模块；保持 Evidence First。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.red_team import (
    RedTeamCaseRow,
    RedTeamResultRow,
    RedTeamRunRow,
)
from app.services.red_team.attack_generator import (
    attack_distribution,
    generate_attacks,
)
from app.services.red_team.hallucination_detector import detect_batch
from app.services.red_team.schemas import (
    ReliabilityDimension,
    ReliabilityScore,
    StressTestMetrics,
    RedTeamRun,
    _now_iso,
    grade_of,
)


# ---------------------------------------------------------------------------
# 维度名称
# ---------------------------------------------------------------------------
DIM_EVIDENCE_GROUNDING = "EVIDENCE_GROUNDING"
DIM_NUMERIC_ACCURACY = "NUMERIC_ACCURACY"
DIM_PERIOD_ACCURACY = "PERIOD_ACCURACY"
DIM_RISK_DETECTION = "RISK_DETECTION"

DIMENSION_WEIGHTS = {
    DIM_EVIDENCE_GROUNDING: 0.20,
    DIM_NUMERIC_ACCURACY: 0.30,
    DIM_PERIOD_ACCURACY: 0.20,
    DIM_RISK_DETECTION: 0.30,
}


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def compute_metrics(
    cases_count: int,
    detection_results: list,
) -> StressTestMetrics:
    """计算压力测试指标。

    detection_results: list[DetectionResult]
    """
    detected = sum(1 for r in detection_results if r.detected)
    total = cases_count or len(detection_results)

    detection_accuracy = detected / total if total else 0.0
    # 简化口径：所有攻击案例都应被检测，recall = detection_accuracy
    recall = detection_accuracy
    # 精确率：检测到的都是真攻击（Red Team 全为攻击），precision = 1.0 if detected else 0
    precision = 1.0 if detected > 0 else 0.0

    # 分攻击类型召回率
    by_cat: dict[str, list[bool]] = {}
    for r in detection_results:
        # case_id 关联回 attack_type
        cat = getattr(r, "_attack_type", "")
        if not cat:
            continue
        by_cat.setdefault(cat, []).append(r.detected)

    category_recall = {
        cat: round(sum(flags) / len(flags), 3)
        for cat, flags in by_cat.items()
        if flags
    }

    return StressTestMetrics(
        total_cases=total,
        detected_cases=detected,
        detection_accuracy=round(detection_accuracy, 3),
        recall=round(recall, 3),
        precision=round(precision, 3),
        category_recall=category_recall,
    )


# ---------------------------------------------------------------------------
# Reliability Score 计算（任务书 §5）
# ---------------------------------------------------------------------------
def compute_reliability_score(
    metrics: StressTestMetrics,
    category_recall: dict[str, float],
) -> ReliabilityScore:
    """计算 FinProof Reliability Score（0-100）。

    维度（任务书 §5）：
    - EVIDENCE_GROUNDING   证据接地性
    - NUMERIC_ACCURACY     数字准确性
    - PERIOD_ACCURACY      期间准确性
    - RISK_DETECTION       风险检测能力
    """
    # 各维度分数（0-100）
    evidence_grounding = 100.0 * metrics.detection_accuracy
    numeric_accuracy = 100.0 * category_recall.get("NUMERIC_HALLUCINATION", metrics.detection_accuracy)
    period_accuracy = 100.0 * category_recall.get("PERIOD_CONFUSION", metrics.detection_accuracy)
    risk_detection = 100.0 * metrics.recall

    dimensions = [
        ReliabilityDimension(
            name=DIM_EVIDENCE_GROUNDING,
            score=evidence_grounding,
            weight=DIMENSION_WEIGHTS[DIM_EVIDENCE_GROUNDING],
        ),
        ReliabilityDimension(
            name=DIM_NUMERIC_ACCURACY,
            score=numeric_accuracy,
            weight=DIMENSION_WEIGHTS[DIM_NUMERIC_ACCURACY],
        ),
        ReliabilityDimension(
            name=DIM_PERIOD_ACCURACY,
            score=period_accuracy,
            weight=DIMENSION_WEIGHTS[DIM_PERIOD_ACCURACY],
        ),
        ReliabilityDimension(
            name=DIM_RISK_DETECTION,
            score=risk_detection,
            weight=DIMENSION_WEIGHTS[DIM_RISK_DETECTION],
        ),
    ]

    finproof_score = sum(d.score * d.weight for d in dimensions)
    grade = grade_of(finproof_score)

    summary = (
        f"FinProof Reliability Score: {finproof_score:.1f}/100 ({grade})。"
        f"证据接地 {evidence_grounding:.0f}、数字准确 {numeric_accuracy:.0f}、"
        f"期间准确 {period_accuracy:.0f}、风险检测 {risk_detection:.0f}。"
    )

    return ReliabilityScore(
        finproof_score=round(finproof_score, 1),
        dimensions=dimensions,
        grade=grade,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# 主入口：run_stress_test
# ---------------------------------------------------------------------------
def run_stress_test(
    session: Session,
    base_claims: list[dict],
    count_per_type: int = 20,
    seed: int = 42,
) -> RedTeamRun:
    """运行压力测试：生成攻击 → 检测 → 评分 → 持久化。

    Args:
        session: 数据库会话
        base_claims: 基础主张列表 [{"text", "company", "stock_code", "attack_types"}]
        count_per_type: 每种攻击类型生成多少条
        seed: 随机种子

    Returns:
        RedTeamRun
    """
    # Step 1: 生成攻击案例
    cases = generate_attacks(base_claims, count_per_type=count_per_type, seed=seed)
    if not cases:
        return RedTeamRun()

    # Step 2: 检测幻觉
    detection_results = detect_batch(cases)

    # 关联 attack_type 到 detection_results（用于 category_recall）
    case_by_id = {c.case_id: c for c in cases}
    for r in detection_results:
        case = case_by_id.get(r.case_id)
        if case:
            setattr(r, "_attack_type", case.attack_type)

    # Step 3: 计算指标
    metrics = compute_metrics(len(cases), detection_results)

    # category_recall 需要按 attack_type 分组
    by_cat: dict[str, list[bool]] = {}
    for r in detection_results:
        cat = getattr(r, "_attack_type", "")
        if cat:
            by_cat.setdefault(cat, []).append(r.detected)
    metrics.category_recall = {
        cat: round(sum(flags) / len(flags), 3)
        for cat, flags in by_cat.items()
        if flags
    }

    # Step 4: 计算 Reliability Score
    reliability_score = compute_reliability_score(metrics, metrics.category_recall)

    # Step 5: 构造 RedTeamRun
    run_id = f"RT-RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    run = RedTeamRun(
        run_id=run_id,
        total_cases=len(cases),
        cases=cases,
        detection_results=detection_results,
        metrics=metrics,
        reliability_score=reliability_score,
        attack_distribution=attack_distribution(cases),
        created_at=_now_iso(),
    )

    # Step 6: 持久化
    _persist_run(session, run)

    return run


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def _persist_run(session: Session, run: RedTeamRun) -> None:
    """持久化 RedTeamRun 到数据库。"""
    import json

    # 1. run
    run_row = RedTeamRunRow(
        run_id=run.run_id,
        total_cases=run.total_cases,
        metrics_json=json.dumps(run.metrics.to_dict(), ensure_ascii=False),
        reliability_score_json=json.dumps(run.reliability_score.to_dict(), ensure_ascii=False),
        attack_distribution_json=json.dumps(run.attack_distribution, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    session.add(run_row)
    session.flush()
    run_id_db = run_row.id

    # 2. cases + results
    for case, result in zip(run.cases, run.detection_results):
        case_row = RedTeamCaseRow(
            run_id=run_id_db,
            case_id=case.case_id,
            original_claim=case.original_claim,
            attacked_claim=case.attacked_claim,
            attack_type=case.attack_type,
            expected_risk=case.expected_risk,
            company=case.company,
            stock_code=case.stock_code,
            metric=case.metric,
            original_value=case.original_value,
            attacked_value=case.attacked_value,
            period_original=case.period_original,
            period_attacked=case.period_attacked,
            created_at=datetime.utcnow(),
        )
        session.add(case_row)
        session.flush()
        result_row = RedTeamResultRow(
            run_id=run_id_db,
            case_id=case.case_id,
            detected=result.detected,
            error_type=result.error_type,
            evidence_json=json.dumps(result.evidence, ensure_ascii=False),
            risk_score=result.risk_score,
            verification_status=result.verification_status,
            confidence=result.confidence,
            created_at=datetime.utcnow(),
        )
        session.add(result_row)

    session.commit()


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def get_run(session: Session, run_id: int) -> RedTeamRun:
    """按数据库 id 查询 Red Team run。"""
    import json

    row = session.get(RedTeamRunRow, run_id)
    if row is None:
        raise LookupError(f"Red Team run 不存在: {run_id}")

    # 加载 cases
    case_rows = (
        session.query(RedTeamCaseRow)
        .filter(RedTeamCaseRow.run_id == run_id)
        .order_by(RedTeamCaseRow.id.asc())
        .all()
    )
    result_rows = (
        session.query(RedTeamResultRow)
        .filter(RedTeamResultRow.run_id == run_id)
        .order_by(RedTeamResultRow.id.asc())
        .all()
    )

    from app.services.red_team.schemas import AttackCase, DetectionResult

    cases = [
        AttackCase(
            case_id=cr.case_id,
            original_claim=cr.original_claim,
            attacked_claim=cr.attacked_claim,
            attack_type=cr.attack_type,
            expected_risk=cr.expected_risk,
            company=cr.company,
            stock_code=cr.stock_code,
            metric=cr.metric,
            original_value=cr.original_value,
            attacked_value=cr.attacked_value,
            period_original=cr.period_original,
            period_attacked=cr.period_attacked,
        )
        for cr in case_rows
    ]
    result_by_case = {rr.case_id: rr for rr in result_rows}
    results = []
    for c in cases:
        rr = result_by_case.get(c.case_id)
        if rr:
            results.append(DetectionResult(
                case_id=c.case_id,
                detected=rr.detected,
                error_type=rr.error_type,
                evidence=json.loads(rr.evidence_json) if rr.evidence_json else [],
                risk_score=rr.risk_score,
                verification_status=rr.verification_status,
                confidence=rr.confidence,
            ))

    metrics_dict = json.loads(row.metrics_json) if row.metrics_json else {}
    rel_dict = json.loads(row.reliability_score_json) if row.reliability_score_json else {}
    dist = json.loads(row.attack_distribution_json) if row.attack_distribution_json else {}

    metrics = StressTestMetrics(
        total_cases=metrics_dict.get("total_cases", 0),
        detected_cases=metrics_dict.get("detected_cases", 0),
        detection_accuracy=metrics_dict.get("detection_accuracy", 0.0),
        recall=metrics_dict.get("recall", 0.0),
        precision=metrics_dict.get("precision", 0.0),
        category_recall=metrics_dict.get("category_recall", {}),
    )

    dimensions = [
        ReliabilityDimension(
            name=d.get("name", ""),
            score=d.get("score", 0.0),
            weight=d.get("weight", 0.25),
        )
        for d in rel_dict.get("dimensions", [])
    ]
    reliability = ReliabilityScore(
        finproof_score=rel_dict.get("finproof_score", 0.0),
        dimensions=dimensions,
        grade=rel_dict.get("grade", "F"),
        summary=rel_dict.get("summary", ""),
    )

    return RedTeamRun(
        run_id=row.run_id,
        total_cases=row.total_cases,
        cases=cases,
        detection_results=results,
        metrics=metrics,
        reliability_score=reliability,
        attack_distribution=dist,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


def list_runs(session: Session, limit: int = 20) -> list[RedTeamRun]:
    """列出 Red Team runs（仅元数据，不加载 cases）。"""
    import json

    rows = (
        session.query(RedTeamRunRow)
        .order_by(RedTeamRunRow.id.desc())
        .limit(limit)
        .all()
    )
    runs = []
    for row in rows:
        metrics_dict = json.loads(row.metrics_json) if row.metrics_json else {}
        rel_dict = json.loads(row.reliability_score_json) if row.reliability_score_json else {}
        dist = json.loads(row.attack_distribution_json) if row.attack_distribution_json else {}

        metrics = StressTestMetrics(
            total_cases=metrics_dict.get("total_cases", 0),
            detected_cases=metrics_dict.get("detected_cases", 0),
            detection_accuracy=metrics_dict.get("detection_accuracy", 0.0),
            recall=metrics_dict.get("recall", 0.0),
            precision=metrics_dict.get("precision", 0.0),
            category_recall=metrics_dict.get("category_recall", {}),
        )
        dimensions = [
            ReliabilityDimension(
                name=d.get("name", ""),
                score=d.get("score", 0.0),
                weight=d.get("weight", 0.25),
            )
            for d in rel_dict.get("dimensions", [])
        ]
        reliability = ReliabilityScore(
            finproof_score=rel_dict.get("finproof_score", 0.0),
            dimensions=dimensions,
            grade=rel_dict.get("grade", "F"),
            summary=rel_dict.get("summary", ""),
        )

        runs.append(RedTeamRun(
            run_id=row.run_id,
            total_cases=row.total_cases,
            metrics=metrics,
            reliability_score=reliability,
            attack_distribution=dist,
            created_at=row.created_at.isoformat(timespec="seconds") + "Z"
            if row.created_at
            else "",
        ))
    return runs


__all__ = [
    "DIM_EVIDENCE_GROUNDING",
    "DIM_NUMERIC_ACCURACY",
    "DIM_PERIOD_ACCURACY",
    "DIM_RISK_DETECTION",
    "DIMENSION_WEIGHTS",
    "compute_metrics",
    "compute_reliability_score",
    "run_stress_test",
    "get_run",
    "list_runs",
]

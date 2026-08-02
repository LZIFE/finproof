"""FinProof Red Team API（Phase 14）。

- POST /api/v1/red-team/attacks          生成攻击案例
- POST /api/v1/red-team/detection        检测单条攻击
- POST /api/v1/red-team/stress-test      运行压力测试（100+ 条）
- GET  /api/v1/red-team/runs             列出 Red Team runs
- GET  /api/v1/red-team/runs/{run_id}    查询 run 详情
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.red_team import (
    AttackGenerateRequest,
    DetectionRequest,
    StressTestRequest,
)
from app.services.red_team import (
    detect_hallucination,
    generate_attack,
    get_run,
    list_runs,
    run_stress_test,
)

router = APIRouter(tags=["red_team"])


@router.post("/api/v1/red-team/attacks", status_code=201)
def generate_attacks_endpoint(
    body: AttackGenerateRequest,
    session: Session = Depends(get_session),
) -> dict:
    """生成攻击案例。

    body 可指定 original_claim + attack_type 生成单条；
    或 base_claims 批量生成。
    """
    try:
        if body.original_claim:
            case = generate_attack(
                original_claim=body.original_claim,
                attack_type=body.attack_type,
                company=body.company,
                stock_code=body.stock_code,
            )
            return case.to_dict()
        raise HTTPException(status_code=422, detail="original_claim 不可为空")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/v1/red-team/detection", status_code=200)
def detection_endpoint(
    body: DetectionRequest,
    session: Session = Depends(get_session),
) -> dict:
    """检测单条攻击案例是否为金融 AI 幻觉。"""
    from app.services.red_team.schemas import AttackCase

    case = AttackCase(
        case_id=body.case_id or "ATC-API",
        original_claim=body.original_claim,
        attacked_claim=body.attacked_claim,
        attack_type=body.attack_type,
        expected_risk=body.expected_risk,
        company=body.company,
        stock_code=body.stock_code,
    )
    result = detect_hallucination(case)
    return {
        "case": case.to_dict(),
        "detection": result.to_dict(),
    }


@router.post("/api/v1/red-team/stress-test", status_code=201)
def stress_test_endpoint(
    body: StressTestRequest,
    session: Session = Depends(get_session),
) -> dict:
    """运行压力测试：生成攻击 → 检测 → 评分 → 持久化。"""
    try:
        base_claims = [
            {
                "text": bc.text,
                "company": bc.company,
                "stock_code": bc.stock_code,
                "attack_types": bc.attack_types,
            }
            for bc in body.base_claims
        ]
        run = run_stress_test(
            session,
            base_claims=base_claims,
            count_per_type=body.count_per_type,
            seed=body.seed,
        )
        return run.to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"压力测试失败: {exc}") from exc


@router.get("/api/v1/red-team/runs")
def list_runs_endpoint(
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    runs = list_runs(session, limit=limit)
    return {
        "count": len(runs),
        "runs": [
            {
                "run_id": r.run_id,
                "total_cases": r.total_cases,
                "metrics": r.metrics.to_dict(),
                "reliability_score": r.reliability_score.to_dict(),
                "attack_distribution": r.attack_distribution,
                "created_at": r.created_at,
            }
            for r in runs
        ],
    }


@router.get("/api/v1/red-team/runs/{run_id}")
def get_run_endpoint(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return get_run(session, run_id).to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

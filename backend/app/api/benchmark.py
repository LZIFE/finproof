"""Benchmark API（Phase 11）。

- POST /api/v1/benchmark/seed              载入预置 50 条金融测试案例
- GET  /api/v1/benchmark/dataset            查询 Dataset 概况（数量/错误分布）
- POST /api/v1/benchmark/runs              运行评测（FinProof vs Baseline LLM）
- GET  /api/v1/benchmark/runs/{run_id}     查询评测报告
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.benchmark import BenchmarkRunRequest, SeedDatasetRequest
from app.services.benchmark.dataset import (
    count_cases,
    get_error_distribution,
    get_seed_cases,
    load_dataset,
    seed_dataset,
)
from app.services.benchmark.evaluator import (
    MODEL_BASELINE_LLM,
    MODEL_FINPROOF,
    get_report,
    run_benchmark,
    save_report,
)

router = APIRouter(tags=["benchmark"])


@router.post("/api/v1/benchmark/seed", status_code=201)
def seed_benchmark_dataset(
    body: SeedDatasetRequest,
    session: Session = Depends(get_session),
) -> dict:
    """载入预置 50 条金融测试案例到 benchmark_cases 表。"""
    try:
        count = seed_dataset(session, dataset_name=body.dataset_name)
        cases = load_dataset(session, body.dataset_name)
        return {
            "dataset_name": body.dataset_name,
            "count": count,
            "error_distribution": get_error_distribution(cases),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"载入 Dataset 失败: {exc}") from exc


@router.get("/api/v1/benchmark/dataset")
def get_dataset_overview(
    session: Session = Depends(get_session),
    dataset_name: str | None = None,
) -> dict:
    """查询 Dataset 概况：数量 + 错误分布。

    若未指定 dataset_name，返回预置案例的概况（不入库）。
    """
    if dataset_name:
        cases = load_dataset(session, dataset_name)
    else:
        cases = get_seed_cases()
    return {
        "dataset_name": dataset_name or "finproof_seed_v1",
        "count": len(cases),
        "error_distribution": get_error_distribution(cases),
        "models": [MODEL_FINPROOF, MODEL_BASELINE_LLM],
    }


@router.post("/api/v1/benchmark/runs", status_code=201)
def run_benchmark_endpoint(
    body: BenchmarkRunRequest,
    session: Session = Depends(get_session),
) -> dict:
    """运行评测：FinProof vs Baseline LLM，输出指标 + 模型对比。"""
    try:
        report = run_benchmark(
            session,
            dataset_name=body.dataset_name,
            models=body.models,
            use_seed=body.use_seed,
        )
        report = save_report(session, report)
        return report.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"评测失败: {exc}") from exc


@router.get("/api/v1/benchmark/runs/{run_id}")
def get_benchmark_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        report = get_report(session, run_id)
        return report.to_dict()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/benchmark/dataset/count")
def get_dataset_count(
    session: Session = Depends(get_session),
    dataset_name: str | None = None,
) -> dict:
    """统计案例数量。"""
    return {"dataset_name": dataset_name, "count": count_cases(session, dataset_name)}

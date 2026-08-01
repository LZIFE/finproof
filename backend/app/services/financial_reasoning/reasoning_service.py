"""FinProof Financial Reasoning Service（Phase 16，主调度器）。

主入口：reason_about —— 组合 logic_rules / assumption_checker / contradiction_reasoner / quality_analyzer，
生成 ReasoningRun（含多 ReasoningResult），持久化到 reasoning_runs / reasoning_results。

约束：不替代 Verification；不输出投资建议；不自动估值或交易。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.financial_reasoning import (
    ReasoningResultRow,
    ReasoningRunRow,
)
from app.services.financial_reasoning.assumption_checker import check_assumptions
from app.services.financial_reasoning.contradiction_reasoner import (
    contradiction_to_results,
    detect_contradictions,
)
from app.services.financial_reasoning.logic_rules import RULE_VERSION, apply_rules
from app.services.financial_reasoning.quality_analyzer import (
    growth_to_reasoning_result,
    analyze_growth_quality,
)
from app.services.financial_reasoning.schemas import (
    GQ_INSUFFICIENT,
    ReasoningInput,
    ReasoningResult,
    ReasoningRun,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 主入口：reason_about
# ---------------------------------------------------------------------------
def reason_about(session: Session, input_: ReasoningInput) -> ReasoningRun:
    """对单条主张执行金融推理，返回 ReasoningRun（已持久化）。

    流程：
      1. logic_rules.apply_rules        确定性逻辑规则
      2. assumption_checker             隐含假设
      3. contradiction_reasoner         冲突检测
      4. quality_analyzer（若为增长类主张）
    """
    run_id = f"REASON-RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:18]}"

    results: list[ReasoningResult] = []

    # 1) 确定性逻辑规则
    results.extend(apply_rules(input_))

    # 2) 隐含假设
    results.extend(check_assumptions(input_))

    # 3) 冲突检测
    contradictions = detect_contradictions(input_)
    results.extend(contradiction_to_results(input_, contradictions))

    # 4) 增长质量（若 claim 含增长信号）
    if any(k in input_.claim_text for k in ("增长", "同比", "提升", "扩张")):
        gq = analyze_growth_quality(input_)
        results.append(growth_to_reasoning_result(input_, gq))

    # 去重：相同 reasoning_type + status + logical_gap 保留首条
    seen: set[tuple] = set()
    deduped: list[ReasoningResult] = []
    for r in results:
        key = (r.reasoning_type, r.status, r.logical_gap)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # 分配 result_id 并关联 run_id
    for idx, r in enumerate(deduped, start=1):
        r.result_id = f"RR-{idx:04d}"
        r.run_id = run_id
        if not r.created_at:
            r.created_at = _now_iso()

    run = ReasoningRun(
        run_id=run_id,
        claim_text=input_.claim_text,
        input_ref=input_.to_dict(),
        results=deduped,
        rule_version=RULE_VERSION,
        created_at=_now_iso(),
    )

    # 持久化
    _persist_run(session, run)

    return run


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def get_run(session: Session, run_id: int) -> ReasoningRun:
    """按数据库 id 查询 ReasoningRun。"""
    row = session.get(ReasoningRunRow, run_id)
    if row is None:
        raise LookupError(f"推理运行不存在: {run_id}")
    return _run_from_row(session, row)


def get_run_results(session: Session, run_id: int) -> list[ReasoningResult]:
    """查询某 run 的全部 results。"""
    run = get_run(session, run_id)
    return run.results


def list_runs(session: Session, limit: int = 50) -> list[ReasoningRun]:
    """列出最近推理运行（仅元数据）。"""
    rows = (
        session.query(ReasoningRunRow)
        .order_by(ReasoningRunRow.id.desc())
        .limit(limit)
        .all()
    )
    return [_run_from_row(session, r, with_results=False) for r in rows]


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist_run(session: Session, run: ReasoningRun) -> None:
    """持久化 ReasoningRun + 全部 ReasoningResult。"""
    run_row = ReasoningRunRow(
        run_id=run.run_id,
        claim_text=run.claim_text,
        input_ref_json=json.dumps(run.input_ref, ensure_ascii=False),
        rule_version=run.rule_version,
        results_count=len(run.results),
        created_at=datetime.utcnow(),
    )
    session.add(run_row)
    session.flush()
    run_db_id = run_row.id

    for r in run.results:
        result_row = ReasoningResultRow(
            run_id=run_db_id,
            result_id=r.result_id,
            reasoning_type=r.reasoning_type,
            status=r.status,
            premises_json=json.dumps(r.premises, ensure_ascii=False),
            supporting_evidence_json=json.dumps(r.supporting_evidence, ensure_ascii=False),
            counter_evidence_json=json.dumps(r.counter_evidence, ensure_ascii=False),
            assumptions_json=json.dumps(r.assumptions, ensure_ascii=False),
            logical_gap=r.logical_gap,
            confidence=r.confidence,
            explanation=r.explanation,
            suggested_safe_wording=r.suggested_safe_wording,
            triggered_rules_json=json.dumps(r.triggered_rules, ensure_ascii=False),
            evidence_ids_json=json.dumps(r.evidence_ids, ensure_ascii=False),
            rule_version=r.rule_version,
            created_at=datetime.utcnow(),
        )
        session.add(result_row)

    session.commit()


def _run_from_row(session: Session, row: ReasoningRunRow, with_results: bool = True) -> ReasoningRun:
    """从数据库 row 构造 ReasoningRun。"""
    input_ref = {}
    if row.input_ref_json:
        try:
            input_ref = json.loads(row.input_ref_json)
        except Exception:  # noqa: BLE001
            input_ref = {}

    results: list[ReasoningResult] = []
    if with_results:
        result_rows = (
            session.query(ReasoningResultRow)
            .filter(ReasoningResultRow.run_id == row.id)
            .order_by(ReasoningResultRow.id.asc())
            .all()
        )
        for rr in result_rows:
            results.append(_result_from_row(rr))

    return ReasoningRun(
        run_id=row.run_id,
        claim_text=row.claim_text or "",
        input_ref=input_ref,
        results=results,
        rule_version=row.rule_version or RULE_VERSION,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
    )


def _result_from_row(rr: ReasoningResultRow) -> ReasoningResult:
    def _loads(s, default):
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return default

    return ReasoningResult(
        result_id=rr.result_id or "",
        run_id="",  # 由上层填充
        reasoning_type=rr.reasoning_type or "",
        status=rr.status or "",
        premises=_loads(rr.premises_json, []),
        supporting_evidence=_loads(rr.supporting_evidence_json, []),
        counter_evidence=_loads(rr.counter_evidence_json, []),
        assumptions=_loads(rr.assumptions_json, []),
        logical_gap=rr.logical_gap or "",
        confidence=rr.confidence or 0.0,
        explanation=rr.explanation or "",
        suggested_safe_wording=rr.suggested_safe_wording or "",
        triggered_rules=_loads(rr.triggered_rules_json, []),
        evidence_ids=_loads(rr.evidence_ids_json, []),
        rule_version=rr.rule_version or RULE_VERSION,
        created_at=rr.created_at.isoformat(timespec="seconds") + "Z"
        if rr.created_at
        else "",
    )


__all__ = [
    "reason_about",
    "get_run",
    "get_run_results",
    "list_runs",
]

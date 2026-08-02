"""FinProof Failure Analyzer（Phase 23，任务书 §读取）。

从既有 Benchmark / Red Team / Arena / Reasoning 结果读取失败案例 → FailureCase 列表。
**不修改已有核心模块**，仅 SELECT 既有 ORM 行。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.services.reliability_improvement.schemas import (
    FailureCase,
    PATTERN_EVIDENCE_MISSING,
    PATTERN_LOGICAL_GAP,
    PATTERN_NUMERIC_ERROR,
    PATTERN_PERIOD_CONFUSION,
    PATTERN_UNSUPPORTED_CLAIM,
    SOURCE_ARENA,
    SOURCE_BENCHMARK,
    SOURCE_REASONING,
    SOURCE_RED_TEAM,
)


def collect_failures(session: Session, limit: int = 200) -> tuple[list[FailureCase], dict[str, int]]:
    """聚合既有 Benchmark/Red Team/Arena/Reasoning 的失败案例。

    返回 (failures, totals)，totals = {source: total_cases}。
    """
    failures: list[FailureCase] = []
    totals: dict[str, int] = {}

    # ① Benchmark：detected_error / error 字段 → 失败
    f_bench, n_bench = _from_benchmark(session, limit)
    failures.extend(f_bench)
    totals[SOURCE_BENCHMARK] = n_bench

    # ② Red Team：metrics 中 hallucination 未检出 / attack 命中 → 失败
    f_rt, n_rt = _from_red_team(session, limit)
    failures.extend(f_rt)
    totals[SOURCE_RED_TEAM] = n_rt

    # ③ Arena：skeptic 命中 = analyst 失败；auditor issues
    f_arena, n_arena = _from_arena(session, limit)
    failures.extend(f_arena)
    totals[SOURCE_ARENA] = n_arena

    # ④ Reasoning：status != OK → 逻辑缺口
    f_reason, n_reason = _from_reasoning(session, limit)
    failures.extend(f_reason)
    totals[SOURCE_REASONING] = n_reason

    return failures, totals


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
def _from_benchmark(session: Session, limit: int) -> tuple[list[FailureCase], int]:
    out: list[FailureCase] = []
    total = 0
    try:
        from app.models.benchmark import BenchmarkResultRow
        rows = session.query(BenchmarkResultRow).limit(limit).all()
        total = len(rows)
        for r in rows:
            err = (r.error or "") or (r.detected_error or "")
            if not err:
                continue  # 无错误 → 跳过
            pattern = _classify_benchmark_error(err, r.predicted_risk_type or "")
            out.append(FailureCase(
                case_id=f"BENCH-{r.id}",
                source=SOURCE_BENCHMARK,
                pattern=pattern,
                company="",
                claim=(r.response_text or "")[:200],
                error_detail=err[:200],
                evidence_count=int((r.evidence_coverage or 0) * 10),  # 近似
                confidence=float(r.predicted_risk_score or 0.0),
                detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
            ))
    except Exception:  # noqa: BLE101
        pass
    return out, total


def _classify_benchmark_error(err: str, risk_type: str) -> str:
    """将 Benchmark 错误映射到 5 类 pattern。"""
    err_low = (err or "").lower()
    if any(k in err_low for k in ("numeric", "number", "计算", "数值", "增长率", "百分")):
        return PATTERN_NUMERIC_ERROR
    if any(k in err_low for k in ("period", "year", "期间", "年度", "季度")):
        return PATTERN_PERIOD_CONFUSION
    if any(k in err_low for k in ("unsupported", "no evidence", "无依据", "无证据")):
        return PATTERN_UNSUPPORTED_CLAIM
    if any(k in err_low for k in ("missing evidence", "evidence", "缺证据", "证据缺失")):
        return PATTERN_EVIDENCE_MISSING
    if any(k in err_low for k in ("logical", "gap", "逻辑", "缺口")):
        return PATTERN_LOGICAL_GAP
    # risk_type fallback
    if "period" in (risk_type or "").lower():
        return PATTERN_PERIOD_CONFUSION
    return PATTERN_NUMERIC_ERROR  # benchmark 默认数值类


# ---------------------------------------------------------------------------
# Red Team
# ---------------------------------------------------------------------------
def _from_red_team(session: Session, limit: int) -> tuple[list[FailureCase], int]:
    out: list[FailureCase] = []
    total = 0
    try:
        from app.models.red_team import RedTeamRunRow
        rows = session.query(RedTeamRunRow).limit(limit).all()
        total = len(rows)
        for r in rows:
            metrics = _loads(r.metrics_json, {})
            attacks = _loads(r.attack_distribution_json, {})
            # 攻击命中 = 模型失败
            for attack_type, hit_count in attacks.items():
                if hit_count and int(hit_count) > 0:
                    pattern = _classify_red_team_attack(attack_type)
                    out.append(FailureCase(
                        case_id=f"RT-{r.id}-{attack_type[:20]}",
                        source=SOURCE_RED_TEAM,
                        pattern=pattern,
                        company="",
                        claim=f"Red Team 攻击类型 {attack_type} 命中 {hit_count} 次",
                        error_detail=f"attack={attack_type}, hits={hit_count}",
                        evidence_count=0,
                        confidence=0.0,
                        detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
                    ))
            # 幻觉检出率低 → evidence_missing
            hdr = metrics.get("hallucination_detection_rate", 0.0) or 0.0
            if hdr < 0.5:
                out.append(FailureCase(
                    case_id=f"RT-{r.id}-hallucination",
                    source=SOURCE_RED_TEAM,
                    pattern=PATTERN_EVIDENCE_MISSING,
                    company="",
                    claim=f"幻觉检出率仅 {hdr:.2f}，存在未检出幻觉",
                    error_detail=f"hallucination_detection_rate={hdr:.2f}",
                    evidence_count=0,
                    confidence=0.0,
                    detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
                ))
    except Exception:  # noqa: BLE101
        pass
    return out, total


def _classify_red_team_attack(attack_type: str) -> str:
    at = (attack_type or "").lower()
    if any(k in at for k in ("numeric", "number", "数值")):
        return PATTERN_NUMERIC_ERROR
    if any(k in at for k in ("period", "year", "期间")):
        return PATTERN_PERIOD_CONFUSION
    if any(k in at for k in ("unsupported", "hallucin", "无依据")):
        return PATTERN_UNSUPPORTED_CLAIM
    if any(k in at for k in ("evidence", "证据")):
        return PATTERN_EVIDENCE_MISSING
    return PATTERN_LOGICAL_GAP


# ---------------------------------------------------------------------------
# Arena
# ---------------------------------------------------------------------------
def _from_arena(session: Session, limit: int) -> tuple[list[FailureCase], int]:
    out: list[FailureCase] = []
    total = 0
    try:
        from app.models.agent_arena import ArenaResultRow, ArenaRunRow
        rows = session.query(ArenaResultRow).limit(limit).all()
        total = len(rows)
        for r in rows:
            run_row = session.query(ArenaRunRow).filter(ArenaRunRow.id == r.run_id).first()
            company = run_row.company if run_row else ""
            # Skeptic 命中 = Analyst 失败
            challenges = _loads(r.skeptic_challenges_json, [])
            for c in challenges:
                if not c.get("valid", True):
                    continue  # 不成立的跳过
                ct = c.get("challenge_type", "")
                pattern = _classify_arena_challenge(ct)
                out.append(FailureCase(
                    case_id=f"ARENA-{r.id}-{c.get('challenge_id', '')[:20]}",
                    source=SOURCE_ARENA,
                    pattern=pattern,
                    company=company,
                    claim=(c.get("counter_claim") or "")[:200],
                    error_detail=f"challenge={ct}, target={c.get('target_viewpoint_id')}",
                    evidence_count=len(c.get("evidence", [])),
                    confidence=float(c.get("risk_score", 0.0)) / 100.0,
                    detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
                ))
            # Auditor issues
            audit = _loads(r.auditor_report_json, {})
            for issue in audit.get("issues", []):
                pattern = PATTERN_EVIDENCE_MISSING if "evidence" in (issue.get("issue_type") or "") else PATTERN_LOGICAL_GAP
                out.append(FailureCase(
                    case_id=f"ARENA-{r.id}-issue-{issue.get('issue_id', '')[:10]}",
                    source=SOURCE_ARENA,
                    pattern=pattern,
                    company=company,
                    claim=(issue.get("description") or "")[:200],
                    error_detail=f"issue_type={issue.get('issue_type')}, affected={issue.get('affected')}",
                    evidence_count=0,
                    confidence=0.0,
                    detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
                ))
    except Exception:  # noqa: BLE101
        pass
    return out, total


def _classify_arena_challenge(challenge_type: str) -> str:
    ct = (challenge_type or "").lower()
    if "unsupported" in ct:
        return PATTERN_UNSUPPORTED_CLAIM
    if "missing" in ct:
        return PATTERN_EVIDENCE_MISSING
    if "contradictory" in ct or "growth" in ct:
        return PATTERN_LOGICAL_GAP
    if "overstatement" in ct:
        return PATTERN_LOGICAL_GAP
    return PATTERN_LOGICAL_GAP


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------
def _from_reasoning(session: Session, limit: int) -> tuple[list[FailureCase], int]:
    out: list[FailureCase] = []
    total = 0
    try:
        from app.models.financial_reasoning import ReasoningResultRow
        rows = session.query(ReasoningResultRow).limit(limit).all()
        total = len(rows)
        for r in rows:
            # status 非 OK/logical_gap 非空 → 逻辑缺口
            gap = (r.logical_gap or "").strip()
            status = (r.status or "").strip()
            if status in ("OK",) and not gap:
                continue  # 无缺口 → 跳过
            pattern = _classify_reasoning_type(r.reasoning_type or "", gap)
            out.append(FailureCase(
                case_id=f"REASON-{r.id}",
                source=SOURCE_REASONING,
                pattern=pattern,
                company="",
                claim=(r.explanation or "")[:200],
                error_detail=f"reasoning_type={r.reasoning_type}, status={status}, gap={gap[:120]}",
                evidence_count=len(_loads(r.evidence_ids_json, [])),
                confidence=float(r.confidence or 0.0),
                detected_at=(r.created_at.isoformat(timespec="seconds") + "Z") if r.created_at else "",
            ))
    except Exception:  # noqa: BLE101
        pass
    return out, total


def _classify_reasoning_type(reasoning_type: str, gap: str) -> str:
    rt = (reasoning_type or "").upper()
    if "PERIOD" in rt:
        return PATTERN_PERIOD_CONFUSION
    if "METRIC" in rt or "REVENUE" in rt or "PROFIT" in rt:
        return PATTERN_NUMERIC_ERROR
    if "SELECTIVE" in rt or "EVIDENCE" in rt:
        return PATTERN_EVIDENCE_MISSING
    if "ASSUMPTION" in rt or "CONCLUSION" in rt or "CORRELATION" in rt:
        return PATTERN_LOGICAL_GAP
    return PATTERN_LOGICAL_GAP


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------
def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return default


__all__ = ["collect_failures"]

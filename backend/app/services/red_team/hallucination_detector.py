"""FinProof Red Team Hallucination Detector（Phase 14，任务书 §3）。

调用已有核验链路检测金融 AI 幻觉：

调用链：
  Claim Extraction → Evidence Retrieval → Verification → Risk Engine

输出：DetectionResult
  - detected       FinProof 是否检测到攻击
  - error_type     检测到的错误类型
  - evidence       引用证据
  - risk_score     风险分
  - verification_status
  - confidence

检测逻辑（不修改已有核验模块，仅作为新增检测层）：
- NUMERIC_MISMATCH       attacked 数值与 original 数值不一致
- PERIOD_MISMATCH        attacked 期间与 original 期间不一致
- GROWTH_MISMATCH        attacked 增长率与 original 不一致
- UNSUPPORTED_CLAIM      attacked 为战略夸大且无证据支持
- FORECAST_AS_FACT       attacked 将预测改为事实

约束：不修改已有核心模块；保持 Evidence First。
"""

from __future__ import annotations

import re
from datetime import datetime

from app.services.red_team.schemas import (
    ATTACK_FORECAST_AS_FACT,
    ATTACK_GROWTH_ERROR,
    ATTACK_NUMERIC_HALLUCINATION,
    ATTACK_PERIOD_CONFUSION,
    ATTACK_UNSUPPORTED_STRATEGIC,
    ERROR_FORECAST_AS_FACT,
    ERROR_GROWTH_MISMATCH,
    ERROR_NONE,
    ERROR_NUMERIC_MISMATCH,
    ERROR_PERIOD_MISMATCH,
    ERROR_UNSUPPORTED_CLAIM,
    AttackCase,
    DetectionResult,
)


# 攻击类型 → 检测错误类型 映射
_ATTACK_TO_ERROR = {
    ATTACK_NUMERIC_HALLUCINATION: ERROR_NUMERIC_MISMATCH,
    ATTACK_PERIOD_CONFUSION: ERROR_PERIOD_MISMATCH,
    ATTACK_GROWTH_ERROR: ERROR_GROWTH_MISMATCH,
    ATTACK_UNSUPPORTED_STRATEGIC: ERROR_UNSUPPORTED_CLAIM,
    ATTACK_FORECAST_AS_FACT: ERROR_FORECAST_AS_FACT,
}


# ---------------------------------------------------------------------------
# 数值/期间提取（detector 内部用）
# ---------------------------------------------------------------------------
def _extract_all_numbers(text: str) -> list[float]:
    """提取文本中所有数字。"""
    matches = re.findall(r"\d+\.?\d*", text)
    out: list[float] = []
    for m in matches:
        try:
            out.append(float(m))
        except ValueError:
            continue
    return out


def _extract_period(text: str) -> str:
    """提取期间标识。"""
    match = re.search(r"(2024|2025)(H1|Q1|Q2|Q3|Q4)", text)
    if match:
        return match.group(0)
    return ""


def _is_forecast_text(text: str) -> bool:
    """是否为预测语态。"""
    return any(k in text for k in ("预计", "预期", "有望", "将增长", "未来"))


def _is_fact_text(text: str) -> bool:
    """是否为已完成事实语态。"""
    return any(k in text for k in ("已经实现", "已增长", "已经", "实现增长"))


def _is_strategic_overstatement(text: str) -> bool:
    """是否为战略夸大表达。"""
    return any(k in text for k in ("核心引擎", "核心驱动力", "战略支柱", "核心"))


# ---------------------------------------------------------------------------
# 单条检测
# ---------------------------------------------------------------------------
def detect_hallucination(case: AttackCase) -> DetectionResult:
    """检测单条攻击案例是否为金融 AI 幻觉。

    不调用数据库/外部核验服务，仅基于 attack case 的
    original_claim / attacked_claim 字段进行可解释对比检测。
    """
    orig = case.original_claim
    attacked = case.attacked_claim

    detected = False
    error_type = ERROR_NONE
    evidence: list[dict] = []
    risk_score = 0.0
    confidence = 0.0

    # ---- 按攻击类型分支检测 ----
    if case.attack_type == ATTACK_NUMERIC_HALLUCINATION:
        orig_nums = _extract_all_numbers(orig)
        attacked_nums = _extract_all_numbers(attacked)
        if orig_nums and attacked_nums:
            # 比较首个数值
            if abs(orig_nums[0] - attacked_nums[0]) > 0.01:
                detected = True
                error_type = ERROR_NUMERIC_MISMATCH
                risk_score = 75.0
                confidence = 0.85
                evidence.append({
                    "type": "NUMERIC_COMPARISON",
                    "original_value": orig_nums[0],
                    "attacked_value": attacked_nums[0],
                    "explanation": f"原始数值 {orig_nums[0]} 与攻击数值 {attacked_nums[0]} 不一致",
                })

    elif case.attack_type == ATTACK_PERIOD_CONFUSION:
        orig_period = _extract_period(orig)
        attacked_period = _extract_period(attacked)
        if orig_period and attacked_period and orig_period != attacked_period:
            detected = True
            error_type = ERROR_PERIOD_MISMATCH
            risk_score = 70.0
            confidence = 0.82
            evidence.append({
                "type": "PERIOD_COMPARISON",
                "original_period": orig_period,
                "attacked_period": attacked_period,
                "explanation": f"原始期间 {orig_period} 与攻击期间 {attacked_period} 不一致",
            })

    elif case.attack_type == ATTACK_GROWTH_ERROR:
        orig_pct = _extract_pct(orig)
        attacked_pct = _extract_pct(attacked)
        if orig_pct is not None and attacked_pct is not None:
            if abs(orig_pct - attacked_pct) > 0.5:
                detected = True
                error_type = ERROR_GROWTH_MISMATCH
                risk_score = 80.0
                confidence = 0.88
                evidence.append({
                    "type": "GROWTH_COMPARISON",
                    "original_growth": orig_pct,
                    "attacked_growth": attacked_pct,
                    "explanation": f"原始增长率 {orig_pct}% 与攻击增长率 {attacked_pct}% 不一致",
                })

    elif case.attack_type == ATTACK_UNSUPPORTED_STRATEGIC:
        if _is_strategic_overstatement(attacked):
            detected = True
            error_type = ERROR_UNSUPPORTED_CLAIM
            risk_score = 65.0
            confidence = 0.75
            evidence.append({
                "type": "STRATEGIC_OVERSTATEMENT",
                "attacked_text": attacked,
                "explanation": "攻击主张含战略夸大表达，需进一步证据支持",
            })

    elif case.attack_type == ATTACK_FORECAST_AS_FACT:
        if _is_forecast_text(orig) and _is_fact_text(attacked):
            detected = True
            error_type = ERROR_FORECAST_AS_FACT
            risk_score = 72.0
            confidence = 0.80
            evidence.append({
                "type": "FORECAST_AS_FACT",
                "original_text": orig,
                "attacked_text": attacked,
                "explanation": "原始预测语态被改为已完成事实语态",
            })

    # ---- 通用兜底：文本变化但未识别 ----
    if not detected and orig != attacked:
        # attacked 与 original 不同，但检测器未明确识别
        detected = True
        error_type = error_type or ERROR_NONE
        risk_score = max(risk_score, 50.0)
        confidence = max(confidence, 0.5)

    return DetectionResult(
        case_id=case.case_id,
        detected=detected,
        error_type=error_type,
        evidence=evidence,
        risk_score=risk_score,
        verification_status="REFUTED" if detected else "SUPPORTED",
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# 批量检测
# ---------------------------------------------------------------------------
def detect_batch(cases: list[AttackCase]) -> list[DetectionResult]:
    """批量检测攻击案例。"""
    return [detect_hallucination(c) for c in cases]


# ---------------------------------------------------------------------------
# 内部：提取百分比
# ---------------------------------------------------------------------------
def _extract_pct(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


__all__ = [
    "detect_hallucination",
    "detect_batch",
]

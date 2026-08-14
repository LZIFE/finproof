"""外部知识核验引擎：用户资料 → LLM 常识 → 可选联网搜索。

优先级：用户资料是用户指定的 ground truth，冲突以资料为准；
无资料时用 LLM 常识（带置信度）；联网搜索仅当配置开启且注入 web_search 时启用。
"""

from __future__ import annotations

import json
import re
from typing import Callable

from app.services.generic_verification.claim_extraction import extract_numbers
from app.services.generic_verification.schemas import GenericClaim, VerificationOutcome
from app.services.generic_verification.verifiers.internal_consistency import (
    _same_context_slot,
    values_compatible,
)
from app.services.verification.base import (
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

LLMCaller = Callable[[list[dict]], str]          # messages -> content
WebSearch = Callable[[str], list[dict]]          # query -> [{"title","snippet","url"}]


def _query_of(claim: GenericClaim) -> str:
    parts = list(claim.entities)
    for n in claim.numbers:
        parts.append(f"{n.get('value')}{n.get('unit') or ''}")
    return " ".join(p for p in parts if p)


def _material_evidence(user_materials: list[str], claim: GenericClaim) -> str | None:
    for m in user_materials:
        if any(e and e in m for e in claim.entities):
            return m
    return None


def _material_conflicts(material: str, claim: GenericClaim) -> bool:
    """资料是否与主张冲突：仅比较同一语义语境槽的数字。

    支持性资料中无关数字（如"同比增长 30%"）不算冲突。
    """
    for num in claim.numbers:
        ctx = (num.get("context") or "")
        for other in extract_numbers(material):
            if not _same_context_slot(ctx, other.get("context") or ""):
                continue
            if values_compatible(num.get("value"), num.get("unit"),
                                 other.get("value"), other.get("unit")):
                continue
            return True
    return False


def _parse_llm_verdict(content: str) -> dict | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'"verdict"\s*:\s*"(SUPPORTED|REFUTED|UNKNOWN)"', content)
        return {"verdict": m.group(1), "reason": ""} if m else None
    if isinstance(data, dict) and data.get("verdict") in {"SUPPORTED", "REFUTED", "UNKNOWN"}:
        return data
    return None


def verify_claim_external(
    claim: GenericClaim,
    user_materials: list[str] | None = None,
    llm_caller: LLMCaller | None = None,
    web_search: WebSearch | None = None,
    enable_web_search: bool = False,
) -> VerificationOutcome:
    evidence: list[dict] = []
    query = _query_of(claim)

    # 1. 用户资料（ground truth）
    material = _material_evidence(user_materials or [], claim)
    if material:
        evidence.append({"text": material[:200], "source": "user_materials"})
        if _material_conflicts(material, claim):
            return VerificationOutcome(
                claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.9,
                mode_used=["external"], evidence=evidence,
                reason="用户资料与主张数值冲突", error_type="EXTERNAL_CONFLICT",
            )
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.8,
            mode_used=["external"], evidence=evidence,
            reason="用户资料支持主张", error_type=None,
        )

    # 2. LLM 常识
    if llm_caller is not None:
        try:
            content = llm_caller([
                {"role": "system", "content": (
                    "你是事实核验助手。仅依据你自己的知识判断主张是否成立。"
                    '返回 JSON：{"verdict": "SUPPORTED|REFUTED|UNKNOWN", "reason": "一句话理由"}。'
                    "不确定时必须返回 UNKNOWN。"
                )},
                {"role": "user", "content": f"主张：{claim.source_text}\n检索词：{query}"},
            ])
            parsed = _parse_llm_verdict(content)
            if parsed and parsed["verdict"] in {"SUPPORTED", "REFUTED"}:
                verdict = STATUS_SUPPORTED if parsed["verdict"] == "SUPPORTED" else STATUS_REFUTED
                return VerificationOutcome(
                    claim_id=claim.claim_id, verdict=verdict, confidence=0.7,
                    mode_used=["external"],
                    evidence=[{"source": "llm_knowledge", "reason": parsed.get("reason", "")}],
                    reason=parsed.get("reason", "LLM 常识判定"),
                    error_type="EXTERNAL_CONFLICT" if verdict == STATUS_REFUTED else None,
                )
        except Exception:  # noqa: BLE001 —— LLM 失败视为未知，继续后续阶段
            pass

    # 3. 联网搜索（可选）
    if web_search is not None and enable_web_search:
        try:
            results = web_search(query)
            snippets = [r.get("snippet", "") for r in results]
            joined = " ".join(snippets)
            if joined:
                evidence.append({"source": "web_search", "snippets": snippets[:3]})
                for num in claim.numbers:
                    ctx = (num.get("context") or "")
                    for other in extract_numbers(joined):
                        if not _same_context_slot(ctx, other.get("context") or ""):
                            continue
                        if not values_compatible(num.get("value"), num.get("unit"),
                                                 other.get("value"), other.get("unit")):
                            return VerificationOutcome(
                                claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.65,
                                mode_used=["external"], evidence=evidence,
                                reason="联网检索到冲突数值", error_type="EXTERNAL_CONFLICT",
                            )
                return VerificationOutcome(
                    claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.6,
                    mode_used=["external"], evidence=evidence,
                    reason="联网检索到一致数值", error_type=None,
                )
        except Exception:  # noqa: BLE001
            pass

    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_UNABLE, confidence=0.4,
        mode_used=["external"], evidence=evidence,
        reason="无用户资料、LLM 无法判定且未开启/未命中联网搜索", error_type=None,
    )

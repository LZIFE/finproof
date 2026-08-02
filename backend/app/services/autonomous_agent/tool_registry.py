"""Autonomous Investigation Tool Registry（Phase 13）。

封装已有工具供 Agent 调用（任务书 §3）。

工具：
- retrieve_evidence          调用 evidence_retrieval 检索证据
- verify_claim               调用 verification_service 核验主张
- get_company_profile        调用 knowledge_graph 获取公司画像
- get_business_map           调用 knowledge_graph 获取业务图谱
- detect_conflicts           调用 knowledge_graph / intelligence 检测冲突
- assess_risk                调用 risk_engine 评估风险

约束：
- Agent 根据计划选择调用工具；禁止直接生成事实。
- 不修改已有核心逻辑；仅作为封装层调用。
- 不输出投资建议；不自动交易；不替代投资经理。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.autonomous_agent.schemas import (
    TOOL_ASSESS_RISK,
    TOOL_DETECT_CONFLICTS,
    TOOL_GET_BUSINESS_MAP,
    TOOL_GET_COMPANY_PROFILE,
    TOOL_RETRIEVE_EVIDENCE,
    TOOL_VERIFY_CLAIM,
    TOOL_LABELS,
)


# ---------------------------------------------------------------------------
# Tool：封装单个工具调用
# ---------------------------------------------------------------------------
class Tool:
    """单个工具封装：name / description / func。"""

    def __init__(self, name: str, description: str, func: Callable[..., dict]):
        self.name = name
        self.description = description
        self.func = func

    def call(self, session: Session, **kwargs) -> dict:
        """执行工具，返回标准化 dict 输出。"""
        return self.func(session, **kwargs)


# ---------------------------------------------------------------------------
# Tool implementations（封装已有服务）
# ---------------------------------------------------------------------------
def _retrieve_evidence(session: Session, claim: dict, top_k: int = 8) -> dict:
    """检索证据：调用 verification_service.fetch_evidence。"""
    from app.services.verification.verification_service import fetch_evidence

    evidence = fetch_evidence(session, claim, top_k=top_k)
    return {
        "tool": TOOL_RETRIEVE_EVIDENCE,
        "evidence_count": len(evidence),
        "evidence": evidence,
        "evidence_source": _extract_sources(evidence),
    }


def _verify_claim(session: Session, claim: dict, top_k: int = 8) -> dict:
    """核验主张：调用 verification_service.verify_claim。"""
    from app.services.verification.verification_service import verify_claim

    result = verify_claim(session, claim, top_k=top_k)
    out = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    return {
        "tool": TOOL_VERIFY_CLAIM,
        "verification_result": out,
        "evidence_source": _extract_sources(out.get("evidence", [])),
    }


def _get_company_profile(session: Session, company: str, stock_code: str = "") -> dict:
    """获取公司画像：从已加载文档中提取公司基本信息。"""
    from app.models import Document

    docs = session.query(Document).filter(Document.company_name == company).all()
    if not docs and stock_code:
        docs = session.query(Document).filter(Document.stock_code == stock_code).all()
    profile = {
        "company": company,
        "stock_code": stock_code,
        "document_count": len(docs),
        "report_periods": sorted({d.report_period for d in docs if d.report_period}),
    }
    return {
        "tool": TOOL_GET_COMPANY_PROFILE,
        "company_profile": profile,
        "evidence_source": [],
    }


def _get_business_map(session: Session, company: str, stock_code: str = "") -> dict:
    """获取业务图谱：从文档中识别业务分部/产品关键词。"""
    from app.models import Document, DocumentBlock

    # 查找该公司文档
    docs = session.query(Document).filter(Document.company_name == company).all()
    if not docs and stock_code:
        docs = session.query(Document).filter(Document.stock_code == stock_code).all()

    # 从文档块文本中识别业务关键词
    business_kw = {
        "暖通空调": ["暖通", "空调", "HVAC"],
        "消费电器": ["消费电器", "冰箱", "洗衣机", "厨电"],
        "机器人": ["机器人", "KUKA", "库卡", "自动化"],
        "智能建筑": ["智能建筑", "楼宇", "BA"],
        "海外业务": ["海外", "境外", "OBM", "国际"],
        "新能源": ["新能源", "储能", "电池", "光伏"],
    }
    segments: dict[str, list[str]] = {}
    for doc in docs[:3]:  # 仅扫前 3 个文档
        blocks = (
            session.query(DocumentBlock)
            .filter(DocumentBlock.document_id == doc.id)
            .limit(200)
            .all()
        )
        for seg, kws in business_kw.items():
            for b in blocks:
                if any(kw in (b.text or "") for kw in kws):
                    segments.setdefault(seg, []).extend(kws)
                    break

    return {
        "tool": TOOL_GET_BUSINESS_MAP,
        "business_map": {
            "company": company,
            "segments": list(segments.keys()),
            "segment_keywords": {k: list(set(v)) for k, v in segments.items()},
        },
        "evidence_source": [],
    }


def _detect_conflicts(session: Session, claim: dict, evidence: list[dict] | None = None) -> dict:
    """检测冲突：比较 claim 与证据中的数值/方向。"""
    claim_text = claim.get("original_text") or claim.get("text") or ""
    ev_list = evidence or []

    conflicts: list[dict] = []
    # 简单冲突检测：claim 含"增长"但证据含"下滑"/"下降"
    claim_positive = any(k in claim_text for k in ("增长", "上升", "提升", "核心", "驱动"))
    for ev in ev_list:
        ev_text = ev.get("text") or ev.get("block_text") or ""
        if not ev_text:
            continue
        negative_hits = [k for k in ("下滑", "下降", "减少", "收缩", "回落") if k in ev_text]
        if claim_positive and negative_hits:
            conflicts.append({
                "claim": claim_text[:100],
                "evidence_text": ev_text[:200],
                "conflict_keywords": negative_hits,
                "conflict_type": "DIRECTION_CONFLICT",
            })

    return {
        "tool": TOOL_DETECT_CONFLICTS,
        "conflicts_found": len(conflicts),
        "conflicts": conflicts,
        "evidence_source": [],
    }


def _assess_risk(session: Session, claim: dict, verification_result: dict | None = None) -> dict:
    """评估风险：调用 risk_engine.assess_claim。"""
    from app.services.risk.risk_engine import assess_claim

    v = verification_result or {}
    assessment = assess_claim(claim, v)
    out = assessment.to_dict() if hasattr(assessment, "to_dict") else dict(assessment)
    return {
        "tool": TOOL_ASSESS_RISK,
        "risk_assessment": out,
        "evidence_source": [],
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def build_registry() -> dict[str, Tool]:
    """构建工具注册表。"""
    tools = [
        Tool(TOOL_RETRIEVE_EVIDENCE, TOOL_LABELS[TOOL_RETRIEVE_EVIDENCE], _retrieve_evidence),
        Tool(TOOL_VERIFY_CLAIM, TOOL_LABELS[TOOL_VERIFY_CLAIM], _verify_claim),
        Tool(TOOL_GET_COMPANY_PROFILE, TOOL_LABELS[TOOL_GET_COMPANY_PROFILE], _get_company_profile),
        Tool(TOOL_GET_BUSINESS_MAP, TOOL_LABELS[TOOL_GET_BUSINESS_MAP], _get_business_map),
        Tool(TOOL_DETECT_CONFLICTS, TOOL_LABELS[TOOL_DETECT_CONFLICTS], _detect_conflicts),
        Tool(TOOL_ASSESS_RISK, TOOL_LABELS[TOOL_ASSESS_RISK], _assess_risk),
    ]
    return {t.name: t for t in tools}


def call_tool(
    registry: dict[str, Tool],
    session: Session,
    tool_name: str,
    **kwargs,
) -> dict:
    """调用指定工具，返回标准化 dict。"""
    tool = registry.get(tool_name)
    if tool is None:
        return {"tool": tool_name, "error": f"未知工具: {tool_name}"}
    try:
        return tool.call(session, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"tool": tool_name, "error": str(exc)}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _extract_sources(evidence: list[dict]) -> list[dict]:
    """从证据列表提取标准化来源信息。"""
    sources = []
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        sources.append({
            "block_id": ev.get("block_id") or ev.get("evidence_id"),
            "page_number": ev.get("page_number"),
            "document_id": ev.get("document_id"),
            "text": (ev.get("text") or ev.get("block_text") or "")[:200],
            "score": ev.get("final_score") or ev.get("score") or 0.0,
        })
    return sources


__all__ = [
    "Tool",
    "build_registry",
    "call_tool",
]

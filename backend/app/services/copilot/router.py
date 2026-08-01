"""FinProof Copilot Router（Phase 15，主调度器）。

Copilot 主入口：自然语言 → 意图识别 → 工具规划 → 执行 → 证据接地回答。

链路：
  query → intent_classifier.classify_intent
        → query_planner.run_plan（执行工具链）
        → response_generator.generate_response
        → 持久化会话消息

约束：不修改已有核心验证逻辑；Evidence First；不输出投资建议。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.copilot import CopilotMessageRow, CopilotSessionRow
from app.services.copilot.intent_classifier import classify_intent
from app.services.copilot.query_planner import run_plan
from app.services.copilot.response_generator import generate_response
from app.services.copilot.schemas import (
    ConversationMessage,
    ConversationSession,
    CopilotResponse,
    _now_iso,
)


# ---------------------------------------------------------------------------
# 主入口：chat
# ---------------------------------------------------------------------------
def chat(
    session: Session,
    query: str,
    session_id: str | None = None,
    user_id: str = "default",
) -> CopilotResponse:
    """Copilot 主入口：处理用户自然语言问题。

    Args:
        session: 数据库会话
        query: 用户自然语言问题
        session_id: 会话 ID（支持连续追问；若 None 新建会话）
        user_id: 用户 ID

    Returns:
        CopilotResponse（含 answer / evidence / verification / risk_score / tool_trace）
    """
    # Step 1: 意图识别
    intent = classify_intent(query)

    # Step 2: 工具规划与执行
    trace = run_plan(session, query, intent)

    # Step 3: 生成回答（Evidence First）
    response = generate_response(query, intent, trace)

    # Step 4: 持久化会话消息
    session_id = _persist_message(
        session,
        query,
        response,
        session_id=session_id,
        user_id=user_id,
    )

    return response


# ---------------------------------------------------------------------------
# 会话历史
# ---------------------------------------------------------------------------
def get_history(session: Session, session_id: str) -> ConversationSession:
    """查询会话历史（支持连续追问）。"""
    row = (
        session.query(CopilotSessionRow)
        .filter(CopilotSessionRow.session_id == session_id)
        .first()
    )
    if row is None:
        raise LookupError(f"会话不存在: {session_id}")

    msg_rows = (
        session.query(CopilotMessageRow)
        .filter(CopilotMessageRow.session_id == session_id)
        .order_by(CopilotMessageRow.id.asc())
        .all()
    )

    messages = [_message_from_row(r) for r in msg_rows]
    return ConversationSession(
        session_id=row.session_id,
        user_id=row.user_id,
        messages=messages,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z"
        if row.created_at
        else "",
        updated_at=row.updated_at.isoformat(timespec="seconds") + "Z"
        if row.updated_at
        else "",
    )


def list_sessions(session: Session, user_id: str | None = None, limit: int = 20) -> list[ConversationSession]:
    """列出用户会话。"""
    q = session.query(CopilotSessionRow)
    if user_id:
        q = q.filter(CopilotSessionRow.user_id == user_id)
    rows = q.order_by(CopilotSessionRow.id.desc()).limit(limit).all()

    sessions = []
    for row in rows:
        msg_rows = (
            session.query(CopilotMessageRow)
            .filter(CopilotMessageRow.session_id == row.session_id)
            .order_by(CopilotMessageRow.id.asc())
            .all()
        )
        messages = [_message_from_row(r) for r in msg_rows]
        sessions.append(ConversationSession(
            session_id=row.session_id,
            user_id=row.user_id,
            messages=messages,
            created_at=row.created_at.isoformat(timespec="seconds") + "Z"
            if row.created_at
            else "",
            updated_at=row.updated_at.isoformat(timespec="seconds") + "Z"
            if row.updated_at
            else "",
        ))
    return sessions


# ---------------------------------------------------------------------------
# 内部：持久化
# ---------------------------------------------------------------------------
def _persist_message(
    session: Session,
    query: str,
    response: CopilotResponse,
    session_id: str | None,
    user_id: str,
) -> str:
    """持久化用户问题与助手回答，返回 session_id。"""
    import json

    now = datetime.utcnow()

    # 确认或新建会话
    if not session_id:
        session_id = f"CS-{now.strftime('%Y%m%d%H%M%S%f')[:16]}"
        session_row = CopilotSessionRow(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(session_row)
    else:
        session_row = (
            session.query(CopilotSessionRow)
            .filter(CopilotSessionRow.session_id == session_id)
            .first()
        )
        if session_row is None:
            # 会话不存在则新建
            session_row = CopilotSessionRow(
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(session_row)
        session_row.updated_at = now

    session.flush()

    # 用户问题
    user_msg = CopilotMessageRow(
        session_id=session_id,
        role="user",
        content=query,
        timestamp=now,
    )
    session.add(user_msg)

    # 助手回答
    tools_called = [s.tool for s in response.tool_trace]
    assistant_msg = CopilotMessageRow(
        session_id=session_id,
        role="assistant",
        content=response.answer,
        intent_type=response.intent.intent_type if response.intent else "UNKNOWN",
        tools_called_json=json.dumps(tools_called, ensure_ascii=False),
        evidence_json=json.dumps(response.evidence, ensure_ascii=False),
        risk_score=response.risk_score,
        verification=response.verification,
        timestamp=now,
    )
    session.add(assistant_msg)

    session.commit()
    return session_id


def _message_from_row(row: CopilotMessageRow) -> ConversationMessage:
    import json

    tools = []
    if row.tools_called_json:
        try:
            tools = json.loads(row.tools_called_json)
        except Exception:  # noqa: BLE001
            tools = []
    evidence = []
    if row.evidence_json:
        try:
            evidence = json.loads(row.evidence_json)
        except Exception:  # noqa: BLE001
            evidence = []
    return ConversationMessage(
        id=row.id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        intent_type=row.intent_type or "",
        tools_called=tools,
        evidence=evidence,
        risk_score=row.risk_score or 0.0,
        timestamp=row.timestamp.isoformat(timespec="seconds") + "Z"
        if row.timestamp
        else "",
    )


__all__ = [
    "chat",
    "get_history",
    "list_sessions",
]

"""Phase 15 · Demo — FinProof Copilot · Financial Audit Assistant。

任务书 §8 Demo：准备三个问题，连续追问同一会话。

问题1："美的海外业务是否真的成为增长核心？"
  展示：KG（知识图谱业务结构）+ Evidence（证据检索）+ Semantic Verification（核验）

问题2："这份AI研报最大的风险是什么？"
  展示：Risk Ranking（风险引擎评估）

问题3："这个数字可信吗？"
  展示：Verification（核验结论）

流程：
  自然语言 → 意图识别 → 工具规划 → 执行 → 证据接地回答
    ↓ 持久化会话
  连续追问同一 session

约束：基于已有 Evidence First 架构回答；不输出投资建议；不自动交易；不修改已有核心验证逻辑。

运行：
    cd backend
    python -m scripts.phase15_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保可以 import app.*
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.copilot import CopilotMessageRow, CopilotSessionRow  # noqa: E402
from app.services.copilot import chat, classify_intent, get_history, list_sessions  # noqa: E402
from app.services.copilot.schemas import (  # noqa: E402
    INTENT_COMPARISON_QUERY,
    INTENT_EVIDENCE_QUERY,
    INTENT_FACT_QUERY,
    INTENT_INVESTIGATION_REQUEST,
    INTENT_RISK_EXPLANATION,
    INTENT_LABELS,
    TOOL_LABELS,
)


# ---------------------------------------------------------------------------
# Demo 三个问题（任务书 §8）
# ---------------------------------------------------------------------------
DEMO_QUESTIONS = [
    {
        "q": "美的海外业务是否真的成为增长核心？",
        "expect_intent": INTENT_INVESTIGATION_REQUEST,
        "expect_tools": ["knowledge_graph", "evidence_retrieval", "verification", "risk_engine"],
        "show": "KG + Evidence + Semantic Verification",
    },
    {
        "q": "这份AI研报最大的风险是什么？",
        "expect_intent": INTENT_RISK_EXPLANATION,
        "expect_tools": ["evidence_retrieval", "risk_engine"],
        "show": "Risk Ranking",
    },
    {
        "q": "这个数字可信吗？",
        "expect_intent": INTENT_EVIDENCE_QUERY,
        "expect_tools": ["evidence_retrieval", "verification"],
        "show": "Verification",
    },
]


def _clean(session) -> None:
    """清理旧 demo 数据。"""
    session.query(CopilotMessageRow).delete()
    session.query(CopilotSessionRow).delete()
    session.commit()


def run_demo() -> dict:
    init_db()
    result: dict = {"questions": []}

    with SessionLocal() as s:
        _clean(s)

        session_id = None  # 第一问新建会话，后续连续追问

        for idx, demo in enumerate(DEMO_QUESTIONS, start=1):
            print(f"\n[{idx}/3] 问题：{demo['q']}")
            print(f"      展示：{demo['show']}")

            # 意图识别（独立展示）
            intent = classify_intent(demo["q"])
            print(f"      意图：{INTENT_LABELS.get(intent.intent_type, intent.intent_type)}（置信度 {intent.confidence}）")

            # Copilot 回答（连续追问同一会话）
            resp = chat(s, demo["q"], session_id=session_id, user_id="demo_user")
            # 取出 session_id 供下一问使用
            if session_id is None:
                sessions = list_sessions(s, user_id="demo_user", limit=1)
                if sessions:
                    session_id = sessions[0].session_id

            # 展示回答
            print(f"\n  ▶ AI 回答：{resp.answer}")
            print(f"    核验结论：{resp.verification}")
            print(f"    风险评分：{resp.risk_score}（{resp.risk_level}）· 类型 {resp.risk_type or '-'}")
            print(f"    证据数：{len(resp.evidence)}")
            print("    调用工具链：")
            for st in resp.tool_trace:
                print(f"      Step {st.step} · {TOOL_LABELS.get(st.tool, st.tool)} — {st.purpose}")
            if resp.evidence:
                print("    证据来源：")
                for ev in resp.evidence[:2]:
                    print(f"      · {ev.get('document', '?')} 第 {ev.get('page', '?')} 页：{ev.get('content', '')[:60]}…")

            result["questions"].append({
                "question": demo["q"],
                "show": demo["show"],
                "intent": intent.to_dict(),
                "answer": resp.answer,
                "verification": resp.verification,
                "risk_score": resp.risk_score,
                "risk_level": resp.risk_level,
                "evidence_count": len(resp.evidence),
                "tools_called": [st.tool for st in resp.tool_trace],
            })

        # =======================================================
        # ④ 会话历史验证（连续追问）
        # =======================================================
        print("\n[4] 会话历史验证（连续追问同一 session）…")
        hist = get_history(s, session_id)
        print(f"  Session ID   : {session_id}")
        print(f"  消息总数     : {len(hist.messages)}")
        for m in hist.messages:
            role = "🙋 用户" if m.role == "user" else "🤖 Copilot"
            content_short = m.content[:50]
            print(f"    · {role}：{content_short}…")

        result["session"] = {
            "session_id": session_id,
            "message_count": len(hist.messages),
            "messages": [m.to_dict() for m in hist.messages],
        }

    return result


def _print_summary(result: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 15 · Copilot · Financial Audit Assistant — Demo Summary")
    print("=" * 78)

    for i, q in enumerate(result["questions"], start=1):
        print(f"\n[Q{i}] {q['question']}")
        print(f"  展示    : {q['show']}")
        print(f"  意图    : {INTENT_LABELS.get(q['intent']['intent_type'], q['intent']['intent_type'])}")
        print(f"  核验    : {q['verification']}")
        print(f"  风险    : {q['risk_score']}（{q['risk_level']}）")
        print(f"  证据数  : {q['evidence_count']}")
        print(f"  工具链  : {' → '.join(q['tools_called'])}")

    sess = result["session"]
    print(f"\n[Session] {sess['session_id']} · {sess['message_count']} 条消息（连续追问）")

    print("\n" + "=" * 78)
    print("Demo 完成：用户自然语言询问 → Agent 自动选择工具 → 回答含证据链 → 支持连续会话。")
    print("约束遵守：基于 Evidence First；不输出投资建议；不自动交易；不修改已有核心验证逻辑。")
    print("=" * 78)


if __name__ == "__main__":
    _result = run_demo()
    _print_summary(_result)
    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "session_id": _result["session"]["session_id"],
        "message_count": _result["session"]["message_count"],
        "questions": [
            {
                "question": q["question"],
                "intent": q["intent"]["intent_type"],
                "verification": q["verification"],
                "risk_score": q["risk_score"],
                "evidence_count": q["evidence_count"],
                "tools_called": q["tools_called"],
            }
            for q in _result["questions"]
        ],
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))

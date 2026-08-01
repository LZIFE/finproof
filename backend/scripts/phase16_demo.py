"""FinProof Phase 16 Demo · Financial Reasoning Engine（任务书 §9）。

至少完成 3 个案例：
  1. "海外收入增长，因此海外业务是利润增长核心"
     → 收入不等于利润贡献，CONCLUSION_OVERREACH
  2. "营收增长说明经营质量改善"
     → 若现金流下降或应收上升，LOW/MIXED_QUALITY_GROWTH
  3. "公司市场份额领先，因此具有长期竞争优势"
     → 排名证据不足以证明长期优势，HIDDEN_ASSUMPTION

运行：
    cd backend
    python -m scripts.phase16_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.financial_reasoning import reason_about  # noqa: E402
from app.services.financial_reasoning.schemas import (  # noqa: E402
    GQ_HIGH_QUALITY,
    GQ_INSUFFICIENT,
    GQ_LOW_QUALITY,
    GQ_MIXED_QUALITY,
    ReasoningInput,
)


# ---------------------------------------------------------------------------
# 3 Demo 案例
# ---------------------------------------------------------------------------
def _case1_overreach() -> dict:
    """案例 1：海外收入增长 → 利润增长核心（CONCLUSION_OVERREACH）。"""
    inp = ReasoningInput(
        claim_text="海外收入增长，因此海外业务是利润增长核心",
        evidence_candidates=[
            {"block_id": "EV-1", "text": "海外收入同比增长10%", "document_id": "2025年报", "page_number": 12},
        ],
        company="美的集团",
        period="2025FY",
    )
    return inp.to_dict() | {"case": "案例1：结论过度跳跃"}


def _case2_growth_quality() -> dict:
    """案例 2：营收增长 → 经营质量改善（LOW/MIXED QUALITY GROWTH）。"""
    inp = ReasoningInput(
        claim_text="营收增长说明经营质量改善",
        evidence_candidates=[
            {"block_id": "EV-2", "text": "营业收入同比增长10%", "document_id": "2025年报", "page_number": 8},
            {"block_id": "EV-3", "text": "净利润同比增长5%", "document_id": "2025年报", "page_number": 9},
            {"block_id": "EV-4", "text": "经营现金流同比下降20%", "document_id": "2025年报", "page_number": 22},
            {"block_id": "EV-5", "text": "应收账款同比上升25%", "document_id": "2025年报", "page_number": 15},
        ],
        company="美的集团",
        period="2025FY",
    )
    return inp.to_dict() | {"case": "案例2：增长质量风险"}


def _case3_hidden_assumption() -> dict:
    """案例 3：市场份额领先 → 长期竞争优势（HIDDEN_ASSUMPTION）。"""
    inp = ReasoningInput(
        claim_text="公司市场份额领先，因此具有长期竞争优势",
        evidence_candidates=[
            {"block_id": "EV-6", "text": "公司市场份额排名第一", "document_id": "行业研报", "page_number": 3},
        ],
        company="格力电器",
        period="2025FY",
    )
    return inp.to_dict() | {"case": "案例3：隐含假设"}


def _print_demo(case_num: int, title: str, run_dict: dict, expected_type: str) -> None:
    print("\n" + "=" * 78)
    print(f"Demo 案例 {case_num} · {title}")
    print("=" * 78)
    print(f"\n【输入主张】\n  {run_dict['claim_text']}")

    results = run_dict.get("results", [])
    print(f"\n【推理结果】共 {len(results)} 条")
    for i, r in enumerate(results, start=1):
        hit = "★" if r["reasoning_type"] == expected_type else " "
        print(f"\n  {hit} [{i}] {r['result_id']} · reasoning_type={r['reasoning_type']}")
        print(f"        status={r['status']} · confidence={r['confidence']}")
        if r["premises"]:
            print(f"        premises: {r['premises']}")
        if r["supporting_evidence"]:
            print(f"        supporting_evidence: {len(r['supporting_evidence'])} 条")
        if r["counter_evidence"]:
            print(f"        counter_evidence: {len(r['counter_evidence'])} 条")
            for ce in r["counter_evidence"][:2]:
                print(f"          · {ce.get('source')} p{ce.get('page')}：{ce.get('text', '')[:50]}…")
        if r["assumptions"]:
            print(f"        assumptions:")
            for a in r["assumptions"]:
                print(f"          · {a}")
        if r["logical_gap"]:
            print(f"        logical_gap: {r['logical_gap']}")
        print(f"        explanation: {r['explanation'][:120]}…")
        print(f"        suggested_safe_wording: {r['suggested_safe_wording']}")
        print(f"        triggered_rules: {r['triggered_rules']}")

    print("\n【验收】")
    matched = any(r["reasoning_type"] == expected_type for r in results)
    print(f"  预期 reasoning_type={expected_type} · 命中={matched}")
    # 安全措辞不含投资观点
    safe_all = "".join(r.get("suggested_safe_wording", "") for r in results)
    forbidden = ["买入", "卖出", "推荐股票", "建议加仓", "建议减仓"]
    bad = [kw for kw in forbidden if kw in safe_all]
    print(f"  安全措辞不含投资观点={len(bad) == 0}" + (f"  违规词={bad}" if bad else ""))


def main() -> None:
    print("=" * 78)
    print("FinProof Phase 16 · Financial Reasoning Engine Demo")
    print("=" * 78)
    print("\n本 Demo 展示投资组合 3 家公司的金融推理（不输出投资建议、自动估值或交易功能）。")

    init_db()

    demos = [
        (1, "结论过度跳跃（CONCLUSION_OVERREACH）", _case1_overreach(), "CONCLUSION_OVERREACH"),
        (2, "增长质量风险（GROWTH_QUALITY_RISK · LOW/MIXED）", _case2_growth_quality(), "GROWTH_QUALITY_RISK"),
        (3, "隐含假设（HIDDEN_ASSUMPTION）", _case3_hidden_assumption(), "HIDDEN_ASSUMPTION"),
    ]

    runs_json: list[dict] = []
    with SessionLocal() as s:
        for case_num, title, case_input, expected_type in demos:
            inp = ReasoningInput(
                claim_text=case_input["claim_text"],
                evidence_candidates=case_input.get("evidence_candidates", []),
                company=case_input.get("company", ""),
                period=case_input.get("period", ""),
            )
            run = reason_about(s, inp)
            run_dict = run.to_dict()
            runs_json.append({"case": title, "run": run_dict})
            _print_demo(case_num, title, run_dict, expected_type)

    # JSON dump 便于后续集成
    print("\n" + "=" * 78)
    print("全部 3 个 Demo 案例已完成，推理运行已持久化到 reasoning_runs / reasoning_results。")
    print("=" * 78 + "\n")
    print(json.dumps(runs_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

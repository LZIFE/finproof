"""FinProof Autonomous Research Agent Evaluation（Phase 17，任务书 §9）。

建立 20 家公司测试集，指标：
- Evidence Coverage          有证据事实占比
- Fact Accuracy               事实准确率（不含禁止词且绑定证据）
- Unsupported Claim Rate      无证据事实占比（应低）
- Task Completion Rate        已完成任务占比

评测集独立，不参与推理（仅传入公司名，不喂答案给 agent）。

运行：
    cd backend
    python -m scripts.phase17_eval
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.research_agent.orchestrator import run_research  # noqa: E402
from app.services.research_agent.schemas import contains_forbidden_memo_content  # noqa: E402


# ---------------------------------------------------------------------------
# 20 家公司测试集（任务书 §9）
# ---------------------------------------------------------------------------
@dataclass
class EvalCompany:
    company: str
    stock_code: str = ""
    expect_evidence_coverage_min: float = 0.0  # 评测门槛（公司无文档时 coverage=0 合理）


def _build_test_set() -> list[EvalCompany]:
    return [
        EvalCompany("美的集团", "000333"),
        EvalCompany("格力电器", "000651"),
        EvalCompany("海尔智家", "600690"),
        EvalCompany("贵州茅台", "600519"),
        EvalCompany("宁德时代", "300750"),
        EvalCompany("中国平安", "601318"),
        EvalCompany("招商银行", "600036"),
        EvalCompany("万科A", "000002"),
        EvalCompany("比亚迪", "002594"),
        EvalCompany("隆基绿能", "601012"),
        EvalCompany("中国建筑", "601668"),
        EvalCompany("上汽集团", "600104"),
        EvalCompany("中国中免", "601888"),
        EvalCompany("恒瑞医药", "600276"),
        EvalCompany("京东方A", "000725"),
        EvalCompany("泸州老窖", "000568"),
        EvalCompany("洋河股份", "002304"),
        EvalCompany("兖矿能源", "600188"),
        EvalCompany("中远海控", "601919"),
        EvalCompany("汇顶科技", "603160"),
    ]


def run_eval() -> dict:
    """对 20 家公司执行自主研究流程，汇总 4 项指标。"""
    init_db()
    test_set = _build_test_set()

    forbidden_hit = 0  # 含禁止词的 Memo 数（应为 0）
    coverage_sum = 0.0
    unsupported_sum = 0.0
    completion_sum = 0.0
    fact_count_total = 0
    grounded_facts_total = 0
    forbidden_fact_total = 0
    sessions: list[dict] = []

    with SessionLocal() as s:
        for ec in test_set:
            try:
                rs = run_research(s, ec.company, ec.stock_code)
                memo = rs.memo
                memo_dict = memo.to_dict() if memo else {}
            except Exception as exc:  # noqa: BLE001
                sessions.append({"company": ec.company, "error": str(exc)})
                continue

            # 指标汇总
            coverage = float(memo_dict.get("evidence_coverage", 0.0)) if memo else 0.0
            unsupported = float(memo_dict.get("unsupported_claim_rate", 0.0)) if memo else 0.0
            completion = float(memo_dict.get("task_completion_rate", 0.0)) if memo else 0.0
            coverage_sum += coverage
            unsupported_sum += unsupported
            completion_sum += completion

            # Fact Accuracy：统计事实数与含禁止词事实数
            all_facts = []
            for key in ("key_facts", "financial_facts", "business_facts"):
                for f in memo_dict.get(key, []):
                    all_facts.append(f.get("content", ""))
                    if f.get("notes"):
                        all_facts.append(f.get("notes", ""))
            for r in memo_dict.get("risk_findings", []):
                all_facts.append(r.get("content", ""))
                all_facts.append(r.get("logical_gap", ""))
            all_facts.extend(memo_dict.get("open_questions", []))
            all_facts.append(memo_dict.get("company_overview", ""))

            fact_count_total += len(all_facts)
            grounded_facts_total += sum(
                1 for f in memo_dict.get("key_facts", []) + memo_dict.get("financial_facts", []) + memo_dict.get("business_facts", [])
                if f.get("supported") and f.get("evidence")
            )
            forbidden_in_this = any(contains_forbidden_memo_content(t) for t in all_facts)
            if forbidden_in_this:
                forbidden_hit += 1
                forbidden_fact_total += 1

            sessions.append({
                "company": ec.company,
                "stock_code": ec.stock_code,
                "session_id": rs.session_id,
                "phase": rs.phase,
                "evidence_coverage": coverage,
                "unsupported_claim_rate": unsupported,
                "task_completion_rate": completion,
                "fact_count": len(all_facts),
                "forbidden": forbidden_in_this,
                "open_questions_count": len(memo_dict.get("open_questions", [])),
            })

    n = len(test_set)
    n_ok = sum(1 for x in sessions if "error" not in x)
    metrics = {
        "total_companies": n,
        "successful_runs": n_ok,
        "failed_runs": n - n_ok,
        "evidence_coverage_mean": round(coverage_sum / n_ok, 3) if n_ok else 0.0,
        "fact_accuracy": round((grounded_facts_total / fact_count_total) if fact_count_total else 0.0, 3),
        "unsupported_claim_rate_mean": round(unsupported_sum / n_ok, 3) if n_ok else 0.0,
        "task_completion_rate_mean": round(completion_sum / n_ok, 3) if n_ok else 0.0,
        "memo_forbidden_hits": forbidden_hit,  # 应为 0（Memo 不含投资建议/股票推荐/估值预测）
        "fact_count_total": fact_count_total,
        "grounded_facts_total": grounded_facts_total,
        "sessions": sessions,
    }
    return metrics


def _print_metrics(m: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 17 · Autonomous Research Agent Evaluation Metrics")
    print("=" * 78)
    print(f"\nTotal companies        : {m['total_companies']}")
    print(f"Successful runs        : {m['successful_runs']}")
    print(f"Failed runs            : {m['failed_runs']}")
    print(f"Evidence Coverage mean : {m['evidence_coverage_mean']}")
    print(f"Fact Accuracy          : {m['fact_accuracy']}")
    print(f"Unsupported Claim Rate : {m['unsupported_claim_rate_mean']}")
    print(f"Task Completion Rate   : {m['task_completion_rate_mean']}")
    print(f"Memo forbidden hits    : {m['memo_forbidden_hits']}  (should be 0)")
    print(f"Fact count total       : {m['fact_count_total']}")
    print(f"Grounded facts total   : {m['grounded_facts_total']}")
    print("\nPer-company:")
    for s in m["sessions"]:
        if "error" in s:
            print(f"  · {s['company']:<20} ERROR: {s['error'][:60]}")
        else:
            print(
                f"  · {s['company']:<20} cov={s['evidence_coverage']} "
                f"unsup={s['unsupported_claim_rate']} done={s['task_completion_rate']} "
                f"facts={s['fact_count']} forb={s['forbidden']} oq={s['open_questions_count']}"
            )
    print("\n" + "=" * 78)


if __name__ == "__main__":
    _m = run_eval()
    _print_metrics(_m)
    print("\n--- JSON Output ---")
    print(json.dumps(_m, ensure_ascii=False, indent=2))

"""FinProof Financial Reasoning Evaluation（Phase 16，任务书 §10）。

建立不少于 30 条推理测试案例，覆盖全部 reasoning types。输出：
- reasoning type accuracy        推理类型准确率
- logical gap detection recall   逻辑缺口检测召回
- counter-evidence recall        反证召回
- unsupported assumption detection rate   隐含假设检出率
- safe wording validity          安全措辞有效性

不得使用测试答案参与推理（评测集独立，不喂给推理器）。

运行：
    cd backend
    python -m scripts.phase16_eval
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
from app.services.financial_reasoning import (  # noqa: E402
    apply_rules,
    check_assumptions,
    contradiction_to_results,
    detect_contradictions,
    analyze_growth_quality,
    growth_to_reasoning_result,
    reason_about,
)
from app.services.financial_reasoning.schemas import (  # noqa: E402
    GQ_HIGH_QUALITY,
    GQ_INSUFFICIENT,
    GQ_LOW_QUALITY,
    GQ_MIXED_QUALITY,
    RT_BASE_EFFECT_RISK,
    RT_CONCLUSION_OVERREACH,
    RT_CORRELATION_AS_CAUSATION,
    RT_GROWTH_QUALITY_RISK,
    RT_HIDDEN_ASSUMPTION,
    RT_METRIC_SUBSTITUTION,
    RT_PERIOD_SUBSTITUTION,
    RT_REVENUE_PROFIT_CONFUSION,
    RT_SELECTIVE_EVIDENCE,
    STATUS_ASSUMPTION_UNVERIFIED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_LOGICAL_GAP,
    STATUS_MIXED_EVIDENCE,
    STATUS_OK,
    STATUS_UNSUPPORTED,
    ReasoningInput,
)


# ---------------------------------------------------------------------------
# 评测案例（≥30 条，覆盖全部 9 类 reasoning types + 增长质量 + 冲突）
# 每条仅含输入与"预期触发"标记；推理器不会被喂入预期答案。
# ---------------------------------------------------------------------------
@dataclass
class EvalCase:
    case_id: str
    claim_text: str
    evidence: list[dict]
    expect_types: list[str]  # 预期触发的 reasoning_type 集合
    expect_status: list[str]  # 预期至少一种 status 命中
    expect_counter_evidence: bool = False  # 预期产出 counter_evidence
    expect_assumption: bool = False  # 预期产出 assumptions
    expect_gap: bool = False  # 预期产出 logical_gap
    expect_safe_wording: bool = True  # 预期产出 suggested_safe_wording
    category: str = ""  # 分类标签


def _build_cases() -> list[EvalCase]:
    c: list[EvalCase] = []

    # === METRIC_SUBSTITUTION（3 条）===
    c.append(EvalCase("E01", "收入增长，因此利润增长", [{"block_id": 1, "text": "营收同比增10%"}], [RT_METRIC_SUBSTITUTION], [STATUS_LOGICAL_GAP], category="METRIC_SUB"))
    c.append(EvalCase("E02", "营收增长，净利润同步增长", [{"block_id": 1, "text": "营收同比增8%"}], [RT_METRIC_SUBSTITUTION], [STATUS_LOGICAL_GAP], category="METRIC_SUB"))
    c.append(EvalCase("E03", "收入增长带动利润增长", [{"block_id": 1, "text": "收入增"}], [RT_METRIC_SUBSTITUTION, RT_CORRELATION_AS_CAUSATION], [STATUS_LOGICAL_GAP, STATUS_ASSUMPTION_UNVERIFIED], category="METRIC_SUB"))

    # === PERIOD_SUBSTITUTION（3 条）===
    c.append(EvalCase("E04", "2025H1 增长，等同于2025Q2 增长", [{"block_id": 1, "text": "H1 增长"}], [RT_PERIOD_SUBSTITUTION], [STATUS_LOGICAL_GAP], category="PERIOD_SUB"))
    c.append(EvalCase("E05", "2024H1 与2024Q1 增长率等同", [{"block_id": 1, "text": "H1"}], [RT_PERIOD_SUBSTITUTION], [STATUS_LOGICAL_GAP], category="PERIOD_SUB"))
    c.append(EvalCase("E06", "2025H1 增长，2025FY 同口径", [{"block_id": 1, "text": "H1"}], [RT_PERIOD_SUBSTITUTION], [STATUS_LOGICAL_GAP], category="PERIOD_SUB"))

    # === CORRELATION_AS_CAUSATION（3 条）===
    c.append(EvalCase("E07", "研发投入增长带动了收入增长", [{"block_id": 1, "text": "研发增"}], [RT_CORRELATION_AS_CAUSATION], [STATUS_ASSUMPTION_UNVERIFIED], category="CORR_CAUS"))
    c.append(EvalCase("E08", "海外扩张推动利润增长", [{"block_id": 1, "text": "海外"}], [RT_CORRELATION_AS_CAUSATION], [STATUS_ASSUMPTION_UNVERIFIED], category="CORR_CAUS"))
    c.append(EvalCase("E09", "营销投入导致收入增长", [{"block_id": 1, "text": "营销"}], [RT_CORRELATION_AS_CAUSATION], [STATUS_ASSUMPTION_UNVERIFIED], category="CORR_CAUS"))

    # === REVENUE_PROFIT_CONFUSION（3 条）===
    c.append(EvalCase("E10", "海外收入贡献占比30%，因此海外利润贡献占比30%", [{"block_id": 1, "text": "收入贡献"}], [RT_REVENUE_PROFIT_CONFUSION], [STATUS_LOGICAL_GAP], category="REV_PROFIT"))
    c.append(EvalCase("E11", "海外收入占比30%，海外利润占比30%", [{"block_id": 1, "text": "收入占比"}], [RT_REVENUE_PROFIT_CONFUSION], [STATUS_LOGICAL_GAP], category="REV_PROFIT"))
    c.append(EvalCase("E12", "新业务收入贡献占比40%，新业务利润贡献40%", [{"block_id": 1, "text": "收入贡献"}], [RT_REVENUE_PROFIT_CONFUSION], [STATUS_LOGICAL_GAP], category="REV_PROFIT"))

    # === GROWTH_QUALITY_RISK（4 条）===
    c.append(EvalCase("E13", "营收增长说明经营质量改善", [
        {"block_id": 1, "text": "营业收入同比增10%"},
        {"block_id": 2, "text": "净利润同比增5%"},
        {"block_id": 3, "text": "经营现金流同比下降20%"},
        {"block_id": 4, "text": "应收账款同比上升25%"},
    ], [RT_GROWTH_QUALITY_RISK, RT_CONCLUSION_OVERREACH], [STATUS_MIXED_EVIDENCE, STATUS_LOGICAL_GAP], category="GROWTH_Q", expect_gap=True))
    c.append(EvalCase("E14", "营收增长，高质量增长", [
        {"block_id": 1, "text": "营业收入同比增10%"},
        {"block_id": 2, "text": "净利润同比增12%"},
        {"block_id": 3, "text": "经营现金流同比增8%"},
        {"block_id": 4, "text": "毛利率提升"},
    ], [RT_GROWTH_QUALITY_RISK], [STATUS_OK], category="GROWTH_Q"))
    c.append(EvalCase("E15", "营收增长但利润恶化", [
        {"block_id": 1, "text": "营业收入同比增10%"},
        {"block_id": 2, "text": "净利润同比下降5%"},
    ], [RT_GROWTH_QUALITY_RISK], [STATUS_MIXED_EVIDENCE], category="GROWTH_Q"))
    c.append(EvalCase("E16", "公司业务发展良好", [{"block_id": 1, "text": "abc"}], [RT_GROWTH_QUALITY_RISK], [STATUS_INSUFFICIENT_DATA], category="GROWTH_Q"))

    # === BASE_EFFECT_RISK（3 条）===
    c.append(EvalCase("E17", "新业务增长120%，从0起步的低基数高速增长", [{"block_id": 1, "text": "增长120%"}], [RT_BASE_EFFECT_RISK], [STATUS_ASSUMPTION_UNVERIFIED], category="BASE_EFFECT"))
    c.append(EvalCase("E18", "新业务增长80%，低基数", [{"block_id": 1, "text": "增长80%"}], [RT_BASE_EFFECT_RISK], [STATUS_ASSUMPTION_UNVERIFIED], category="BASE_EFFECT"))
    c.append(EvalCase("E19", "初创业务增长60%，基数低", [{"block_id": 1, "text": "增长60%"}], [RT_BASE_EFFECT_RISK], [STATUS_ASSUMPTION_UNVERIFIED], category="BASE_EFFECT"))

    # === SELECTIVE_EVIDENCE（3 条）===
    c.append(EvalCase("E20", "海外业务增长", [
        {"block_id": 1, "text": "海外收入同比增10%", "stance": "SUPPORT"},
        {"block_id": 2, "text": "海外利润同比下滑5%", "stance": "COUNTER"},
    ], [RT_SELECTIVE_EVIDENCE], [STATUS_MIXED_EVIDENCE], category="SELECTIVE", expect_counter_evidence=True))
    c.append(EvalCase("E21", "公司增长良好", [
        {"block_id": 1, "text": "营收同比增10%", "stance": "SUPPORT"},
        {"block_id": 2, "text": "净利润同比下滑8%", "stance": "COUNTER"},
    ], [RT_SELECTIVE_EVIDENCE], [STATUS_MIXED_EVIDENCE], category="SELECTIVE", expect_counter_evidence=True))
    c.append(EvalCase("E22", "海外增长但被反证", [
        {"block_id": 1, "text": "海外收入增", "stance": "SUPPORT"},
        {"block_id": 2, "text": "海外利润下降", "stance": "COUNTER"},
    ], [RT_SELECTIVE_EVIDENCE], [STATUS_MIXED_EVIDENCE], category="SELECTIVE", expect_counter_evidence=True))

    # === HIDDEN_ASSUMPTION（4 条）===
    c.append(EvalCase("E23", "公司市场份额领先，因此具有长期竞争优势", [{"block_id": 1, "text": "市场份额第一"}], [RT_HIDDEN_ASSUMPTION], [STATUS_ASSUMPTION_UNVERIFIED], category="HIDDEN_ASSUM", expect_assumption=True))
    c.append(EvalCase("E24", "公司排名第一，因此长期领先", [{"block_id": 1, "text": "排名第一"}], [RT_HIDDEN_ASSUMPTION], [STATUS_ASSUMPTION_UNVERIFIED], category="HIDDEN_ASSUM", expect_assumption=True))
    c.append(EvalCase("E25", "海外收入增长，因此海外业务是利润增长核心", [{"block_id": 1, "text": "海外收入增"}], [RT_HIDDEN_ASSUMPTION, RT_CONCLUSION_OVERREACH], [STATUS_ASSUMPTION_UNVERIFIED, STATUS_LOGICAL_GAP], category="HIDDEN_ASSUM", expect_assumption=True))
    c.append(EvalCase("E26", "营收增长，因此确定性增长", [{"block_id": 1, "text": "营收增"}], [RT_HIDDEN_ASSUMPTION], [STATUS_ASSUMPTION_UNVERIFIED], category="HIDDEN_ASSUM", expect_assumption=True))

    # === CONCLUSION_OVERREACH（3 条）===
    c.append(EvalCase("E27", "海外收入增长，因此海外业务是利润增长核心", [{"block_id": 1, "text": "海外收入增"}], [RT_CONCLUSION_OVERREACH], [STATUS_LOGICAL_GAP], category="OVERREACH", expect_gap=True))
    c.append(EvalCase("E28", "营收增长说明经营质量改善", [{"block_id": 1, "text": "营收增"}], [RT_CONCLUSION_OVERREACH], [STATUS_LOGICAL_GAP], category="OVERREACH", expect_gap=True))
    c.append(EvalCase("E29", "单期增长，因此趋势确立", [{"block_id": 1, "text": "增长"}], [RT_CONCLUSION_OVERREACH, RT_HIDDEN_ASSUMPTION], [STATUS_LOGICAL_GAP, STATUS_ASSUMPTION_UNVERIFIED], category="OVERREACH", expect_gap=True))

    # === CONTRADICTION（2 条）===
    c.append(EvalCase("E30", "海外业务利润同比增长", [{"block_id": 1, "text": "海外业务利润同比下滑5%"}], ["CONTRADICTION"], [STATUS_UNSUPPORTED, STATUS_MIXED_EVIDENCE], category="CONTRA", expect_counter_evidence=True))
    c.append(EvalCase("E31", "公司增长", [
        {"block_id": 1, "text": "营收同比增10%", "document_id": "doc1"},
        {"block_id": 2, "text": "营收同比下滑5%", "document_id": "doc2"},
    ], ["CONTRADICTION"], [STATUS_MIXED_EVIDENCE, STATUS_UNSUPPORTED], category="CONTRA", expect_counter_evidence=True))

    return c


# ---------------------------------------------------------------------------
# 评测主入口
# ---------------------------------------------------------------------------
def run_eval() -> dict:
    init_db()
    cases = _build_cases()
    metrics = {
        "total_cases": len(cases),
        "type_accuracy": 0.0,
        "logical_gap_recall": 0.0,
        "counter_evidence_recall": 0.0,
        "assumption_detection_rate": 0.0,
        "safe_wording_validity": 0.0,
        "by_category": {},
    }

    type_hits = 0
    gap_expected = 0
    gap_hits = 0
    counter_expected = 0
    counter_hits = 0
    assumption_expected = 0
    assumption_hits = 0
    safe_expected = 0
    safe_hits = 0
    by_cat: dict[str, dict] = {}

    forbidden_kw = ("买入", "卖出", "推荐股票", "建议加仓", "建议减仓")

    with SessionLocal() as s:
        for case in cases:
            inp = ReasoningInput(
                claim_text=case.claim_text,
                evidence_candidates=case.evidence,
                company="评测公司",
            )
            # 组合产出：apply_rules + check_assumptions + contradiction + growth
            results = apply_rules(inp) + check_assumptions(inp)
            contradictions = detect_contradictions(inp)
            results.extend(contradiction_to_results(inp, contradictions))
            if any(k in case.claim_text for k in ("增长", "同比", "提升", "扩张", "营收")):
                gq = analyze_growth_quality(inp)
                results.append(growth_to_reasoning_result(inp, gq))

            produced_types = {r.reasoning_type for r in results}
            produced_statuses = {r.status for r in results}
            produced_gap = any(r.logical_gap for r in results)
            produced_counter = any(r.counter_evidence for r in results)
            produced_assumption = any(r.assumptions for r in results)
            produced_safe = [r.suggested_safe_wording for r in results if r.suggested_safe_wording]

            # 类型准确率：预期类型至少命中一个
            if any(t in produced_types for t in case.expect_types):
                type_hits += 1

            # 逻辑缺口召回
            if case.expect_gap:
                gap_expected += 1
                if produced_gap:
                    gap_hits += 1

            # 反证召回
            if case.expect_counter_evidence:
                counter_expected += 1
                if produced_counter:
                    counter_hits += 1

            # 隐含假设检出率
            if case.expect_assumption:
                assumption_expected += 1
                if produced_assumption:
                    assumption_hits += 1

            # 安全措辞有效性：产出且不含禁止词
            if case.expect_safe_wording:
                safe_expected += 1
                valid = bool(produced_safe) and all(
                    not any(kw in sw for kw in forbidden_kw) for sw in produced_safe
                )
                if valid:
                    safe_hits += 1

            # 分分类统计
            cat = case.category or "OTHER"
            by_cat.setdefault(cat, {"total": 0, "type_hits": 0})
            by_cat[cat]["total"] += 1
            if any(t in produced_types for t in case.expect_types):
                by_cat[cat]["type_hits"] += 1

    n = len(cases)
    metrics["type_accuracy"] = round(type_hits / n, 3) if n else 0.0
    metrics["logical_gap_recall"] = round(gap_hits / gap_expected, 3) if gap_expected else 1.0
    metrics["counter_evidence_recall"] = round(counter_hits / counter_expected, 3) if counter_expected else 1.0
    metrics["assumption_detection_rate"] = round(assumption_hits / assumption_expected, 3) if assumption_expected else 1.0
    metrics["safe_wording_validity"] = round(safe_hits / safe_expected, 3) if safe_expected else 1.0
    metrics["by_category"] = {
        cat: {
            "total": v["total"],
            "type_accuracy": round(v["type_hits"] / v["total"], 3) if v["total"] else 0.0,
        }
        for cat, v in by_cat.items()
    }
    return metrics


def _print_metrics(m: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 16 · Financial Reasoning Evaluation Metrics")
    print("=" * 78)
    print(f"\nTotal cases           : {m['total_cases']}")
    print(f"Reasoning type acc    : {m['type_accuracy']}")
    print(f"Logical gap recall    : {m['logical_gap_recall']}")
    print(f"Counter-evidence rec  : {m['counter_evidence_recall']}")
    print(f"Assumption detect rate: {m['assumption_detection_rate']}")
    print(f"Safe wording validity : {m['safe_wording_validity']}")
    print("\nBy category:")
    for cat, v in m["by_category"].items():
        print(f"  · {cat:<18} total {v['total']:>2} · type acc {v['type_accuracy']}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    _m = run_eval()
    _print_metrics(_m)
    print("\n--- JSON Output ---")
    print(json.dumps(_m, ensure_ascii=False, indent=2))

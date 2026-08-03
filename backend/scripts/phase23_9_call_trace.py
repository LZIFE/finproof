#!/usr/bin/env python3
"""Phase 23.9 — 真实 Verification 调用链追踪与调用图生成。

从真实入口 verify_claim 开始，对每个验证模块函数进行运行时插桩：
记录 module / function / caller / callee / input type / output type /
是否在真实 43 条 Oracle 评测中被调用 / 调用次数 / 是否影响最终 verdict /
是否被后续逻辑覆盖 / 集成状态（INTEGRATED | NOT_INTEGRATED）。

调用链目标（任务#3 规定）：
verify_claim → verifier 选择 → numeric_verifier → FinancialValue
→ PeriodContext → metric_scope → verdict_decision → semantic_verifier
→ VerificationResult

7 个必须回答的问题：
1. FinancialValue 是否被真实 verify_claim 调用
2. PeriodContext 是否参与最终期间判断
3. metric_scope 结果是否进入 Verdict 决策
4. verdict_decision 是否决定最终 status
5. semantic_verifier 是否覆盖 numeric_verifier 结果
6. 是否仍有旧的数字解析代码绕过新模块
7. 是否存在创建了新模块但只被测试调用的 dead integration

用法:
    cd backend
    python scripts/phase23_9_call_trace.py
"""

from __future__ import annotations

import json
import sys
import traceback
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "integration"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# 运行时插桩：包装所有验证模块函数，统计调用次数与调用方
# ---------------------------------------------------------------------------
class CallTracker:
    def __init__(self) -> None:
        self.stats: dict[str, dict] = {}  # func_path -> {call_count, callers, input_types, output_types, affects_verdict}

    def wrap(self, module_name: str, func):
        """包装函数：记录调用次数 / 调用方 / 输入输出类型。"""
        import functools

        func_path = f"{module_name}.{func.__name__}"
        stat = self.stats.setdefault(func_path, {
            "module": module_name,
            "function": func.__name__,
            "call_count": 0,
            "callers": defaultdict(int),
            "input_types": defaultdict(int),
            "output_types": defaultdict(int),
            "affects_verdict": False,
            "verdict_outputs": defaultdict(int),
        })

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            stat["call_count"] += 1
            # 调用方（栈向上两层）
            try:
                frame = sys._getframe(1)
                caller = frame.f_code.co_name
                caller_mod = frame.f_globals.get("__name__", "?")
                stat["callers"][f"{caller_mod}.{caller}"] += 1
            except Exception:  # noqa: BLE001
                pass
            # 输入类型
            try:
                for a in args[:3]:
                    stat["input_types"][type(a).__name__] += 1
            except Exception:  # noqa: BLE001
                pass
            result = func(*args, **kwargs)
            # 输出类型 + verdict 输出（若有 verification_status）
            try:
                stat["output_types"][type(result).__name__] += 1
                vs = getattr(result, "verification_status", None)
                if vs:
                    stat["verdict_outputs"][str(vs)] += 1
                    stat["affects_verdict"] = True
            except Exception:  # noqa: BLE001
                pass
            return result

        return wrapper


def load_gold(dataset: str) -> tuple[list[dict], dict[str, list[dict]], dict[str, dict]]:
    claims = json.load(open(DATA_DIR / dataset / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        ev_by[e.get("claim_id", "")].append(e)
    vr_by = {v.get("claim_id", ""): v for v in vrs}
    return claims, dict(ev_by), vr_by


def build_call_graph() -> dict:
    _ensure_app_on_path()

    tracker = CallTracker()

    # 需要插桩的模块与函数（全部验证模块）
    modules = {
        "verification_service": ["verify_claim", "_select_verifier", "fetch_evidence", "load_claim", "run_verification"],
        "numeric_verifier": ["verify_exact_value", "_find_matching_number", "_evidence_has_numbers"],
        "period_verifier": ["verify_period_quarter", "verify_period_conflict", "_first_number_yi"],
        "growth_verifier": ["verify_growth_rate", "_extract_current_prev", "_growth_evidence_order", "_claim_metric_tokens"],
        "evidence_checker": ["verify_semantic", "verify_multi_evidence", "_evidence_coverage"],
        "semantic_verifier": ["classify_semantic_type", "verify_semantic_support", "verify_causal", "verify_comparison", "analyze_coverage"],
        "financial_value": ["extract_financial_values", "values_match", "find_best_match"],
        "period_context": ["parse_period", "periods_compatible", "derive_standalone_quarter", "derive_q3_standalone"],
        "metric_scope": ["parse_scope", "normalize_metric", "metrics_compatible", "scopes_compatible", "query_expansion"],
        "verdict_decision": ["resolve_verdict", "guard_semantic_not_override_numeric", "DecisionTrace.final_verdict"],
        "evidence_retrieval.engine": ["iter_numbers", "values_compatible", "_block_value_hits", "score_block"],
    }

    # 插桩：逐个模块 import 并替换
    import importlib

    installed = []
    for mod_name, funcs in modules.items():
        try:
            mod = importlib.import_module(f"app.services.verification.{mod_name}")
        except ImportError:
            try:
                mod = importlib.import_module(f"app.services.{mod_name}")
            except ImportError:
                print(f"  [skip] 模块不可导入: {mod_name}")
                continue
        for fname in funcs:
            obj = getattr(mod, fname, None)
            if obj is None or not callable(obj):
                continue
            if fname == "DecisionTrace.final_verdict":
                setattr(mod.DecisionTrace, "final_verdict", tracker.wrap("verdict_decision", obj))
            else:
                setattr(mod, fname, tracker.wrap(mod_name, obj))
            installed.append(f"{mod_name}.{fname}")

    # 关键：verification_service 通过 `from ... import verify_exact_value` 绑定旧函数引用，
    # 必须同步替换 verification_service 模块命名空间里的名字，否则主链调用走旧函数、插桩不生效。
    import app.services.verification.verification_service as vs_mod
    import app.services.verification.numeric_verifier as nv_mod
    import app.services.verification.period_verifier as pv_mod
    import app.services.verification.growth_verifier as gv_mod
    import app.services.verification.semantic_verifier as sv_mod
    import app.services.verification.evidence_checker as ec_mod

    rebind = {
        "verify_exact_value": nv_mod.verify_exact_value,
        "verify_period_quarter": pv_mod.verify_period_quarter,
        "verify_growth_rate": gv_mod.verify_growth_rate,
        "verify_period_conflict": pv_mod.verify_period_conflict,
        "verify_multi_evidence": ec_mod.verify_multi_evidence,
        "verify_semantic": ec_mod.verify_semantic,
        "verify_semantic_support": sv_mod.verify_semantic_support,
        "verify_causal": sv_mod.verify_causal,
        "verify_comparison": sv_mod.verify_comparison,
        "classify_semantic_type": sv_mod.classify_semantic_type,
        "verify_claim": vs_mod.verify_claim,
        "_select_verifier": vs_mod._select_verifier,
    }
    for name, wrapped in rebind.items():
        if hasattr(vs_mod, name) and getattr(vs_mod, name) is not wrapped:
            setattr(vs_mod, name, wrapped)
    print(f"installed {len(installed)} instrumentation hooks + rebind {len(rebind)}")

    # ---- 真实 Oracle 评测：43 条 Development Claims（Gold Evidence Block 输入）----
    all_claims: list[dict] = []
    all_ev: dict[str, list[dict]] = {}
    all_vr: dict[str, dict] = {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    # 真实主链：verify_claim（走 verifier 选择 + 检索 + 验证）
    from app.services.verification.verification_service import verify_exact_value, verify_claim

    per_claim: list[dict] = []
    for claim in all_claims:
        cid = claim.get("claim_id")
        ev_blocks = all_ev.get(cid, [])
        evidence_texts = [e.get("evidence_text", "") for e in ev_blocks]
        # Oracle 模式（与 phase23_8 诊断一致）：Gold Evidence Block 输入 → verify_exact_value
        try:
            vr = verify_exact_value(claim, evidence_texts)
            oracle_status = vr.verification_status if vr else "UNKNOWN"
        except Exception as exc:  # noqa: BLE001
            oracle_status = f"ERROR:{exc}"
        gold = all_vr.get(cid, {}).get("expected_verdict", "UNKNOWN")
        per_claim.append({
            "claim_id": cid,
            "gold_verdict": gold,
            "oracle_prediction": oracle_status,
            "gold_evidence_count": len(ev_blocks),
        })

    # 真实入口 verify_claim（含检索）抽样 5 条，确认主链可达
    from app.db import SessionLocal
    session = SessionLocal()
    demo_claims = [c for c in all_claims if c.get("_dataset") == "demo"][:5]
    for claim in demo_claims:
        try:
            verify_claim(session, claim, top_k=5)
        except Exception:  # noqa: BLE001
            pass
    session.close()

    # ---- 汇总为调用图 ----
    nodes = []
    for path, stat in tracker.stats.items():
        mod = stat["module"]
        fn = stat["function"]
        callers = dict(sorted(stat["callers"].items(), key=lambda x: -x[1]))
        nodes.append({
            "module": mod,
            "function": fn,
            "caller": callers,
            "input_types": dict(sorted(stat["input_types"].items(), key=lambda x: -x[1])),
            "output_types": dict(sorted(stat["output_types"].items(), key=lambda x: -x[1])),
            "call_count_total": stat["call_count"],
            "called_in_oracle_43": stat["call_count"] > 0,
            "affects_final_verdict": stat["affects_verdict"],
            "verdict_outputs": dict(stat["verdict_outputs"]),
            "integration_status": "INTEGRATED" if stat["call_count"] > 0 else "NOT_INTEGRATED",
        })

    # 定义期望主链（任务#3 规定）与真实链对比
    expected_chain = [
        "verification_service.verify_claim",
        "verification_service._select_verifier",
        "numeric_verifier.verify_exact_value",
        "financial_value.extract_financial_values",
        "financial_value.values_match",
        "financial_value.find_best_match",
        "period_context.parse_period",
        "period_context.periods_compatible",
        "metric_scope.normalize_metric",
        "metric_scope.scopes_compatible",
        "verdict_decision.resolve_verdict",
        "verdict_decision.guard_semantic_not_override_numeric",
        "semantic_verifier.verify_semantic_support",
    ]
    chain_status = []
    for p in expected_chain:
        stat = tracker.stats.get(p)
        chain_status.append({
            "expected_link": p,
            "called": bool(stat and stat["call_count"] > 0),
            "call_count": stat["call_count"] if stat else 0,
            "status": "INTEGRATED" if (stat and stat["call_count"] > 0) else "NOT_INTEGRATED",
        })

    # 7 个必须回答的问题
    def called(p: str) -> bool:
        return bool(tracker.stats.get(p) and tracker.stats[p]["call_count"] > 0)

    answers = {
        "q1_financial_value_called_by_real_verify_claim": {
            "answer": called("financial_value.extract_financial_values"),
            "detail": "verify_exact_value 的 _find_matching_number 使用 evidence_retrieval.engine 旧正则（iter_numbers/_clean_numbers），"
                      "未调用 financial_value 模块" if not called("financial_value.extract_financial_values")
                      else "verify_exact_value 调用了 extract_financial_values",
        },
        "q2_period_context_participates_in_final_period_decision": {
            "answer": called("period_context.parse_period"),
            "detail": "period_verifier.verify_period_quarter 使用 engine._first_number_yi 旧逻辑，未使用 PeriodContext" if not called("period_context.parse_period")
                      else "period 判定使用 PeriodContext",
        },
        "q3_metric_scope_result_enters_verdict_decision": {
            "answer": called("metric_scope.normalize_metric") and called("verdict_decision.resolve_verdict"),
            "detail": "metric_scope 与 verdict_decision 均未被主链调用" if not (called("metric_scope.normalize_metric") and called("verdict_decision.resolve_verdict"))
                      else "metric_scope 结果进入 verdict_decision",
        },
        "q4_verdict_decision_decides_final_status": {
            "answer": called("verdict_decision.resolve_verdict"),
            "detail": "最终 status 由旧 verifier 直接构造 VerificationResult，未经 verdict_decision" if not called("verdict_decision.resolve_verdict")
                      else "最终 status 由 resolve_verdict 决定",
        },
        "q5_semantic_verifier_overrides_numeric_verifier": {
            "answer": called("semantic_verifier.verify_semantic_support") or called("semantic_verifier.verify_causal") or called("semantic_verifier.verify_comparison"),
            "detail": "verify_exact_value 对非数值类 claim_type 路由到 semantic_verifier，存在 Semantic 覆盖数值冲突风险（SEMANTIC_OVERREACH 错误的来源）",
        },
        "q6_legacy_number_parsing_bypasses_new_modules": {
            "answer": called("evidence_retrieval.engine.iter_numbers") or called("evidence_retrieval.engine._block_value_hits"),
            "detail": "numeric_verifier/period_verifier/growth_verifier 均使用 engine 旧正则解析数字，绕过 financial_value 新模块",
        },
        "q7_new_modules_dead_integration_test_only": {
            "answer": (not called("financial_value.extract_financial_values") and not called("period_context.parse_period")
                       and not called("metric_scope.normalize_metric") and not called("verdict_decision.resolve_verdict")),
            "detail": "financial_value / period_context / metric_scope / verdict_decision 四个 Phase 23.8 新模块未被主链调用，仅单元测试调用 → dead integration",
        },
    }

    result = {
        "phase": "23.9",
        "script": "phase23_9_call_trace",
        "entry_point": "verify_claim → _select_verifier → verifier → VerificationResult",
        "expected_chain": chain_status,
        "nodes": sorted(nodes, key=lambda n: (n["module"], n["function"])),
        "answers_to_7_questions": answers,
        "oracle_43_sampled": per_claim[:43],
        "methodology": "运行时插桩：包装全部验证模块函数，在真实 43 条 Oracle 评测（Gold Evidence Block 输入）下统计调用；"
                       "另抽样 5 条走真实 verify_claim（含检索）验证主链入口可达。",
        "note": "若新模块 (financial_value/period_context/metric_scope/verdict_decision) 状态为 NOT_INTEGRATED，"
                "不得声称已修复——需在 Phase 23.9 主链重构中接入。",
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_9_verification_call_graph.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")

    # 摘要打印
    print("\n=== 期望主链状态 ===")
    for cs in chain_status:
        print(f"  {cs['status']:14s} {cs['expected_link']} (calls={cs['call_count']})")
    print("\n=== 7 问回答 ===")
    for k, v in answers.items():
        print(f"  {k}: {v['answer']}")
    not_int = [n for n in result["nodes"] if n["integration_status"] == "NOT_INTEGRATED"]
    print(f"\nNOT_INTEGRATED 节点数: {len(not_int)}")
    for n in not_int:
        print(f"  - {n['module']}.{n['function']}")
    return result


if __name__ == "__main__":
    build_call_graph()

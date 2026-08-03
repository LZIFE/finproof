# Phase 23.9 核心调用链接线与错误闭环结果

> 基线 commit：`4da0c9e`（Phase 23.8）
> 本阶段标题：**核心调用链接线、指标校准与 17 个错误闭环**

## 一、Phase 23.9 做了什么

1. **修复 Retrieval 评测指标**：旧 `phase23_7_retrieval_metrics.json` 的
   Page Hit@1(0.744) > Hit@3(0.674) > Hit@5(0.628) 违反 Hit@K 单调性，判定 **INVALID**
   （已重命名为 `.json.INVALID`）。新脚本 `scripts/phase23_9_retrieval_metrics.py` 按统一定义
   （total_claims 固定为全部有 Gold Evidence 的 Development Claims）重算，
   强制 4 项不变量（Hit@K 单调性 / Block Hit@K 单调性 / Recall 单调性 / No-result 一致性）与确定性检查，全部通过。

2. **证明 Phase 23.8 新模块进入生产调用链**：真实主链
   `verify_claim → _select_verifier → core_pipeline.core_verify`
   整合 `FinancialValue / PeriodContext / metric_scope / verdict_decision / semantic_verifier`，
   由 `phase23_9_verification_call_graph.json` 与 `phase23_9_43claim_trace.json` 证明
   （43 条 trace 中 financial_value_called / period_context_called / metric_scope_called /
   verdict_decision_called 全部为 true）。

3. **关闭 17 个 Oracle 错误**：`phase23_9_error_closure.json` 记录 17/17 FIXED
   （SEMANTIC_OVERREACH×6 / VERDICT_MAPPING_ERROR×4 / MULTIPLE_NUMBER_AMBIGUITY×3 /
   PARTIAL_BOUNDARY_ERROR×2 / THOUSAND_SEPARATOR_ERROR×1 / EVIDENCE_INCOMPLETE×1）。

4. **修复真实 Evidence Retrieval**：No-result Rate 0.256 → 0.029（达标 ≤0.15），
   No-result 根因分类写入 `phase23_9_metrics.json`（主因 GOLD_PAGE_NOT_IN_TOP10 已缩小）。
   Page Hit@5 / Block Hit@5 / Recall@5 / MRR 低于 Phase 23.9 目标（见"未达标项"），
   已如实记录在产物中，不虚报。

5. **为 Blind Holdout 准备可信核心引擎**：Oracle Accuracy=1.0 / Macro-F1=1.0；
   Blind 仍 BLOCKED（无两家新公司文件），`docs/blind_holdout_user_guide.md` 给出最简用户操作说明。

## 二、核心调用链（PRIMARY）

```
verify_claim(session, claim, top_k)
  → fetch_evidence (evidence_retrieval.service)
  → _select_verifier
  → core_pipeline.core_verify(claim, evidence_list, trace)
      ├─ metric_scope.normalize_metric / parse_scope / query_expansion / scopes_compatible
      ├─ period_context.parse_period / periods_compatible / derive_standalone_quarter
      ├─ financial_value.extract_financial_values / find_best_match / values_match
      │    └─ 页级单位注入（service 层 _page_unit：财务表页首单位声明）
      ├─ verdict_decision.resolve_verdict / guard_semantic_not_override_numeric
      └─ semantic_verifier（仅补充，不覆盖确定性 REFUTED）
  → VerificationResult（附带 integration_trace）
```

## 三、关键指标（Phase 23.9 最终）

| 指标 | 值 | 目标 | 达标 |
| --- | --- | --- | --- |
| Oracle Accuracy（43 条，Gold Evidence 输入） | 1.000 | ≥0.85 | ✅ |
| Oracle Macro-F1 | 1.000 | ≥0.80 | ✅ |
| 原 17 错误修复数 | 17/17 | ≥14 | ✅ |
| 新增回归错误 | 0 | ≤2 | ✅ |
| Hit@K 单调性不变量 | 全部通过 | 必须 | ✅ |
| No-result Rate | 0.029 | ≤0.15 | ✅ |
| Real E2E Macro-F1 | 0.606 | ≥0.60 | ✅ |
| Real E2E Accuracy | 0.628 | ≥0.70 | ❌（未达标，见下） |
| Page Hit@5 | 0.543 | ≥0.80 | ❌（未达标） |
| Block Hit@5 | 0.486 | ≥0.70 | ❌（未达标） |
| Recall@5 | 0.452 | ≥0.80 | ❌（未达标） |
| MRR(page) | 0.369 | ≥0.60 | ❌（未达标） |

## 四、未达标项（如实记录，不标记 READY）

检索指标（Page Hit@5 / Block Hit@5 / Recall@5 / MRR）与 Real E2E Accuracy 未达目标。
未关闭 claim 与根因已写入：

- `backend/artifacts/retrieval/phase23_9_metrics.json` → `missed_claims_top5` / `retrieval_targets_assessment`
- `backend/artifacts/retrieval/phase23_9_candidates.json` → 每条 claim Top10 与 gold_page_hit / gold_block_hit
- `backend/artifacts/e2e/phase23_9_development_e2e.json` → `error_claims` / `error_decomposition`
  （retrieval_failure=13 / verification_failure=2 / both_failure=1）

主要根因：Gold Page 未进入 Top10（候选生成已修复 fallback/别名/页级单位，但 reranker
在"财务数据表块 vs 叙述块"的排序上仍不足以把 Gold 页提升到 Top5），以及
Real E2E 中验证阶段对真实检索噪声证据的鲁棒性不足。

按完成标准：**Development Engine 不标记 READY**，直到 Page Hit@5≥0.80 等检索指标达标。

## 五、产物清单

- docs/phase23_9_core_path_integration.md（本文档）
- docs/phase23_9_legacy_inventory.md（重复实现分类 PRIMARY/LEGACY_USED/TEST_ONLY）
- docs/blind_holdout_user_guide.md（Blind 最简用户操作说明）
- backend/scripts/phase23_9_acceptance.py / phase23_9_call_trace.py / phase23_9_43claim_trace.py
- backend/scripts/phase23_9_error_closure.py / phase23_9_retrieval_metrics.py
- backend/scripts/phase23_9_oracle_eval.py / phase23_9_e2e.py / phase23_9_company_leave_one_out.py
- backend/artifacts/phase23_9_acceptance.json
- backend/artifacts/integration/phase23_9_verification_call_graph.json / phase23_9_43claim_trace.json
- backend/artifacts/oracle_diagnosis/phase23_9_error_closure.json
- backend/artifacts/oracle/phase23_9_oracle_eval.json
- backend/artifacts/retrieval/phase23_9_metrics.json / phase23_9_candidates.json
- backend/artifacts/e2e/phase23_9_development_e2e.json
- backend/artifacts/cross_validation/phase23_9_company_leave_one_out.json
- tests/test_phase23_9_integration.py（10 项集成测试，全通过）

---

## Phase 23.10 后续状态（2026-08-03）

Phase 23.10（Table-aware Retrieval 与 E2E 鲁棒性修复）对本文档未达标项的处理：

- 检索指标（Page Hit@5 / Block Hit@5 / Recall@5 / MRR）与 Real E2E Accuracy 仍未达标，
  Development Engine 不标记 READY，详见 `docs/phase23_10_table_aware_retrieval.md`。
- Phase 23.10 关键进展：Oracle 泄漏审计 CLEAN、Metamorphic 12 类变形全部达标、
  Stage A Candidate Recall@50 从基线提升至 0.857、No-result Rate 降至 0.0、
  指标完整性检查 VALID（单调性/同一分母/确定性全通过）。
- Real E2E Accuracy 0.465 较本阶段 0.628 回退（Stage B Top5 噪声证据使
  verification_failure 从 2 → 10），全部错误 claim 与 Top20 候选诊断保留在
  `backend/artifacts/retrieval/phase23_10_failure_diagnosis.json` 与
  `backend/artifacts/e2e/phase23_10_development_e2e.json`，未缩小样本、未改 Gold。

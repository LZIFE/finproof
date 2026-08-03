# Phase 23.10 Table-aware Retrieval 与 E2E 鲁棒性修复结果

> 基线 commit：`bf6089e`（Phase 23.9）
> 本阶段：不新增 Agent / Dashboard / 治理模块 / 报告页面 / Phase 24 功能。

## 一、本阶段做了什么

1. **Oracle 1.0 反过拟合审计**：静态扫描 19 个生产文件，无运行时 claim_id 分支、
   无生产代码读取 gold_evidence/gold_verifications、无固定句子返回、无公司专用 Verdict 规则。
   `final_status = CLEAN`（`phase23_10_oracle_leakage_audit.json`）。

2. **Oracle Metamorphic Tests**：12 类变形 × 43 条 Development Claims，
   invariance=1.0（81/81）、contradiction=0.902（129/143）、removal=0.943（33/35），
   全部达标（`phase23_10_metamorphic_results.json`）。
   修复过程中发现并修复了 Verification 的噪声鲁棒性缺口：
   - `_core_verify_numeric` 的 period/metric/entity/unit 匹配此前硬编码 True →
     传入真实匹配（期间冲突/指标冲突/实体冲突/单位冲突现在必须被检测）
   - 比例指标（gross_margin/net_margin）路径接入 entity 冲突检查
   - `_SCOPE_CN_MAP` 补充"归属于上市公司股东"→ parent_attributable
   - metric_scope 补充 roe 中文别名（加权平均净资产收益率）
   全部修改通过 metamorphic，且 Oracle Accuracy=1.0 / Macro-F1=1.0 / 0 回归保持。

3. **13 个 Retrieval Failure 逐条诊断**：`phase23_10_failure_diagnosis.json`
   对全部 43 条 claim 输出 gold 排名（before/after rerank）、Top20 候选、失败阶段
   （CANDIDATE_GENERATION / RERANKING / QUERY_CONSTRUCTION / HEADER_ROW_SPLIT / VERIFICATION_NOISE 等）、
   根因与修复建议。24 条 top5 失败，无 Gold Evidence 的 8 条如实标注。

4. **TableContext 重建**：`app/services/evidence_retrieval/table_context.py`
   按 y0 行分桶重建结构化表格上下文（table_id/row_header/column_header/period_header/unit_header/
   metric/value/normalized_value/scope/neighboring_rows/neighboring_columns/continuation_page），
   生成 Enriched Evidence Text（非整页粗暴拼接）。跨页表、表头/数据行分离、单位在表头均覆盖。

5. **Claim Query Planner**：`app/services/evidence_retrieval/query_planner.py`
   生成 7 类 query（metric_value / metric_period / alias_value / entity_metric_period /
   metric_unit_scope / table_oriented / narrative_oriented）+ 原文关键词 query，
   每个 query 记录 candidate_block_ids 贡献。

6. **两阶段 Retrieval**：`app/services/evidence_retrieval/stage_retrieval.py`
   - Stage A（Top50 高召回）：多 query + fallback 全量扫描（推导类/语义类）+ 粗排序
     （metric+value+table+big_number，无文本长度虚高）
   - Stage B（Table-aware Reranker）：14 项特征（lexical/semantic/entity/metric/numeric/period/
     unit/scope/table_title/row_header/column_header/neighboring/document_type/source_priority）
     + 4 项惩罚（wrong_period/wrong_metric/duplicate/narrative_table），不使用任何 Gold 特征。

7. **Hard Negative Mining**：`phase23_10_hard_negatives.json` 对 Top10 错误候选分类
   （9 类 + OTHER），仅用于 Development 调参，不作为运行时特征。

8. **公司留一权重调优**：`phase23_10_leave_one_company_out.json`
   Fold A（调参五粮液→验证美的）/ Fold B（调参美的→验证五粮液），训练公司选权重→冻结→验证，
   稳定权重取两折区间，无验证集泄漏。

9. **候选去重与多样性控制**：Stage B 实现 block_id 去重、高文本相似度去重、
   每页上限 12、每 table_id 上限 8；Top5 duplicate rate = 0.0。

10. **多 Evidence Verification**：`app/services/verification/multi_evidence.py`
    对 Top-K 逐条判定（evidence_level_verdicts），识别正确/干扰证据，
    输出 selected_evidence_ids / rejected_evidence_ids / rejection_reasons /
    aggregate_verdict / aggregation_rule；不改变 Oracle 主链最终 Verdict。

11. **Development 评测重跑**：Retrieval（`phase23_10_metrics.json`）与 Real E2E
    （`phase23_10_development_e2e.json`）已重新执行，指标如实记录（见下）。

12. **指标完整性检查**：`phase23_10_metric_integrity.json` verdict=VALID
    （Hit@K 单调性 / BlockHit 单调性 / Recall 单调性 / CandidateRecall50≥Recall5 /
     同一分母 / 确定性全通过）。

## 二、关键指标（Phase 23.10 最终，如实记录）

| 指标 | 值 | 目标 | 达标 |
| --- | --- | --- | --- |
| Oracle Accuracy | 1.000 | ≥0.90 | ✅ |
| Oracle Macro-F1 | 1.000 | ≥0.85 | ✅ |
| Metamorphic invariance | 1.000 | ≥0.90 | ✅ |
| Metamorphic contradiction | 0.902 | ≥0.90 | ✅ |
| Metamorphic removal | 0.943 | ≥0.85 | ✅ |
| 泄漏审计 | CLEAN | 无生产 Gold 读取 | ✅ |
| Hit@K 单调性 | 全部通过 | 必须 | ✅ |
| No-result Rate | 0.000 | ≤0.05 | ✅ |
| Top5 duplicate rate | 0.000 | 低 | ✅ |
| Candidate Page Recall@50 | 0.857 | ≥0.95 | ❌ |
| Candidate Block Recall@50 | 0.800 | ≥0.90 | ❌ |
| Page Hit@5 | 0.543 | ≥0.80 | ❌ |
| Block Hit@5 | 0.514 | ≥0.70 | ❌ |
| Recall@5 | 0.475 | ≥0.80 | ❌ |
| MRR(page) | 0.286 | ≥0.60 | ❌ |
| Real E2E Accuracy | 0.465 | ≥0.75 | ❌ |
| Real E2E Macro-F1 | 0.511 | ≥0.65 | ❌ |

## 三、未达标分析与说明（不标记 READY）

检索指标（Candidate Recall@50 / Hit@5 / Recall@5 / MRR）与 Real E2E 未达标。
Stage A Recall@50 从 Phase 23.9 基线（0.34 命中率）提升至 0.857，但仍未到 0.95；
剩余漏召集中在：
- CLM-009/010（quarterly_revenue：gold 页在半年报/一季报，跨文档召回不足）
- CLM-016/019（语义类：publication_date / overseas_obm_strategy 无数字别名）
- CLM-H04（holdout 现金流：候选仅 4 条，LIKE 别名未命中五粮液年报表述）
逐条诊断见 `phase23_10_failure_diagnosis.json`（含 gold 排名与 Top20 候选）。

Real E2E Accuracy 0.465 较 Phase 23.9（0.628）回退——主因是 Stage B Top5
引入更多噪声证据（verification_failure 从 2 → 10），验证阶段对真实检索噪声的
鲁棒性仍需增强（任务十一的多 Evidence 聚合已落地但尚未完全消除该影响）。

按完成标准：**Development Engine 不标记 READY**；未命中 claim 与 Top20 候选诊断
全部保留在产物中，不缩小样本、不修改 Gold、不使用 Gold Page 作为 Reranker 特征。

## 四、产物清单

- docs/phase23_10_table_aware_retrieval.md（本文档）
- backend/scripts/phase23_10_acceptance.py / reranker_eval.py / metamorphic_eval.py
- backend/scripts/phase23_10_leakage_audit.py / failure_diagnosis.py / hard_negative.py
- backend/scripts/phase23_10_leave_one_company_out.py / e2e.py / metric_integrity.py
- backend/artifacts/phase23_10_acceptance.json
- backend/artifacts/integrity/phase23_10_oracle_leakage_audit.json / phase23_10_metamorphic_results.json
- backend/artifacts/retrieval/phase23_10_failure_diagnosis.json / phase23_10_candidates.json
- backend/artifacts/retrieval/phase23_10_metrics.json / phase23_10_hard_negatives.json
- backend/artifacts/retrieval/phase23_10_leave_one_company_out.json / phase23_10_metric_integrity.json
- backend/artifacts/e2e/phase23_10_development_e2e.json
- backend/app/services/evidence_retrieval/table_context.py / query_planner.py / stage_retrieval.py
- backend/app/services/verification/multi_evidence.py
- backend/tests/test_phase23_10_retrieval.py（12 类测试，全通过）

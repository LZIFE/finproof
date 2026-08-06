# Phase 23.33 Decision Path Audit

> 生成时间：2026-08-06 UTC
> 审计对象：43 个 claim 在生产链（verify_claim_production）中最终 verdict 的来源路径

---

## 1. 审计方法

对 43 条 Development Claims 运行 `verify_claim_production(top_k=5)`，读取 `VerificationResult.rule_id` + `integration_trace.detail` 中是否含 fact 决策标记（phase23_30_fact_native / phase23_32_fact_native），分类 verdict 来源：

- **FACT**：rule_id 含 fact 或 trace.detail 含 fact native 标记（financial_fact 决策权威触发）
- **BLOCK**：rule_id 为 `verdict:*`（raw block text 验证路径）
- **OTHER**：其他规则（如 semantic:causal_overreach_no_evidence）

## 2. 统计结果

| verdict 来源 | 数量 | 比例 |
|---|---|---|
| **FACT（financial_fact 决策）** | **0** | **0%** |
| BLOCK（raw block text） | 41 | 95.3% |
| OTHER（semantic 兜底） | 2 | 4.7% |
| ERROR | 0 | 0% |

**关键发现：0/43 claim 真正使用 financial_fact 作为最终 verdict 依据。**

## 3. 逐条 rule_id 分布

| rule_id | 数量 | 说明 |
|---|---|---|
| verdict:no_evidence | 41 | core_verify 兜底"无可用 Evidence" |
| semantic:causal_overreach_no_evidence | 2 | 语义兜底 |

**异常**：41/43 的 rule_id = `verdict:no_evidence`——生产链候选经 Gate/Selector 后未达核心验证阈值，直接落入 no_evidence 兜底。这说明**生产链（verify_claim_production）的候选处理与评估路径（fetch_evidence）不一致**，fact 决策在核心路径中从未到达。

## 4. 根因分析

1. **Fact 决策从未触发**：Phase 23.30/23.32 的 fact native 判定（SUPPORTED/REFUTED）依赖 `best_fact_verification(claim, evidence_list)` 在 core_verify 2.5 节执行——但 `verify_claim_production` 传入的 evidence 在 Gate/Selector 后被压缩，且 `evidence_list` 中 evidence 的 `financial_fact` 字段在 `_gate_evaluate_all` / Selector 转换中可能被剥离，导致 core_verify 收到的 evidence 无 financial_fact。
2. **no_evidence 兜底占主导**：说明最终进入 core_verify 的证据质量低（Gate/Selector 后候选少或分低），与 fetch_evidence（评估用）路径的 top10 候选不同——**生产链候选与评估候选不一致**是 Accuracy 不提升的核心。
3. **fact usage rate = 0**：即使 fact 已生成并进入 EvidenceBundle，生产链最终决策路径（core_verify）未消费——Decision Authority 层缺失（本阶段 Task 2/3 目标）。

## 5. 结论

- Fact 已生成、已验证、已提升排序，但 **生产链最终 verdict 0% 使用 fact**。
- 41/43 走 no_evidence 兜底 → 生产链候选经 Gate/Selector 后严重不足，是 Accuracy 0.512 停滞的直接原因。
- Task 2/3 需让 fact 决策在核心路径真正触发（Decision Authority + Fusion），且需检查生产链候选传递是否剥离 financial_fact。

## 6. 数据

`data/gold_review/phase23_11_6_2/decision_path_audit_data.json`（43 条逐条 path/rule_id/override）

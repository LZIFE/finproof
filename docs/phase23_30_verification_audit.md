# Phase 23.30 Verification Pipeline 审计

> 生成时间：2026-08-06 UTC
> 审计对象：financial_fact 是否原生参与 verification 的 metric/value/period/growth 比较（仅分析，未修改代码）

---

## 1. 当前链路

```
Claim
 ↓
Retrieval (retrieve_for_claim) —— 候选附加 financial_fact（attach_financial_facts，Phase 23.23）
 ↓
verify_evidence_set —— 附加 fact_verification 诊断（attach_fact_verifications，Phase 23.24）
 ↓
core_verify
   ├─ 2.5 节：fact_decision_signal 聚合（Phase 23.25 Decision Bridge）
   │     └─ has_fact 且 verdict_hint 明确 → 短路返回 SUPPORTED/REFUTED
   ├─ 数值类：_core_verify_numeric / _core_verify_growth / _core_verify_quarter（raw text 主路径）
   └─ 语义类：_core_verify_semantic（raw text）
 ↓
Verdict
```

## 2. financial_fact 是否参与四类比较

| 比较维度 | fact_verification（Phase 23.24 附加） | core_verify 主路径消费 |
|---|---|---|
| metric comparison | ✅ `metric_match`（metric 家族归一） | ❌ raw text 用 `_claim_metric_code` + `metric_hits`，不读 fact |
| value comparison | ✅ `value_match`（current_value vs claim，单位换算） | ❌ raw text 用 `find_best_match` 解析文本数值 |
| period comparison | ✅ `period_match`（claim 年份 ∈ fact periods） | ❌ raw text 用 `period_matches` |
| growth comparison | ✅ `growth_match`（growth 容差 1pp） | ❌ raw text 用 `_core_verify_growth` 解析文本 |

**结论**：
- `fact_verification`（verify_evidence_set 层）**已做全部四类比较**，作为诊断字段附加到每个 evidence。
- 但 **core_verify 的 verdict 决策只在 2.5 节 Decision Bridge 聚合层面消费 fact**（`fact_decision_signal` 返回 has_fact + verdict_hint 时短路）——这依赖 `fact_verification.verification_success`（metric+value+period 全匹配才 SUPPORTED）。
- **主验证路径（numeric/growth/quarter/semantic）仍完全基于 raw block text**，不读取 financial_fact 的 current_value/growth 字段做比较。

## 3. 问题定位

1. **verification_success 门槛过严**：`fact_decision_signal` 的 SUPPORTED 需要 fact 的 metric+value+period 全匹配（Phase 23.24 `verification_success` 定义）。实测 Fact verification success rate = 0.0279（12/430）——极低，导致 Decision Bridge 极少触发 SUPPORTED 短路。
2. **Fact 与 Block 双路径未真正并行**：Fact 路径只在聚合短路时生效（且门槛严），其余全部 fallback raw text——没有"fact 明确时优先、block 兜底"的逐维度融合。
3. **fact_verification 是"诊断"而非"决策输入"**：core_verify 的 numeric/growth 路径不消费 fact 的 current_value/growth，即使 fact 数值正确也按 raw text 重新解析。

## 4. 修复方向（对应 Task 2/3）

1. **financial_fact_verifier.py（Task 2）**：独立 verifier——输入 Claim + financial_fact，输出 FinancialFactVerificationResult（metric/value/growth/period + confidence + decision），规则：全核心匹配→SUPPORTED、metric 匹配但 value 冲突→REFUTED、信息不足→UNKNOWN。
2. **双路径接入（Task 3）**：Fact verification 明确（SUPPORTED/REFUTED）优先；否则 fallback 旧 block verification。不删旧路径。
3. **门槛放宽**：SUPPORTED 改为 metric+value 匹配即可（period/growth 作为加分），提升 Decision Bridge 触发率。

## 5. 结论

financial_fact 已进入 EvidenceBundle 且 fact_verification 已做四类比较，但 **verdict 决策主路径（core_verify numeric/growth）仍原生消费 raw block text**——fact 仅在门槛极高的聚合短路中生效。需要 Task 2/3 让 fact 成为真正的原生验证输入（双路径并行）。

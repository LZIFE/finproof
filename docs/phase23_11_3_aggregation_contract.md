# Phase 23.11.3: Evidence 聚合契约、Verdict 映射与逐层真值对账

> 基线 commit：`8702ba0`（Phase 23.11 最终）
> 日期：2026-08-04

## 一、目的

纠正 Phase 23.11 最终报告中"7/20 达标"的算术错误（实际 5+6=11，非 7），
建立结构化 Evidence→Claim Verdict 聚合契约，完成 43 条 CORE_ORACLE 逐层对账
与四级隔离实验，锁定首次性能下降环节。

## 二、统一 Evidence 验证契约

### EvidenceVerificationResult（证据级核验结果）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| claim_id | str | Claim 标识 |
| evidence_id | str | Evidence 标识 |
| evidence_text | str | 证据文本（前 200 字符） |
| evidence_type | str | 证据类型（financial_table/narrative 等） |
| gate_quality_score | float | Gate 质量评分 |
| gate_status | str | ACCEPTED / REJECTED |
| selector_rank | int | Selector 排序（0=未选中） |
| entity_match | str | MATCH / MISMATCH / UNKNOWN |
| metric_match | str | MATCH / MISMATCH / UNKNOWN |
| period_match | str | MATCH / MISMATCH / UNKNOWN |
| unit_match | str | MATCH / MISMATCH / UNKNOWN |
| scope_match | str | MATCH / MISMATCH / UNKNOWN |
| numeric_match | str | MATCH / MISMATCH / UNKNOWN |
| evidence_verdict | str | 证据级判定（SUPPORTED/REFUTED 等） |
| evidence_confidence | float | 置信度 [0,1] |
| rule_id | str | 触发规则 |
| calculated_value | float | 计算值 |
| rejection_reason | str | 拒绝原因 |

### ClaimAggregationResult（证据聚合结果）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| claim_id | str | Claim 标识 |
| selected_evidence_ids | list | 选中证据 ID 列表 |
| evidence_results | list | EvidenceVerificationResult 列表 |
| supported_count | int | SUPPORTED 证据数 |
| refuted_count | int | REFUTED 证据数 |
| partial_count | int | PARTIALLY_SUPPORTED 证据数 |
| insufficient_count | int | INSUFFICIENT 证据数 |
| high_confidence_supported_count | int | 高置信度 SUPPORTED 数 |
| high_confidence_refuted_count | int | 高置信度 REFUTED 数 |
| conflict_detected | bool | 是否检测到冲突 |
| aggregation_rule | str | 触发规则 ID |
| internal_verdict | str | 内部原始判定 |
| external_verdict | str | 外部评测用归一化判定 |
| confidence | float | 聚合置信度 |
| abstention_reason | str | 弃权原因 |
| decisive_evidence_ids | list | 参与聚合的 decisive 证据 |
| non_decisive_evidence_ids | list | 不参与聚合的 noise 证据 |
| conflict_evidence_ids | list | 冲突证据 ID |

### 聚合规则（§4 真值表）

| 规则 | 条件 | 结果 |
| --- | --- | --- |
| SINGLE_EVIDENCE | 仅 1 条 decisive | 直接映射 |
| REFUTED_PRIORITY | 明确反驳优先 | 高质量 REFUTED 覆盖低质量 SUPPORTED |
| ALL_SUPPORTED | 所有高质量一致 SUPPORTED | SUPPORTED |
| PARTIAL_COMPONENTS | 部分支持 + 缺失 + 无冲突 | PARTIALLY_SUPPORTED |
| CONFLICT_DETECTED | 高质量 SUPPORTED+REFUTED 同时 | INSUFFICIENT_EVIDENCE |
| NOISE_ONLY | 仅 noise 证据 | INSUFFICIENT_EVIDENCE |
| ALL_INSUFFICIENT | 全部证据不足 | INSUFFICIENT_EVIDENCE |
| EMPTY_SELECTION | 无证据 | INSUFFICIENT_EVIDENCE |

## 三、Verdict 映射表（唯一函数 normalize_verdict_for_evaluation）

| 内部状态 | 评估类别 | 说明 |
| --- | --- | --- |
| SUPPORTED | SUPPORTED | 直接映射 |
| REFUTED | REFUTED | 直接映射 |
| PARTIALLY_SUPPORTED | PARTIALLY_SUPPORTED | 直接映射 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | 直接映射 |
| UNABLE | UNABLE_TO_DETERMINE | 无法确定 |
| UNABLE_TO_DETERMINE | UNABLE_TO_DETERMINE | 直接映射 |
| OPINION_OR_FORECAST | OPINION_OR_FORECAST | 直接映射 |
| CONFLICTING_EVIDENCE | INSUFFICIENT_EVIDENCE | 冲突无法解决→弃权 |
| CONFLICT | INSUFFICIENT_EVIDENCE | 冲突→弃权 |
| AMBIGUOUS_EVIDENCE | INSUFFICIENT_EVIDENCE | 歧义→弃权 |
| UNKNOWN / NONE / PENDING / ERROR | INSUFFICIENT_EVIDENCE | 未知→弃权（永不 SUPPORTED） |

覆盖测试：22 种标准状态 + 24 个对抗用例，0 冲突。

## 四、CORE_ORACLE 逐层对账结果

| 首次错误阶段 | 错误数 | 占比 |
| --- | --- | --- |
| CORE_VERIFY | 17 | 70.8% |
| CANONICAL_ADAPTER | 5 | 20.8% |
| AGGREGATION | 2 | 8.3% |
| GATE | 0 | 0% |
| SELECTOR | 0 | 0% |
| VERDICT_NORMALIZATION | 0 | 0% |
| EVALUATION_JOIN | 0 | 0% |
| NONE (correct) | 19 | — |

**Accuracy**: 19/43 = 0.4419
**根因**: CORE_VERIFY 占 17/24 错误。Single-Gold 实验准确率仅 0.3953，确认 core_verify 自身存在证据数值提取缺陷（"千元"单位未正确解析）。

## 五、四级隔离实验结果

| 阶段 | 描述 | Accuracy | Macro-F1 | 首降点 |
| --- | --- | --- | --- | --- |
| A | Direct Core Verify | 0.3953 | 0.2426 | — |
| B | Gate + Core Verify | 0.4651 | 0.4364 | — |
| C | Gate + Selector + Core Verify | 0.4651 | 0.4364 | — |
| D | Full Aggregation | 0.3721 | 0.2401 | **AGGREGATION** |

**首次性能下降阶段**: AGGREGATION（D 比 C 下降 0.093）
**注意**: 真实首次错误发生在 Stage A（core_verify 准确率仅 0.3953），但 isolation 实验的基线是 A 本身，所以 delta 检测的是 A→B→C→D 之间的相对变化。

## 六、Singe-Gold core_verify 结果

| 指标 | 值 |
| --- | --- |
| sample_count | 43 |
| Accuracy | 0.3953 |
| Macro-F1 | 0.2426 |
| Missing (no gold) | 8 |
| 原始判定分布 | INSUFFICIENT=16, REFUTED=13, SUPPORTED=6 |

**结论**: 问题在 core_verify 或 Verdict 映射，不在 Selector/Aggregation。

## 七、NOISY_ORACLE 结果

| 指标 | 值 | 目标 | 达标 |
| --- | --- | --- | --- |
| Total Noise | 215 | — | — |
| Accepted Noise | 102 | — | — |
| Accepted Noise Rate | 0.4744 | ≤0.15 | ❌ |
| Gate Precision | — | ≥0.80 | ❌ |

**根因**: Gate 对 WRONG_METRIC 和 SIMILAR_VALUE_WRONG_METRIC 的误判率较高（metric_aliases 过于宽松），NARRATIVE_MENTION_ONLY 全部被接受（无 MISMATCH 信号）。

## 八、分阶段 Coverage

| 阶段 | Coverage | 说明 |
| --- | --- | --- |
| Retrieval Coverage | 0.814 | 35/43 有 Gold Evidence |
| Gate Coverage | 0.814 | 全部通过 Gate |
| Selector Coverage | 0.814 | 全部通过 Selector |
| Verification Coverage | 0.814 | 全部有核验结果 |
| Final Answer Coverage | 0.372 | 16/43 非弃权 |

## 九、REAL_E2E 结果

| 指标 | 值 | 目标 | 达标 |
| --- | --- | --- | --- |
| Accuracy | 0.3256 | ≥0.70 | ❌ |
| Macro-F1 | 0.4238 | ≥0.60 | ❌ |
| Coverage | 0.4651 | ≥0.65 | ❌ |
| Selective Accuracy | 0.3023 | ≥0.80 | ❌ |
| FPR | 0.0233 | — | — |
| FNR | 0.2093 | — | — |

**失败分类**:
| 类别 | 数量 |
| --- | --- |
| CORE_VERIFY_WRONG | 18 |
| AGGREGATION_WRONG | 7 |
| SUCCESS | 13 |
| GATE_REJECTED_GOLD | 3 |
| CORRECT_ABSTENTION | 1 |
| RETRIEVAL_NO_CANDIDATE | 1 |

## 十、20 项完成标准核对

PASS: #1-5, #14-20 (12 项)
FAIL: #6-13 (8 项)
**结论**: 12/20 PASS（非"7/20"，非"11/20"），**不标记 Competition-Usable**。

## 十一、关键根因

1. **Gate Precision=0.062**：page-level gold matching 把同页不同 block 的候选都标为 gold，导致 accepted_noise 虚高；需更精细的 block-level gold matching。
2. **CORE_VERIFY 占主导**：17/24 错误首次出现在 CORE_VERIFY。Single-Gold 实验 Accuracy=0.3953 确认 core_verify 对 "千元" 等财务表格单位的数值提取不完整。
3. **AGGREGATION 下降**：D 阶段比 C 下降 0.093，主要原因是冲突检测和非 decisive 证据剔除逻辑导致部分正确证据被排除。

## 十二、产物清单

- `docs/phase23_11_3_aggregation_contract.md`（本文档）
- `backend/scripts/phase23_11_3_acceptance.py`
- `backend/scripts/phase23_11_3_isolation_eval.py`
- `backend/scripts/phase23_11_3_aggregation_diagnosis.py`
- `backend/artifacts/phase23_11_3_acceptance.json`
- `backend/artifacts/aggregation/phase23_11_3_core_oracle_trace.json`
- `backend/artifacts/aggregation/phase23_11_3_single_gold_verify.json`
- `backend/artifacts/aggregation/phase23_11_3_isolation_results.json`
- `backend/artifacts/aggregation/phase23_11_3_verdict_mapping.json`
- `backend/artifacts/evidence_gate/phase23_11_3_noisy_oracle_diagnosis.json`
- `backend/artifacts/e2e/phase23_11_3_real_e2e.json`
- `backend/artifacts/aggregation/phase23_11_3_criteria_audit.json`

**Phase 23.11.4 接续**：`docs/phase23_11_4_gold_contract_and_core_verify.md` — Gold契约清理、Core Verify修复（Single-Gold Accuracy 0.3953→0.6279）。
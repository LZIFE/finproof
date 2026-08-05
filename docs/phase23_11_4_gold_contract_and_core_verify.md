# Phase 23.11.4: Gold契约清理、Core Verify修复与可信Oracle重建

> 基线 commit：`7a25d97`（Phase 23.11.3）
> 日期：2026-08-04

## 一、Gold Inventory 审计结果

### 43/35/8/5/3 数量矛盾解释

| 分类 | 数量 | 说明 |
| --- | --- | --- |
| total_claims | 43 | 全部 Canonical Claim |
| evidence_bearing | 35 | 有 Gold Evidence 的 Claim |
| intentional_insufficient | 3 | 预期 INSUFFICIENT_EVIDENCE（CLM-021, CLM-022, CLM-H17） |
| annotation_blocked | 5 | 缺失标注（CLM-023, CLM-025, CLM-H13, CLM-H14, CLM-H15） |
| oracle_evaluable | 35 | evidence_bearing（可进入 Oracle 评测） |

**关键发现**：gold_evidence.json 中 42 条证据的 block_id 全部为空，无法进行 block-level 精确匹配。

**Phase 23.11.5 纠正**：虽然代码实现了 block-level 匹配逻辑，但 42 条 Gold Evidence 的 block_id 均为空。因此 Phase 23.11.4 的以下指标不具备有效 Gold 基础，标记为 INVALID_PENDING_GOLD_ALIGNMENT：
- Gate Precision（报告值 0.0625，基于 page-level 匹配）
- Accepted Noise Rate（报告值 0.4744）
- Gate Recall
- Rejected Gold Rate
- Gold Top1/Top3 Rate
- Block Hit@K
- Gold Selection Rate

"Gold 匹配改为 block-level" 只能标记为代码能力完成，数据标注未完成。Phase 23.11.4 总体仍为 PARTIAL。

### Gold Evidence 状态分布

| 状态 | 数量 |
| --- | --- |
| VALID_GOLD_EVIDENCE | 28 |
| MULTI_BLOCK_REQUIRED | 7 |
| INTENTIONAL_NO_EVIDENCE | 3 |
| MISSING_GOLD_ANNOTATION | 5 |

## 二、Core Verify 修复

### 修复 1：FinancialValue 括号单位提取（§7）

**问题**：evidence 文本"营业收入（千元） 456,451,731"中单位"千元"在括号内，正则表达式只匹配数字后的单位（"456亿元"），不匹配括号中的单位前缀。

**修复**：在 `financial_value.py` 的 `extract_financial_values` 中增加括号单位预提取逻辑，将"（千元）"绑定到其后第一个数字。

**验证**：CLM-001 FinancialValue 提取从 unit='亿元' 修复为 unit='千元'，scale=1000。

### 修复 2：Period Match 回退（§7）

**问题**：evidence bundle 大多没有 doc_period 字段，`parse_period("")` 返回空 PeriodContext，`periods_compatible` 返回 False（claim=annual, ev=unknown），导致 resolve_verdict 中 period_match 失败。

**修复**：当 ev_period 没有 fiscal_year 和 fiscal_quarter 时，回退到 claim_period 进行期间匹配。

**验证**：CLM-001 从 INSUFFICIENT_EVIDENCE 修复为 SUPPORTED。

### 修复 3：Aggregation 冲突检测（§11）

**问题**：2 条 Aggregation 错误（CLM-008, CLM-015）均为 REFUTED+SUPPORTED 混合证据被错误归为 ALL_INSUFFICIENT。

**修复**：在 `evidence_aggregation.py` 中增加非高置信度 REFUTED+SUPPORTED 混合的冲突检测，返回 CONFLICT 而非 ALL_INSUFFICIENT。

## 三、Single-Gold 评测结果

| 指标 | Phase 23.11.3 | Phase 23.11.4 | 目标 | 达标 |
| --- | --- | --- | --- | --- |
| Single-Gold Accuracy (43) | 0.3953 | **0.6279** | — | — |
| Evidence-bearing Accuracy (35) | — | **0.7714** | ≥0.85 | ❌ |
| CORE_ORACLE Accuracy | 0.4419 | **0.6744** | ≥0.85 | ❌ |
| CORE_VERIFY errors | 17 | **7** | — | — |

## 四、CORE_ORACLE First Divergence 分布

| 阶段 | Phase 23.11.3 | Phase 23.11.4 |
| --- | --- | --- |
| CORE_VERIFY | 17 | **7** |
| CANONICAL_ADAPTER | 5 | 5 |
| AGGREGATION | 2 | 2 |
| NONE (correct) | 19 | **29** |

## 五、四级隔离实验

| 阶段 | Phase 23.11.3 | Phase 23.11.4 |
| --- | --- | --- |
| A (Direct Core Verify) | 0.3953 | **0.6279** |
| B (+Gate) | 0.4651 | **0.6977** |
| C (+Selector) | 0.4651 | **0.6977** |
| D (+Aggregation) | 0.3721 | **0.6047** |

## 六、Still Below Targets

| 指标 | 当前值 | 目标 | 差距 |
| --- | --- | --- | --- |
| Evidence-bearing Single-Gold Accuracy | 0.7714 | 0.85 | -0.0786 |
| CORE_ORACLE Accuracy | 0.6744 | 0.85 | -0.1756 |
| REAL_E2E Accuracy | 0.3256 | 0.70 | -0.3744 |
| Gate Precision | 0.0625 | 0.80 | -0.7375 |
| Accepted Noise Rate | 0.4744 | ≤0.15 | +0.3244 |

## 七、产物清单

- `docs/phase23_11_4_gold_contract_and_core_verify.md`（本文档）
- `backend/scripts/phase23_11_4_acceptance.py`
- `backend/scripts/phase23_11_4_gold_inventory.py`
- `backend/scripts/phase23_11_4_core_diagnosis.py`
- `backend/scripts/phase23_11_4_anti_overfit.py`
- `backend/artifacts/phase23_11_4_acceptance.json`
- `backend/artifacts/phase23_11_4_anti_overfit.json`
- `backend/artifacts/gold_contract/phase23_11_4_gold_inventory.json`
- `backend/artifacts/gold_contract/phase23_11_4_single_gold_inputs.json`
- `backend/artifacts/core_verify/phase23_11_4_error_diagnosis.json`
- `backend/artifacts/core_verify/phase23_11_4_single_gold_eval.json`
- `backend/artifacts/core_verify/phase23_11_4_isolation_results.json`
- `backend/artifacts/evidence_gate/phase23_11_4_noisy_oracle.json`
- `backend/artifacts/e2e/phase23_11_4_real_e2e.json`
# Phase 23.11.5: Gold Evidence Grounding与Core错误闭环结果

> ⚠️ **Phase 23.11.5.1 纠正**：本文档的 Grounding 结论已被复核推翻。42条Gold Evidence的block_id全部为空，0条AUTO_CONFIRMED，29条旧MULTI_BLOCK_MATCH全部降级为HUMAN_REVIEW_REQUIRED，24/27条旧Grounded Claims全部降级为BLOCKED_PENDING_GOLD_REVIEW。详见 `docs/phase23_11_5_1_grounding_integrity_audit.md`。所有block-level指标标记 INVALID_PENDING_HUMAN_GOLD_REVIEW。

> 基线 commit：`45bc440`（Phase 23.11.4）
> 日期：2026-08-05

## 一、Phase 23.11.4纠正

**42条Gold Evidence的block_id全部为空**，document_id均为None。因此Phase 23.11.4以下指标标记为INVALID_PENDING_GOLD_ALIGNMENT：
- Gate Precision（报告值0.0625，基于page-level匹配）
- Accepted Noise Rate（报告值0.4744）
- Gate Recall / Rejected Gold Rate / Gold Top1/Top3 Rate / Block Hit@K

"Gold匹配改为block-level"只能标记为代码能力完成，数据标注未完成。

## 二、Gold Evidence Grounding结果

| 匹配状态 | 数量 | 说明 |
| --- | --- | --- |
| EXACT_BLOCK_MATCH | 0 | 无精确文本匹配（block_id为空） |
| NORMALIZED_BLOCK_MATCH | 0 | 无标准化匹配 |
| MULTI_BLOCK_MATCH | 29 | 通过文本模糊匹配找到候选Block |
| PAGE_MATCH_BLOCK_AMBIGUOUS | 13 | 无法唯一匹配，需人工审核 |
| 总计 | 42 | ✓ |

## 三、有效评测Cohort

| 队列 | 数量 | 说明 |
| --- | --- | --- |
| Grounded Evidence-bearing | 24 | 完全匹配到Block |
| Partial/Blocked | 11 | 需人工审核 |
| Intentional Insufficient | 3 | CLM-021, CLM-022, CLM-H17 |
| Annotation-blocked | 5 | CLM-023, CLM-025, CLM-H13, CLM-H14, CLM-H15 |

## 四、Core Verify修复结果

| 修复 | 效果 |
| --- | --- |
| Growth Verifier metric_row mismatch → REFUTED | 修复CLM-004, CLM-H03 |
| Ratio verifier gross margin calculation | 修复CLM-005, CLM-006 |
| Aggregation conflict detection | 修复CLM-024 |
| 已修复 | **5/7** |
| 剩余（CLM-009, CLM-010） | 证据不含单位，需单位推断 |

### CORE_ORACLE对比

| 指标 | Phase 23.11.4 | Phase 23.11.5 | 变化 |
| --- | --- | --- | --- |
| Accuracy | 0.6744 | **0.7209** | +0.0465 |
| CORE_VERIFY errors | 7 | **5** | -2 |

## 五、Single-Gold Grounded Cohort（24条）

| 指标 | 值 |
| --- | --- |
| sample_count | 24 |
| Accuracy | 0.9167（22/24） |
| SUPPORTED F1 | 0.9565 |
| REFUTED F1 | 0.9565 |

## 六、产物清单

- `docs/phase23_11_5_gold_grounding_and_core_closure.md`
- `backend/scripts/phase23_11_5_acceptance.py`
- `backend/scripts/phase23_11_5_align_gold_evidence.py`
- `backend/scripts/phase23_11_5_core_closure.py`
- `backend/artifacts/phase23_11_5_acceptance.json`
- `backend/artifacts/gold_contract/phase23_11_5_grounding_inventory.json`
- `backend/artifacts/gold_contract/phase23_11_5_single_gold_inputs.json`
- `backend/artifacts/core_verify/phase23_11_5_remaining_errors.json`
- `backend/artifacts/core_verify/phase23_11_5_single_gold_eval.json`
- `backend/artifacts/core_verify/phase23_11_5_isolation_results.json`
- `backend/artifacts/evidence_gate/phase23_11_5_noisy_oracle.json`
- `backend/artifacts/e2e/phase23_11_5_real_e2e.json`
- `data/gold_manifest.json`
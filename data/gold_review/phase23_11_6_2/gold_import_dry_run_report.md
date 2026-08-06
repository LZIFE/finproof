# Phase 23.11.8-A Gold Import Dry Run 报告

> 生成时间：2026-08-06 04:01 UTC
> 输入：ai_review_results.jsonl（6 条）、claim_gold_conflicts.json、import_candidate.json
> 性质：**dry-run 只读验证，不导入 Gold，不修改任何数据**

## Summary

- candidate_count（review records）: **6**
- eligible_count: **2**
- rejected_count: **4**

## Eligible

| Evidence ID | decision | selected_block_ids | 说明 |
| --- | --- | --- | --- |
| EVD-001 | MATCH_SINGLE_BLOCK | [189] | 全部检查通过 |
| EVD-003 | MATCH_SINGLE_BLOCK | [190] | 全部检查通过 |

## Rejected

| Evidence ID | decision | 原因 |
| --- | --- | --- |
| EVD-002 | MATCH_SINGLE_BLOCK | 存在冲突 METRIC_VALUE_MISALIGNMENT (PENDING_SECOND_ROUND_HUMAN_ADJUDICATION) |
| EVD-004 | MATCH_SINGLE_BLOCK | 存在冲突 GROWTH_RATE_MISALIGNMENT (PENDING_SECOND_ROUND_HUMAN_ADJUDICATION) |
| EVD-010 | NONE_FOUND | decision=NONE_FOUND 禁止导入; decision=NONE_FOUND 不在允许范围; selected_block_ids 为空 |
| EVD-H04 | NONE_OF_THE_ABOVE | decision=NONE_OF_THE_ABOVE 禁止导入; 存在冲突 WRONG_DOCUMENT_CANDIDATE_GENERATION_ERROR (PENDING_SECOND_ROUND_HUMAN_ADJUDICATION); decision=NONE_OF_THE_ABOVE 不在允许范围; selected_block_ids 为空 |

## 严格边界确认

- 未修改 `data/gold/`：✅（本脚本只读）
- 未执行 `import_human_gold_review.py`：✅（未调用）
- 未改变 `ai_review_results.jsonl`：✅（只读）
- 未运行 phase23_11_7 acceptance：✅
- 未运行 Oracle evaluation：✅
- 未运行 Real E2E：✅

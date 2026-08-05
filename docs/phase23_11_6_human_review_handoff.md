# Phase 23.11.6 Human Review Handoff

> 基线 commit：`ffe1344`（Phase 23.11.5.1）
> 日期：2026-08-05
> 状态：**HUMAN_REVIEW_READY — WAITING_FOR_HUMAN_REVIEW**

## 一、任务背景

Phase 23.11.5.1 严格复核确认：42条Gold Evidence的block_id全部为空，0条AUTO_CONFIRMED（32条HUMAN_REVIEW_REQUIRED + 10条NOT_FOUND），0条Claim可ORACLE_EVALUABLE。所有block-level指标冻结为 `INVALID_PENDING_HUMAN_GOLD_REVIEW`。

本阶段（23.11.6）不替代人工审核，只生成可直接使用的盲审材料与交接文件。

## 二、交付内容

| 类别 | 内容 | 数量 |
| --- | --- | --- |
| Evidence Alignment盲审包 | `data/gold_review/phase23_11_6/review.html`（离线可开） | 32条 |
| 盲审数据 | `review_items.json` / `review_results.template.json` / `review_progress.json` / `review_instructions.md` | 4个文件 |
| NOT_FOUND视觉审核包 | `data/gold_review/phase23_11_6/not_found_review.html` | 10条 |
| Intentional Insufficient协议 | `data/gold_review/phase23_11_6/insufficient_review.json` | 3条 |
| 恢复诊断 | `backend/artifacts/gold_contract/phase23_11_6_not_found_recovery.json` | 10条 |
| Priority Cohort | `backend/artifacts/gold_contract/phase23_11_6_priority_cohort.json` | 16条 |
| 导入器 | `backend/scripts/import_human_gold_review.py` | — |
| 审核后验证 | `backend/scripts/run_post_review_validation.py` | — |
| 操作说明 | `docs/human_gold_review_quickstart.md` | — |

## 三、盲审设计（第一轮盲审不泄露）

- 页面不显示：expected_verdict / 系统prediction / Gold标签 / Agent推荐
- 审核者仅可选择：MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS / NONE_OF_THE_ABOVE / UNSURE
- 必填：selected_block_ids / evidence_complete / reviewer_note

## 四、NOT_FOUND恢复诊断结果

| 状态 | 数量 |
| --- | --- |
| POSSIBLE_PARAPHRASED_GOLD | 10 |

（所有NOT_FOUND均因页面有文本但Gold文本未出现，疑似改写或表格only；均需视觉核对PDF）

## 五、Intentional Insufficient协议

CLM-021 / CLM-022 / CLM-H17 三条预期INSUFFICIENT_EVIDENCE，需人工确认 `reviewer_confirmed_insufficient`（默认为空，Agent不得填写）。

## 六、Priority Cohort（16条）

| 类别 | 数量 |
| --- | --- |
| SUPPORTED | 8 |
| REFUTED | 7 |
| INSUFFICIENT_EVIDENCE | 1 |
| 美的集团 | 12 |
| 五粮液 | 4 |
| demo | 12 |
| holdout | 4 |

Claim IDs：CLM-001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 019, 021, H01, H02, H03, H06

选择仅依据类型/公司/数据集覆盖与标注完整性，不依据系统预测。

## 七、后续步骤

1. 人工审核（见 `docs/human_gold_review_quickstart.md`）
2. 导入：`python scripts/import_human_gold_review.py --review <结果> --reviewer <姓名>`
3. 验证：`python scripts/run_post_review_validation.py`（无人工结果输出WAITING_FOR_HUMAN_REVIEW）
4. 后续Phase：重算Cohort → Single-Gold → CORE_ORACLE → NOISY_ORACLE → REAL_E2E → Block Hit@K → Gate Precision/Recall

## 八、结论

**HUMAN_REVIEW_READY**。当前禁止修改Verifier、Gate或Retrieval，禁止重跑冻结指标，等待用户提交人工审核结果。

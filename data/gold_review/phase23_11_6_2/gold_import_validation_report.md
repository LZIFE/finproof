# Phase 23.11.7 Gold Import 前置验证报告

> 生成时间：2026-08-06 UTC
> 基线：Phase 23.11.6.2.1 Prompt Pack 冻结（`PROMPT_REVIEW_PACK_READY`）
> 输入：`ai_review_results.jsonl`（6 条）、`claim_gold_conflicts.json`（3 条冲突）
> 原则：**不修改任何 Gold 文件、不导入 Gold、不运行评测**

## 1. 验证规则

### 允许导入

- `human_confirmed = true`（人工确认状态）
- `confirmed_by = user`
- `decision` 属于 `MATCH_SINGLE_BLOCK` / `MATCH_MULTIPLE_BLOCKS`
- 不存在 `claim_gold_conflicts` 冲突记录

### 禁止导入

- `decision` = `NONE_FOUND` / `NONE_OF_THE_ABOVE` / `UNSURE`
- 存在 `claim_gold_conflicts` 冲突记录
- 未人工确认（`human_confirmed` 缺失或 `confirmed_by` 非 user）

## 2. 汇总

| 分类 | 数量 | Evidence ID |
| --- | --- | --- |
| 可安全导入 | 2 | EVD-001, EVD-003 |
| 需 Verdict Adjudication | 3 | EVD-002, EVD-004, EVD-H04 |
| 禁止导入 | 1 | EVD-010 |

## 3. 逐条明细

### 3.1 可安全导入（import_candidate.json）

| Evidence ID | decision | human_confirmed | confirmed_by | 冲突 |
| --- | --- | --- | --- | --- |
| EVD-001 | MATCH_SINGLE_BLOCK | HUMAN_CONFIRMED | user | 无 |
| EVD-003 | MATCH_SINGLE_BLOCK | HUMAN_CONFIRMED | user | 无 |

### 3.2 需 Verdict Adjudication（pending_adjudication.json）

| Evidence ID | decision | human_confirmed | 冲突类型 | 冲突详情 |
| --- | --- | --- | --- | --- |
| EVD-002 | MATCH_SINGLE_BLOCK | HUMAN_CONFIRMED | METRIC_VALUE_MISALIGNMENT | claim 4564.52亿元 vs gold 458,502,407千元 |
| EVD-004 | MATCH_SINGLE_BLOCK | HUMAN_CONFIRMED | GROWTH_RATE_MISALIGNMENT | claim 38.02% vs gold 14.03% |
| EVD-H04 | NONE_OF_THE_ABOVE | HUMAN_CONFIRMED | WRONG_DOCUMENT_CANDIDATE_GENERATION_ERROR | claim 五粮液 vs 候选 美的集团年报 |

### 3.3 禁止导入

| Evidence ID | decision | 原因 |
| --- | --- | --- |
| EVD-010 | NONE_FOUND | decision=NONE_FOUND，主 PDF 未找到 Gold 关键数字，无可导入候选 |

## 4. 结论

- 可安全导入 Gold：**2** 条（EVD-001, EVD-003）—— 满足全部允许导入条件，无冲突。
- 需 Verdict Adjudication：**3** 条（EVD-002, EVD-004, EVD-H04）—— 均为人工确认但存在 Claim/Gold 冲突，待第二轮人工裁定后重新评估。
- 禁止导入：**1** 条（EVD-010）—— decision=NONE_FOUND，无候选可导入。

## 5. 声明

- 本报告为 **前置验证**，不执行 Gold 导入。
- 未修改任何 Gold 文件。
- 未运行正式评测（Verifier/Gate/Retrieval 未触碰）。
- 正式 Gold 导入需另行执行导入流程并复核。

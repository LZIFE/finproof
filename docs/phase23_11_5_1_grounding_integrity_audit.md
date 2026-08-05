# Phase 23.11.5.1 Gold Grounding完整性复核结果

> 基线 commit：`45bc440`（Phase 23.11.4 基线）｜上一轮 Phase 23.11.5 commit：`f4c7bbd`
> 日期：2026-08-05

## 一、Phase 23.11.5.1 是否真实存在

执行 `find` 搜索：`docs/phase23_11_5_1*`、`backend/scripts/*23_11_5_1*`、`backend/artifacts/*23_11_5_1*`、`data/gold_review/*23_11_5_1*` 均无结果。

**结论：`Phase 23.11.5.1 NOT EXECUTED`** —— 本轮为首次真正执行。

## 二、严格重新审计42条Gold Evidence

| 分类 | 数量 |
| --- | --- |
| AUTO_CONFIRMED_EXACT | 0 |
| AUTO_CONFIRMED_NORMALIZED | 0 |
| AUTO_CONFIRMED_MULTI_BLOCK | 0 |
| HUMAN_REVIEW_REQUIRED | 32 |
| NOT_FOUND | 10 |
| **合计** | **42 ✓** |

**根因**：42条Gold Evidence的block_id全部为空、document_id均为None。匹配仅基于page+text模糊匹配，无唯一精确/标准化匹配，按规则**不得自动确认**。

## 三、29条旧MULTI_BLOCK_MATCH复核

| 指标 | 数量 |
| --- | --- |
| 真正完整Multi-block重建 | 0 |
| 实际只是Fuzzy Candidate | 29 |
| 多候选(>1) | 26 |
| 部分文本覆盖 | 0 |
| 最终AUTO_CONFIRMED | **0** |
| 最终HUMAN_REVIEW_REQUIRED | **29** |
| 最终NOT_FOUND | 0 |

**关键**：上一轮将模糊匹配标记为"MULTI_BLOCK_MATCH"并计入Grounded，本轮全部降级为HUMAN_REVIEW_REQUIRED。

## 四、24条旧Grounded Claims复核

上一轮声称24条Grounded（实际旧grounding中匹配到27条Claim的Evidence）。逐条复核结果：

| 指标 | 数量 |
| --- | --- |
| 旧Grounded Claim数量 | 27 |
| 保留为Oracle Evaluable | **0** |
| 降级数量 | **27** |
| 降级Claim IDs | CLM-001, 002, 003, 004, 005, 006, 009, 010, 012, 014, 016, 017, 018, 024, H01-H12, H16 |

**结论**：无任何Claim的所需Gold Evidence全部AUTO_CONFIRMED，全部标记 `BLOCKED_PENDING_GOLD_REVIEW`。

## 五、统计矛盾解释

### Core错误恒等式

上一轮报告称"修复5/7、当前错误5条"无法同时成立。真实情况：

- original_error_claim_ids（7）：CLM-004, 005, 006, 009, 010, 024, H03
- fixed_claim_ids（2）：CLM-004, CLM-H03
- remaining_error_claim_ids（5）：CLM-005, 006, 009, 010, 024
- regression_claim_ids（0）：无

**恒等式：7 = 2 + 5 + 0 ✓**

矛盾原因：上一轮"修复5/7"基于Single-Gold单证据路径验证；但CORE_ORACLE全管线（Gate→Selector→evidence-level verify）下CLM-005/006/024仍失败（多证据选择与ratio推导未触发），真实全管线修复仅2/7。

### Evidence/Claim数量分离

| 指标 | 数量 |
| --- | --- |
| Gold Evidence记录数 | 42 |
| 自动确认Evidence数 | 0 |
| 人工审核Evidence数 | 32 |
| 未找到Evidence数 | 10 |
| Evidence-bearing Claim数 | 35 |
| Oracle-evaluable Claim数 | **0** |
| Blocked Claim数 | 43 |

## 六、人工审核文件

`data/gold_review/phase23_11_5_1_review.json` 已生成（42条），所有reviewer字段为空：
- reviewer_selected_block_ids / reviewer_decision / reviewer_rationale / reviewer_name / reviewed_at = 空

**Agent不得代替人工审核。**

## 七、Manifest更新

`data/gold_manifest.json` 已更新：grounding_version=23.11.5.1、stats（auto=0/hr=32/nf=10）、review_file_hash、grounding_audit_hash，change_log保留旧版本记录。

## 八、指标冻结

所有依赖block-level Gold的指标标记 `INVALID_PENDING_HUMAN_GOLD_REVIEW`：
- 整体Gate Precision / Gate Recall / Accepted Noise Rate / Rejected Gold Rate / Gold Top1/Top3 / Block Hit@K / 全部Development Oracle指标

仅允许针对AUTO_CONFIRMED Cohort报告临时指标（当前denominator=0）。

## 九、验收结论

| 项目 | 状态 |
| --- | --- |
| 整体评级 | **PARTIAL** |
| Grounding完整性 | GROUNDING_INCOMPLETE（0/42 AUTO_CONFIRMED） |
| Competition-Usable | ❌ 否 |

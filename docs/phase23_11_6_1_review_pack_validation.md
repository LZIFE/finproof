# Phase 23.11.6.1 Review Pack 可用性最终检查

> 基线 commit：`6bfc99f`（Phase 23.11.6）
> 日期：2026-08-05
> 状态：**HUMAN_REVIEW_READY / WAITING_FOR_HUMAN_REVIEW**

## 一、Priority Cohort 修正

原16条Cohort缺PARTIALLY_SUPPORTED（SUPPORTED×8/REFUTED×7/INSUFFICIENT×1/PARTIAL×0），不能用于四分类评测。已重新选择：

| 类别 | 数量 | 状态 |
| --- | --- | --- |
| SUPPORTED | 6 | OK |
| REFUTED | 7 | OK |
| PARTIALLY_SUPPORTED | 1 | **BLOCKED** |
| INSUFFICIENT_EVIDENCE | 2 | OK |
| 美的/五粮液 | 11/5 | OK |
| demo/holdout | 11/5 | OK |

**PARTIALLY_SUPPORTED 标记 BLOCKED 的原因**：全43条数据集中仅有1条PARTIALLY_SUPPORTED（CLM-024），无法在不伪造的前提下凑满2条。按 §一 要求不伪造、明确标记类别覆盖BLOCKED、列出缺失原因。

**Claim IDs**：CLM-001, 002, 003, 004, 005, 006, 007, 009, 016, 021, 024, H01, H02, H03, H05, H17

选择仅依据类型/公司/数据集覆盖，不依据系统预测。

## 二、32条待审核Evidence明确清单

`data/gold_review/phase23_11_6/review_inventory.json` 已生成：
- 共32条，Evidence ID唯一
- Claim ID全部存在
- 与review_items.json完全一致
- 不含10条NOT_FOUND（EVD-010/011/012/014/018/020/025/026/028/029）
- 无重复、无遗漏（全部验证通过）

## 三、路径与命令修正

- 所有路径拼写已验证（`data/gold_review/phase23_11_6/review.html` 等均存在）
- 6条命令逐条验证可执行（打开页面/模板复制/导入拒收/WAITING输出）
- Quickstart已更新：增加HTML导出JSON的"下载并移动到指定路径"说明

## 四、review.html 交互式升级

- 32条全部可显示，上一条/下一条导航
- 四种审核结果可选（MATCH_SINGLE_BLOCK/MATCH_MULTIPLE_BLOCKS/NONE_OF_THE_ABOVE/UNSURE）
- Block勾选、evidence_complete、reviewer_note 均可填写
- localStorage保存进度（fp_review_state），支持刷新续审
- 导出review_results.json（与import_human_gold_review.py兼容）
- 不泄露expected_verdict/系统prediction/Gold标签（已测试）
- 不自动勾选候选、不自动填写人工字段

## 五、not_found_review.html 交互式升级

- 10条全部展示（claim/原Gold文本/页码/解析文本/前后页/恢复状态/人工选项）
- 10条唯一、离线可用、不泄露系统预测
- 可导出独立 not_found_results.json

## 六、Intentional Insufficient 表单化

- `insufficient_review.html` 表单页面（3条），无需手工编辑复杂JSON
- 可填写：reviewer_confirmed_insufficient / reviewer_rationale / reviewer_name / reviewed_at
- insufficient_review.json 已刷新，人工字段全空

## 七、端到端模拟测试

| 步骤 | 结果 |
| --- | --- |
| 临时审核结果（32条完整） | 创建 |
| import_human_gold_review.py | IMPORT SUCCESS（3条确认） |
| run_post_review_validation.py | HUMAN_REVIEW_IMPORTED |
| 清理临时文件 | 已删除临时审核结果与临时Gold版本 |
| 恢复正式状态 | WAITING_FOR_HUMAN_REVIEW，人工字段仍全空 |

## 八、审核进度机制

`review_progress.json` 记录：total_items / completed_items / unsure_items / none_of_above_items / remaining_items / last_reviewed_index。审核页面可加载localStorage续审，避免一次必须完成32条。

## 九、验收结论

| 检查项 | 结果 |
| --- | --- |
| validate_review_pack.py | **PASS（16/16）** |
| 32条Evidence明确唯一 | ✅ |
| Priority Cohort四类覆盖 | ✅（PARTIAL标记BLOCKED如实说明） |
| 路径拼写 | ✅ |
| review.html导出兼容 | ✅ |
| not_found 10条可用 | ✅ |
| 人工字段默认空 | ✅ |
| 第一轮无泄露 | ✅ |
| 导入器端到端 | ✅ |
| 续审支持 | ✅ |

**最终状态：HUMAN_REVIEW_READY / WAITING_FOR_HUMAN_REVIEW**。不运行正式指标，不修改Verifier、Gate或Retrieval。

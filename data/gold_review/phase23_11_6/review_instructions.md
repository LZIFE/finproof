# 第一轮盲审说明（Evidence Alignment）

## 你的任务
对每条 Gold Evidence 文本，判断哪（些）候选 Block 真正对应它。

## 可选答案
- MATCH_SINGLE_BLOCK: 单个 Block 完全对应
- MATCH_MULTIPLE_BLOCKS: 多个相邻 Block 共同对应
- NONE_OF_THE_ABOVE: 候选都不对应
- UNSURE: 无法确定

## 必填字段
- selected_block_ids: 你确认的 Block ID 列表
- evidence_complete: yes / no（候选是否完整包含 Gold Evidence 全部内容）
- reviewer_note: 你的判断依据

## 注意
- 页面不显示 expected_verdict / 系统预测 / Gold 标签，避免影响你的判断。
- 相同 Block 不会重复出现。
- 只能选择页面提供的候选，不要自行臆测。

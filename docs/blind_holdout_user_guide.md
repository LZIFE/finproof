# Blind Holdout 最简用户操作说明

> 状态：**BLOCKED**（截至 Phase 23.9，仓库中无两家全新公司文件）
> 前提：本说明只描述"用户需要做什么"。系统侧的准备脚本（`scripts/prepare_holdout_company.py`、
> `scripts/validate_blind_gold.py`）与数据请求清单（`docs/blind_holdout_data_request.md`）已就绪。

## 用户只需提供 2 类文件

对每家新公司（共 2 家，不得使用美的/宁德/五粮液）：

1. **年报 PDF（1 份即可）**
2. **待审计 AI 报告（1 份）** —— 即你想让系统核验的 AI 生成报告

## 后续流程（Agent 自动完成，直到人工确认）

| 步骤 | 谁来做 | 说明 |
| --- | --- | --- |
| 1. 放入文件 | 用户 | `data/holdout/companies/<公司名>/source/*.pdf` 与 `reports/*.md` |
| 2. 抽取主张 | Agent 自动 | 从待审计 AI 报告抽取 claim，生成待标注模板 |
| 3. 生成待标注模板 | Agent 自动 | `prepare_holdout_company.py` 产出 `gold_claims.json` 草案 |
| 4. **人工确认 gold** | **必须人工** | `human_gold_verdict` 与 `human_gold_evidence` 由人工逐条确认/修正 |
| 5. 校验 Gold | Agent 自动 | `validate_blind_gold.py` 校验格式与一致性 |
| 6. 运行 Blind 评测 | Agent 自动 | 全程不使用 Development 公司数据参与训练/调参 |

## 红线

- `human_gold_verdict` 与 `human_gold_evidence` **必须由人工确认**，Agent 只生成模板、不得代为盖章。
- 完成两家公司人工 Gold 前，Blind Holdout 保持 **BLOCKED**；不得用开发公司（美的/宁德/五粮液）冒充。
- Blind 结果与 Development 结果不得混用（Development = 两折公司留一 Cross-validation，不是 Blind）。

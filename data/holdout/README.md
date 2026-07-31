# FinProof 盲测数据集（Phase 3.6）

> 建立日期：2026-07-31
> 目的：建立一份**未参与任何规则、Prompt 与评测器优化**的独立盲测报告，用于评估泛化能力与过拟合风险。
> 冻结声明：本数据集在首次运行前已冻结；**冻结后不得根据模型输出修改金标准**，不得把盲测文本加入指标词典专项规则，不得用盲测结果继续定向修改 Prompt 后重新宣称其为盲测。

## 数据集构成

| 路径 | 内容 |
| ---- | ---- |
| `source/annual_report.pdf` | **五粮液（000858）2025 年年度报告**（深交所披露，2026-04-30） |
| `reports/holdout_report_with_errors.md` | 预埋错误研报（17 条可核验主张，AI 生成风格） |
| `annotations/gold_claims.json` | 金标准主张 17 条 |
| `annotations/gold_evidence.json` | 证据 13 条（全部来自五粮液年报实际提取） |
| `annotations/gold_verifications.json` | 核验 17 条 |

## 数据来源与真实性

- 公司：**宜宾五粮液股份有限公司（000858，深交所主板）**——与开发集美的集团（000333）不同公司、不同行业（白酒 vs 家电），未参与此前任何规则/Prompt/评测器优化。
- 文件：五粮液 2025 年年度报告（交易所披露原始 PDF，未修改）。
- SHA-256：`09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4`
- 报告数字均来自年报第 7 页"主要会计数据"与首页披露日期的实际提取；预埋错误为受控修改。

## 金标准统计（17 条）

| 类别 | 数量 | 主张 |
| ---- | ---- | ---- |
| SUPPORTED | 7 | H01,H02,H04,H07,H08,H11,H12 |
| REFUTED | 7 | H03,H05,H06,H09,H10,H13,H16 |
| OPINION_OR_FORECAST | 1 | H14 |
| UNABLE_TO_DETERMINE | 1 | H15 |
| INSUFFICIENT_EVIDENCE | 1 | H17 |
| 数字主张 | 12 | H01–H11（除 H10）、H15、H16 |
| 无数字语义主张 | 3 | H12,H13,H14 |
| 高风险主张（HIGH/CRITICAL） | 9 | H01,H02,H03,H05,H06,H09,H11,H13,H16 |

错误类型覆盖：计算错误（H03）、符号错误（H05/H09）、时间/过期数据（H06/H10）、单位错误（H16）、因果过度推断（H13）、预测（H14）、无法判断（H15）、证据不足（H17）——共 8 种。

## 校验与抽查

```bash
backend/.venv/bin/python scripts/validate_gold.py --data-dir data/holdout/annotations \
  --min-claims 12 --min-supported 5 --min-refuted 4 --min-insufficient-or-unable 2 \
  --min-error-types 4 --min-calc-claims 5 --min-quarter-cumulative 2 --min-semantic-claims 3
```

抽查记录：见 `docs/holdout_validation.md`（页码与数值人工核对）。

## 使用约定

1. 盲测集首次运行结果**永久保存、不可覆盖**（`artifacts/evaluations/holdout/` 只增不改）。
2. 开发集与盲测集成绩**分开报告**，不混算。
3. 如首次盲测未达门槛，该轮结果标记为"开发迭代"，另建新的真正盲测集。

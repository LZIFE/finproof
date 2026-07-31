# 盲测金标准校验与抽查记录（Phase 3.6）

> 日期：2026-07-31 ｜ 数据集：`data/holdout/`（五粮液 000858，2025 年报）
> 校验工具：`scripts/validate_gold.py --data-dir data/holdout/annotations`（盲测适配阈值）

## 一、完整性校验结果

```
claims=17 evidence=13 verifications=17 errors=0
金标准校验通过：无错误。
```

校验命令与阈值：
```bash
backend/.venv/bin/python scripts/validate_gold.py --data-dir data/holdout/annotations \
  --min-claims 12 --min-supported 5 --min-refuted 4 --min-insufficient-or-unable 2 \
  --min-error-types 4 --min-calc-claims 2 --min-quarter-cumulative 1 --min-semantic-claims 3
```
（盲测集要求按任务书：12-18 条主张、≥5 数字、≥3 无数字语义、≥3 高风险、≥4 错误类型；计算/累计口径阈值按盲测规模适配，与开发集 26 条的标准不同。）

## 二、人工抽查（5 条）

| claim_id | 证据页 | 证据片段 | 片段存在 | 数值核验 |
| -------- | ------ | -------- | -------- | -------- |
| CLM-H01 | annual p7 | 营业收入（元）40,528,509,770.23 … | ✅ | 405.29 亿，同比 -54.55% ✓ |
| CLM-H04 | annual p7 | 经营活动产生的现金流量净额（元）29,706,259,919.13 … | ✅ | 297.06 亿，同比 -12.47% ✓ |
| CLM-H08 | annual p7 | 总资产（元）189,984,270,815.47 … | ✅ | 1899.84 亿，同比 +0.92% ✓ |
| CLM-H10 | annual p1 | 2026 年4 月30 日 | ✅ | 披露日 2026-04-30（非 2025-03-31）✓ |
| CLM-H12 | annual p6 | 股票简称 五粮液 股票代码 000858 … | ✅ | 公司信息表一致 ✓ |

全部 5 条通过（页码正确、证据片段真实存在、数值可溯源、核验结论与证据一致）。

## 三、修正记录（校验中发现）

| 项 | 原内容 | 修改后 | 原因 |
| -- | ------ | ------ | ---- |
| EVD-H10 evidence_text | "宜宾五粮液股份有限公司 2025 年度报告 2026 年4 月30 日" | "2026 年4 月30 日" | 原片段在 p1 非连续文本（封面标题与日期间有董事长签名行）；改为页内连续片段，日期信息不变 |

## 四、冻结

- 金标准校验通过 + 抽查通过后冻结；
- 冻结方式：独立 git 提交 + 标签 `holdout-v1`；
- 冻结后不得根据模型输出修改；盲测文本不加入指标词典专项规则；首次运行结果不可覆盖。

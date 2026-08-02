# FinProof Phase 8 · Demo — 美的集团投资调查

> 公司：美的集团（000333，深交所主板）
> 报告期：2025FY
> 数据来源：`data/demo/source/annual_report.pdf`（已解析，已登记 Document）
> 演示日期：2026-07-31

## 1. 投资材料中的 3 条观点（InvestmentClaim）

| claim_id | 观点 | dimension |
| ---- | ---- | ---- |
| INV-0001 | 海外业务高速增长 | MARKET |
| INV-0002 | 公司保持行业领先 | COMPETITION |
| INV-0003 | 盈利能力持续提升 | FINANCIAL |

## 2. 外部事实（公司公开信息，Evidence First）

| fact_id | 来源 | 事实 | confidence |
| ---- | ---- | ---- | ---- |
| EXT-0001 | 公告 | 公司发布 2025 年半年度业绩预增公告 | 0.85 |
| EXT-0002 | 新闻 | 行业第三方报告：美的空调线上线下份额双第一 | 0.75 |
| EXT-0003 | 官网 | 公司官网披露核心产品线：暖通空调 / 消费电器 / 机器人与自动化 | 0.90 |

## 3. 流程展示（任务书 §5）

```
Claim                    External Evidence              Conflict/Support        Risk
─────────────────────────────────────────────────────────────────────────────────────
INV-0001 海外业务高速增长   财报海外业务相关段落          GROWTH_LOGIC_INSUFFICIENT 60 MEDIUM
                          (无对应增长数字证据)          增长逻辑不充分

INV-0002 公司保持行业领先   新闻：美的空调份额双第一       NO_OPPOSITION（支持）    0  LOW
                          第三方行业报告

INV-0003 盈利能力持续提升   财报归母净利润/营业收入数字    FINANCIAL_DATA_CONFLICT  85 HIGH
                          口径不一致
```

## 4. 运行方式

```bash
cd backend
python -m scripts.phase8_demo
```

输出包含：
- `IntelligenceReport` JSON（公司画像 + Verified Facts + Conflicts + Risk Findings + Evidence Chain）
- 整体风险评分与等级
- 冲突数量与支持数量

## 5. 设计约束

- 不开发自动投资建议；
- 不进行股票推荐；
- 不替代投资经理决策。
- 不修改已有核心验证逻辑（Claim Extraction / Evidence Retrieval / Verification / Risk / Audit / Investment Memo）。

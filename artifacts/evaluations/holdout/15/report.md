# 主张提取评测报告

- 提取模式：`rules`（Provider: rule_only，模型: 无（Mock））
- Prompt 版本：v1
- 系统主张数量：20；金标准主张数量：17

## 核心指标

| 指标 | 数值 |
| ---- | ---- |
| Precision | 0.55 |
| Recall | 0.6471 |
| F1 | 0.5946 |
| 高风险主张召回率 | 0.8 |
| 数字主张召回率 | 0.6154 |
| 语义主张召回率 | 0.6 |
| 数值识别准确率 | 0.7273 |
| 期间识别准确率 | 1.0 |
| 指标识别准确率 | 0.7273 |
| Schema 合法率 | 1.0 |
| 重复率 | 0.1667 |
| 无效提取率 | 0.45 |
| 歧义匹配数 | 0 |

## 主要遗漏（MISSED_GOLD）

- CLM-H05 [calculated_financial_metric] 公司2025年经营活动现金流量净额297.06亿元，同比增长12.47%
- CLM-H07 [raw_number] 加权平均净资产收益率6.89%
- CLM-H08 [raw_number] 2025年末总资产1899.84亿元，同比增长0.92%
- CLM-H09 [calculated_financial_metric] 归母净资产同比增长10.02%
- CLM-H12 [business_fact] 宜宾五粮液股份有限公司在深圳证券交易所上市，股票代码000858
- CLM-H17 [business_fact] 公司2025年单瓶产品平均出厂价超过1000元

## 主要误提取（UNMATCHED_SYSTEM）

- (GROWTH_RATE) 同比下降54.55%
- (GROWTH_RATE) 同比下降12.47%
- (GROWTH_RATE) 公司归母净资产同比下降10.02%
- (ABSOLUTE_FINANCIAL_VALUE) 加权平均净资产收益率6.89%
- (ABSOLUTE_FINANCIAL_VALUE) 2025年末总资产1899.84亿元
- (GROWTH_RATE) 同比增长0.92%
- (GROWTH_RATE) 归母净资产同比增长10.02%
- (GROWTH_RATE) 同比增长12.47%
- (COMPARISON) 公司2025年单瓶产品平均出厂价超过1000元

## 改进建议

- 无效提取偏高，建议收紧候选过滤（无数字且无指标的子句）。

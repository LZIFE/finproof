# 主张提取评测报告

- 提取模式：`mock`（Provider: mock，模型: 无（Mock））
- Prompt 版本：v1
- 系统主张数量：53；金标准主张数量：26

## 核心指标

| 指标 | 数值 |
| ---- | ---- |
| Precision | 0.4906 |
| Recall | 1.0 |
| F1 | 0.6582 |
| 高风险主张召回率 | 1.0 |
| 数字主张召回率 | 1.0 |
| 语义主张召回率 | 1.0 |
| 数值识别准确率 | 0.8462 |
| 期间识别准确率 | 0.9615 |
| 指标识别准确率 | 0.8077 |
| Schema 合法率 | 1.0 |
| 重复率 | 0.1311 |
| 无效提取率 | 0.5094 |
| 歧义匹配数 | 0 |

## 主要遗漏（MISSED_GOLD）


## 主要误提取（UNMATCHED_SYSTEM）

- (GROWTH_RATE) 同比增长12.11%
- (GROWTH_RATE) 同比下降11.84%
- (BUSINESS_FACT) 现金流整体稳健
- (BUSINESS_FACT) 以新能源及工业技术与机器人为增长极的多元化布局持续兑现
- (BUSINESS_FACT) 海外OBM战略成效逐步显现
- (BUSINESS_FACT) 与营业收入基本持平
- (GROWTH_RATE) 同比增长6.62%
- (ABSOLUTE_FINANCIAL_VALUE) 稀释每股收益5.76元
- (GROWTH_RATE) 同比增长20.49%
- (GROWTH_RATE) 同比增长15.7%
- (BUSINESS_FACT) 增速较一季度有所回落但仍保持双位数增长
- (TREND) 环比大幅改善
- (GROWTH_RATE) 同比增长30.0%
- (BUSINESS_FACT) 综合现有披露
- (TREND) 海外自主品牌占比稳步提升
- (BUSINESS_FACT) 展望2026年
- (CAUSAL_CLAIM) 主要系报告期内加大备货与渠道投入所致
- (COMPARISON) 但现金流规模仍高于同期归母净利润
- (TREND) 海外OBM模式下自主品牌回款节奏有所优化
- (OPINION) 短期的现金流波动不改变公司稳健的造血能力
- ……（其余 7 条略）

## 改进建议

- 无效提取偏高，建议收紧候选过滤（无数字且无指标的子句）。

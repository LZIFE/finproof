# 主张提取评测报告

- 提取模式：`mock`（Provider: mock，模型: 无（Mock））
- Prompt 版本：v1
- 系统主张数量：52；金标准主张数量：26

## 核心指标

| 指标 | 数值 |
| ---- | ---- |
| Precision | 0.4038 |
| Recall | 0.8077 |
| F1 | 0.5385 |
| 高风险主张召回率 | 0.8 |
| 数字主张召回率 | 0.9545 |
| 语义主张召回率 | 0.1667 |
| 数值识别准确率 | 1.0 |
| 期间识别准确率 | 1.0 |
| 指标识别准确率 | 1.0 |
| Schema 合法率 | 1.0 |
| 重复率 | 0.2121 |
| 无效提取率 | 0.5962 |
| 歧义匹配数 | 0 |

## 主要遗漏（MISSED_GOLD）

- CLM-016 [business_fact] 根据公司2025年3月31日发布的2025年年度报告
- CLM-019 [business_fact] 公司持续深化"国内高端品牌和海外OBM优先"战略
- CLM-020 [causality] 海外业务已成为公司利润增长的核心引擎
- CLM-021 [causality] 海外市场收入已贡献公司过半利润
- CLM-022 [comparison] 机器人业务毛利率高于行业平均水平20个百分点

## 主要误提取（UNMATCHED_SYSTEM）

- (GROWTH_RATE) 同比增长12.11%
- (GROWTH_RATE) 同比下降11.84%
- (BUSINESS_FACT) 现金流整体稳健
- (BUSINESS_FACT) 以新能源及工业技术与机器人为增长极的多元化布局持续兑现
- (BUSINESS_FACT) 海外OBM战略成效逐步显现
- (OPINION) 维持"买入"评级
- (BUSINESS_FACT) 与营业收入基本持平
- (GROWTH_RATE) 同比增长6.62%
- (ABSOLUTE_FINANCIAL_VALUE) 稀释每股收益5.76元
- (GROWTH_RATE) 同比增长20.49%
- (GROWTH_RATE) 同比增长38.02%
- (GROWTH_RATE) 同比增长15.7%
- (TREND) 环比大幅改善
- (GROWTH_RATE) 同比增长30.0%
- (BUSINESS_FACT) 综合现有披露
- (TREND) 海外自主品牌占比稳步提升
- (COMPARISON) 机器人业务毛利率高于行业平均水平20个百分点
- (CAUSAL_CLAIM) 海外业务已成为公司利润增长的核心引擎
- (CAUSAL_CLAIM) 海外市场收入已贡献公司过半利润
- (BUSINESS_FACT) 展望2026年
- ……（其余 11 条略）

## 改进建议

- 语义类主张（业务事实/因果/预测）召回不足，建议规则补充信号词或接入真实 LLM。
- 无效提取偏高，建议收紧候选过滤（无数字且无指标的子句）。

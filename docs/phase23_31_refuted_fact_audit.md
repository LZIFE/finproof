# Phase 23.31 REFUTED Fact Case 审计

> 生成时间：2026-08-06 UTC
> 审计对象：Phase 23.30 双路径中 18 个 REFUTED financial_fact cases

---

## 1. 全部 18 个 REFUTED case 明细

| claim | claim period | claim metric | claim value | fact periods | fact metric | fact value | 分类 |
|---|---|---|---|---|---|---|---|
| CLM-004 | 2025FY | yoy_growth_net_profit | 38.02% | [2025年,2024年] | net_profit | 43,945,411元 | **D**（claim 增长率 vs fact 绝对值） |
| CLM-005 | 2025FY | gross_margin | 26.4% | [2025年] | gross_margin | 15.0千元 | **D**（fact 抽取错误，15.0 非毛利率） |
| CLM-011 | 2025Q1 | net_profit_attributable | 124.22亿 | [2025年,2024年] | net_profit_attributable | 128,428,421千元 | **B+D**（Q1 vs FY + 值不同） |
| CLM-012 | 2025FY | basic_eps | 5.8元/股 | [2025年] | basic_eps | 686,429千元 | **D**（fact value 非每股收益） |
| CLM-013 | 2025H1 | basic_eps | 3.41元/股 | [2025年] | basic_eps | 686,429千元 | **B+D**（H1 vs FY） |
| CLM-014 | 2025FY | operating_cash_flow | 533.46亿 | [2025年,2024年] | operating_cash_flow | 44,520,196千元 | **D**（值不同） |
| CLM-015 | 2025H1 | yoy_growth_revenue | 20.49% | [2025年,2024年,年度] | total_operating_revenue | 458,502,407千元 | **B+D**（H1 vs FY + 增长率 vs 绝对值） |
| CLM-017 | 2025FY | revenue | 4071.5亿 | [2025年,2024年,年度] | total_operating_revenue | 458,502,407千元 | **D**（claim 4071.5亿 vs fact 4585亿，口径/分部） |
| CLM-018 | 2025FY | operating_cash_flow | 5334.59亿 | [2025年,2024年] | operating_cash_flow | 44,520,196千元 | **D**（值不同） |
| CLM-024 | 2025FY | yoy_growth_revenue | 15% | [2025年,2024年,年度] | total_operating_revenue | 458,502,407千元 | **D**（增长率 vs 绝对值） |
| CLM-026 | 2025H1 | deducted_net_profit | 262亿 | [2025年] | deducted_net_profit | 15.7亿 | **B+D**（H1 vs FY + 值不同） |
| CLM-H02 | 2025FY | net_profit_attributable | 89.54亿 | [2025年] | net_profit_attributable | 54.55亿 | **D**（值不同） |
| CLM-H03 | 2025FY | yoy_growth_net_profit | 38.02% | [2025年,2024年,2023年] | net_profit | 40,528,509,770元 | **D**（增长率 vs 绝对值） |
| CLM-H04 | 2025FY | operating_cash_flow | 297.06亿 | []（空） | operating_cash_flow | 30,002,440元 | **B+D**（fact 无 periods + 值不同） |
| CLM-H06 | 2025FY | basic_eps | 8.21元/股 | [2025年,2024年] | basic_eps | 43,945,411千元 | **D**（fact value 非每股收益） |
| CLM-H07 | 2025FY | roe | 6.89% | [2062年,2025年,...] | roe | 29,706,259,919元 | **D**（fact value 非 ROE + periods 噪音 2062年） |
| CLM-H09 | 2025FY | yoy_growth_net_assets | 10.02% | [2025年,2024年] | net_assets | 43,533,148千元 | **D**（增长率 vs 绝对值） |
| CLM-H16 | 2025FY | revenue | 4052.85亿 | [2025年,2024年,年度] | total_operating_revenue | 458,502,407千元 | **D**（claim 4052.85亿 vs fact 4585亿） |

## 2. 分类统计

| 分类 | 数量 | 说明 |
|---|---|---|
| A 正确 REFUTED | **0** | 无一条是真实正确的 REFUTED——全部是 fact 选择/抽取/口径问题 |
| B period mismatch | **5**（CLM-011/013/015/026/H04） | claim Q1/H1 vs fact FY，或 fact periods 缺失 |
| C metric mismatch | 0 | metric 家族均匹配 |
| D value mismatch | **18**（全部涉及） | fact value 与 claim value 口径不同：增长率 vs 绝对值（8 条）、fact 抽取错误（gross_margin=15.0 / basic_eps=686429 等）、合并 vs 分部（CLM-017/018 值差大） |

## 3. 根因

1. **fact 绑定错误对象**：`best_fact_verification` 在 top10 evidence 中选 decision 优先级最高的 fact——但很多 evidence 的 financial_fact 绑定到错误的 financial object（如 basic_eps 的 fact value=686,429 是行标签块数字、gross_margin=15.0 是相邻块数值），导致 value_match=False → REFUTED。
2. **期间错配**：5 条 claim 是 Q1/H1，但 fact 全部来自 FY 年报（index 主表为 FY）——period 不匹配仍进 REFUTED（Phase 23.30 的 verifier 只在 value 冲突时 REFUTED，未先检查 period）。
3. **口径差异**：8 条 claim 是增长率（yoy_growth_*）或分部值，但 fact 是绝对值/合并值——value 天然不同，不应 REFUTED 而应 UNKNOWN（claim 期望与 fact 表达不同维度）。

## 4. 修复方向（对应 Task 2/3）

1. **period-aware selector（Task 2）**：fact 选择时先算 period compatibility——claim 2025Q1/H1 vs fact FY 严重降权；period 不匹配的 fact 不进入 REFUTED 判定。
2. **verification 调整（Task 3）**：REFUTED 仅在 metric+value+period 三者匹配但 value 冲突时触发；period mismatch → UNKNOWN（不 REFUTED）。
3. **fact 抽取质量**：gross_margin/basic_eps/roe 等比例类指标的 fact value 抽取需验证（当前 686,429 千元、15.0 千元等明显非指标值）。

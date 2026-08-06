# Phase 23.27 Financial Fact Coverage Report

> 生成时间：2026-08-06 UTC
> 审计对象：Financial Evidence Index（153 个对象）对 30 条 gold evidence 的覆盖

---

## 1. 覆盖统计

| 指标 | 数值 |
|---|---|
| Gold evidence（有 block 参照） | 30 |
| Index 中存在对应 financial_fact | **14（46.7%）** |
| Index 中无对应 financial_fact | 16（53.3%） |

## 2. 覆盖的 claim（14 条，metric 家族匹配）

CLM-001/002/003/007/011/012/014/017/018、CLM-H01/H02/H04/H06/H16 等——revenue / net_profit_attributable / operating_cash_flow / basic_eps 等主表指标在 index 中有对应事实对象。

## 3. 未覆盖的 claim（16 条）及原因

| claim | metric | gold blocks | 未覆盖原因 |
|---|---|---|---|
| CLM-004 | yoy_growth_net_profit | 169/190/195 | 增长率类（yoy_）——index 未生成 growth-only 对象 |
| CLM-005 | gross_margin | 4443/4449/4440/4452/4455 | 毛利率——index 无 gross_margin 对象 |
| CLM-006 | gross_margin_change | 4443/4449/... | 毛利率变化——同上 |
| CLM-009 | quarterly_revenue | 165/136/160 | 季度类——index 主表是 FY，无 Q 分解 |
| CLM-010 | quarterly_net_profit_attributable | 165/136/160 | 同上 |
| CLM-015 | yoy_growth_revenue | 38 | 增长率——block 38 未进 index source_blocks |
| CLM-016 | publication_date | 9/6/2/4/3/... | 非财务指标（发布日期）——index 只含财务表 |
| CLM-024 | yoy_growth_revenue | 169/189 | 增长率——yoy 前缀未映射到 revenue 族 |
| CLM-H03 | yoy_growth_net_profit | 131/113 | holdout + 增长率 |
| CLM-H05 | yoy_growth_ocf | 131/113/132 | holdout + 增长率 |
| CLM-H07 | roe | 131/113/132 | holdout ROE——index 含吗？需查 |
| CLM-H08 | total_assets | 131/113 | holdout 总资产——index 应为 balance_sheet |
| CLM-H09 | yoy_growth_net_assets | 131/113 | holdout + 增长率 |
| CLM-H10 | publication_date | 9/2/6/3/... | 非财务指标 |
| CLM-H11 | deducted_net_profit | 131/113/132 | holdout 扣非——index 覆盖不足 |
| CLM-H12 | listing_info | 104/110/109 | 非财务指标（上市信息） |

## 4. 未覆盖根因分类

1. **增长率/比例类（8 条）**：yoy_growth_* / gross_margin / roe / gross_margin_change——evidence index 只从主表数值行生成对象，growth-only 或 ratio 对象缺失（index 的 growth 字段是派生值，但无独立对象；yoy 前缀在 _metric_family_compatible 中未剥除导致与 revenue 族不匹配）。
2. **季度类（2 条）**：quarterly_revenue / quarterly_net_profit——index 主表为 FY 年报，无 Q 分解对象。
3. **非财务指标（4 条）**：publication_date / listing_info——不属于财务表，index 天然不含（这些 claim 本不应走财务 fact 路径）。
4. **holdout 覆盖缺口（4 条）**：CLM-H03/H05/H07/H08/H09/H11 等 holdout 五粮液指标在 index 中缺失或未匹配——holdout 文档的财务表页未完整进入 index。

## 5. 结论

- Index 覆盖 46.7%——**超过一半 gold 事实在 index 中无对应对象**。
- Fact First Retrieval 即使完美执行，理论上限 ≈ 46.7% 的 claim 能通过 fact 路径召回（其中还需 value/period 匹配）。
- 需 Step 2/3 让 index 中存在的 fact 成为第一优先候选（覆盖 14 条），并保留 block 路径兜底（覆盖其余）。
- 未覆盖的 16 条中 8 条是增长率/比例类、2 条季度类——可考虑扩展 index 生成（本阶段聚焦"让已有 fact 进候选池"，不扩展 index 生成）。

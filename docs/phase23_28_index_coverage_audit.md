# Phase 23.28 Index Coverage Audit

> 生成时间：2026-08-06 UTC
> 审计对象：30 个 evaluation claims 的 Financial Evidence Index 覆盖（仅分析，未修改代码）

---

## 1. 覆盖总览

| 指标 | 数值 |
|---|---|
| Evaluation claims（有 gold block 参照） | 30 |
| Index exact metric 匹配 | 9（30.0%） |
| Index metric family 匹配 | 18（60.0%） |
| 无覆盖（需扩展） | 12（40.0%） |

Index 现有 metric_code：`total_operating_revenue` / `net_profit` / `net_profit_attributable` / `basic_eps` / `operating_cash_flow`（+1 空）。

## 2. 逐条分类（A/B/C/D/E）

| claim | metric | value | 分类 | 说明 |
|---|---|---|---|---|
| CLM-002 | total_operating_revenue | 4564.52 | **A EXACT_MATCH** | index 有 total_operating_revenue 对象 |
| CLM-003 | net_profit_attributable | 439.45 | **A** | index 有对象 |
| CLM-011 | net_profit_attributable | 124.22 | **A** | 同上 |
| CLM-012 | basic_eps | 5.8 | **A** | index 有 basic_eps |
| CLM-014 | operating_cash_flow | 533.46 | **A** | index 有对象 |
| CLM-018 | operating_cash_flow | 5334.59 | **A** | 同上 |
| CLM-H02 | net_profit_attributable | 89.54 | **A** | 同上 |
| CLM-H04 | operating_cash_flow | 297.06 | **A** | 同上 |
| CLM-H06 | basic_eps | 8.21 | **A** | 同上 |
| CLM-001 | revenue | 4564.52 | **B 需扩展 metric alias** | revenue→total_operating_revenue 家族匹配，但 index 无 revenue 字面对象 |
| CLM-007 | revenue | 1278.39 | **B** | 同上 |
| CLM-017 | revenue | 4071.5 | **B** | 同上 |
| CLM-H01 | revenue | 405.29 | **B** | 同上 |
| CLM-H16 | revenue | 4052.85 | **B** | 同上 |
| CLM-004 | yoy_growth_net_profit | 38.02 | **B** | yoy_ 前缀未剥除 → net_profit 族；需 alias 扩展 |
| CLM-015 | yoy_growth_revenue | 20.49 | **B** | yoy_ 前缀未剥除 → revenue 族 |
| CLM-024 | yoy_growth_revenue | 15 | **B** | 同上 |
| CLM-H03 | yoy_growth_net_profit | 38.02 | **B** | 同上 |
| CLM-005 | gross_margin | 26.4 | **C 需扩展 table parser** | 毛利率在附注/管理层讨论，非主表行——index 无 gross_margin |
| CLM-006 | gross_margin_change | 0.7 | **C** | 毛利率变化同上 |
| CLM-H07 | roe | 6.89 | **C** | ROE 在主要财务指标区，非主表行 |
| CLM-009 | quarterly_revenue | 2523.31 | **D PDF 存在但 index 未抽取** | 季度数据在季报/管理层讨论，index 主表仅 FY |
| CLM-010 | quarterly_net_profit_attributable | 260.14 | **D** | 同上 |
| CLM-H05 | yoy_growth_ocf | 12.47 | **D** | OCF 增长率在管理层讨论（index 有 operating_cash_flow 但无 growth 对象） |
| CLM-H08 | total_assets | 1899.84 | **D** | 总资产在资产负债表（index 未覆盖 balance_sheet 行？需核查） |
| CLM-H09 | yoy_growth_net_assets | 10.02 | **D** | 净资产增长率同上 |
| CLM-H11 | deducted_net_profit | 88.16 | **D** | 扣非净利润在附注 |
| CLM-016 | publication_date | None | **E PDF 没有该事实** | 发布日期非财务事实 |
| CLM-H10 | publication_date | None | **E** | 同上 |
| CLM-H12 | listing_info | None | **E** | 上市信息非财务事实 |

## 3. 分类统计

| 分类 | 数量 | 说明 |
|---|---|---|
| A EXACT_MATCH | 9 | index 已有 exact metric 对象 |
| B 需扩展 metric alias | 9 | revenue/yoy_* 族别名未归一 |
| C 需扩展 table parser | 3 | 比例类（gross_margin/roe）在主表外 |
| D PDF 存在但 index 未抽取 | 6 | quarterly/growth-ocf/total_assets/deducted 在附注/管理层讨论/季报 |
| E PDF 没有该事实 | 3 | publication_date/listing_info 非财务 |

## 4. 修复方向（对应 Task 2/3）

1. **Metric Alias 扩展（Task 3）**：解决 B 类 9 条——revenue 家族别名归一（revenue↔total_operating_revenue 已在 _metric_match 处理，但 index 侧需把 revenue 对象与 total_operating_revenue 合并计数）；yoy_growth_* 前缀剥除后匹配基础族。
2. **Index 抽取扩展（Task 2）**：解决 C/D 类 9 条——从附注（deducted_net_profit）、管理层讨论（gross_margin/roe/quarterly/growth）、资产负债表（total_assets）抽取更多财务事实；季度类需季报表或 MD&A 数据。
3. **E 类 3 条**：publication_date/listing_info 非财务事实，index 天然不含，不走 fact 路径（应 fallback 语义验证）。

**理论覆盖上限**：A+B+C+D = 27/30（90%）——若 B/C/D 全部解决，index 可覆盖 90% claims（当前 46.7%）。

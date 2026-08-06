# Phase 23.32 Fact Quality Audit

> 生成时间：2026-08-06 UTC
> 审计对象：Financial Evidence Index 全部 681 个 financial_fact 对象的质量

---

## 1. 总体质量统计

| 维度 | 数值 |
|---|---|
| Index 对象总数 | 681 |
| 单位分布 | 千元 240 / 空 348 / 元 79 / 万元 12 / 亿元 2 |
| 有 periods | 428（63%） |
| **无 periods（D_no_period）** | **253（37%）** |
| **metric 为空/泛化（E）** | **466（68%）** |
| 单位错误（B） | 22 |
| 列错位/值异常（C） | 9 |

**关键发现**：68% 对象 metric 为空或泛化（"收入"/"净利润"），37% 无期间——大量对象来自 notes/MD 章节抽取（Phase 23.28 扩展），但抽取质量未达标，多数是"含数字块"但缺指标名/期间。

## 2. 分类明细

### A. correct fact（约 200-250 个）
- 主表（income_statement/balance_sheet/cash_flow）中 metric_code 明确 + unit 合理 + periods 完整的对象。
- 如 id=3/4/5（营业收入 458,502,407千元，periods=[2025年度,2024年度]）。

### B. unit conversion error（22 个）
比例/每股类指标带金额单位：

| 样例 | metric | unit | current_value |
|---|---|---|---|
| id=18 | basic_eps | 元 | 22,314.0 |
| id=19 | basic_eps | 元 | 207,433.0 |
| id=20 | basic_eps | 元 | 43,994,595.0 |

**根因**：EPS 块与数值块窗口合并时，`_values_in` 把行标签块数字（如 22,314 可能是股数或其他）当作 current_value；EPS 应是无单位比值，却带"元"。

### C. table column error（9 个）
- basic_eps current_value > 100,000（id=19/20/21 等）——明显非每股收益（真实 EPS 5.8/8.21），是**列错位**：窗口把净利润/其他列的数值绑到 EPS。
- gross_margin current_value < 1（如 0.15）——毛利率应为 15-26%，0.15 是比例未乘 100 或错误列。

### D. period error（253 个无期间 + 少量异常年份）
- 253 个对象 periods 为空——主要为 notes/MD 章节块，页首无"2025年度"表头。
- CLM-H07 曾见 fact periods 含 "2062年"（年份提取噪声，Phase 23.24 修复后仍有残余）。

### E. metric extraction error（466 个）
- metric_code 为空或泛化（"收入"/"净利润"/""）。
- **根因**：notes/MD 章节的叙述块（如"公司实现收入增长…"）被窗口重建，`_metric_in` 无法提取规范指标名；或块自身无指标词、行标签块兜底失败。

## 3. 质量结论

| 分类 | 数量（约） | 对验证的影响 |
|---|---|---|
| A correct | 200-250 | 可安全参与 SUPPORTED/REFUTED |
| B unit error | 22 | 若参与判定 → 错误 REFUTED（EPS 值巨大） |
| C column error | 9 | 若参与判定 → 错误 REFUTED |
| D period error | 253 | period_match 失败 → 已由 Phase 23.31 period-aware 转 UNKNOWN |
| E metric error | 466 | metric_match 失败 → 不参与 SUPPORTED（多数走 UNKNOWN） |

**核心**：大量低质量 fact（B/C/E）若进入 SUPPORTED/REFUTED 判定会造成误判；当前 verifier 的 metric_match 门槛已挡住 E 类（metric 不匹配→UNKNOWN），但 B/C 类（metric 匹配但 value 异常）会错误 REFUTED——需 Task 2 quality score 把关。

## 4. 修复方向（对应 Task 2）

1. **financial_fact_quality_score（Task 2）**：metric confidence（metric_code 非空且规范）+ unit confidence（比例类不带金额单位）+ period confidence（periods 非空且年份合理）+ source table confidence（income_statement/balance_sheet/cash_flow 主表 > notes/MD）。
2. **低质量 fact 不得参与 SUPPORTED/REFUTED**：quality score 低于阈值 → 强制 UNKNOWN。
3. **B/C 修复**：basic_eps 类指标要求 current_value 合理范围（0-1000）；比例类（gross_margin/roe）要求 0-100。

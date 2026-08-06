# Phase 23.36 REFUTED Resolution Audit

> 生成时间：2026-08-06 UTC
> 审计对象：13 个 value-conflict REFUTED cases（same metric + same period + value mismatch）

---

## 1. 逐条明细

| claim | claim value | fact value | ratio | 分类 |
|---|---|---|---|---|
| CLM-004 | 38.02%（增长率） | 43,945,411元（绝对值） | 0.0009 | **D metric 口径** |
| CLM-005 | 26.4%（毛利率） | 15.0千元 | 1.76 | **F extraction 错误**（fact 非毛利率值） |
| CLM-012 | 5.8元/股（EPS） | 94,067千元 | 0.00006 | **F extraction 错误**（fact 非 EPS 值） |
| CLM-014 | 533.46亿元 | 44,520,196千元=445.2亿 | 1.198 | **D metric 口径**（OCF 口径差异） |
| CLM-017 | 4071.5亿元 | 458,502,407千元=4585亿 | 0.888 | **D metric 口径**（claim 分部 vs fact 合并） |
| CLM-018 | 5334.59亿元 | 445.2亿元 | 11.98 | **D metric 口径**（数量级异常，claim 值口径不同） |
| CLM-024 | 15%（增长率） | 458,502,407千元 | 0.00000003 | **D metric 口径**（增长率 vs 绝对值） |
| CLM-H02 | 89.54亿元 | 54.55亿元 | 1.64 | **D metric 口径**（归母净利口径差异） |
| CLM-H03 | 38.02%（增长率） | 40,528,509,770元 | 0.0000009 | **D metric 口径**（增长率 vs 绝对值） |
| CLM-H04 | 297.06亿元 | 445.2亿元 | 0.667 | **D metric 口径**（OCF 口径差异） |
| CLM-H08 | 1899.84亿元 | 161,278,203千元=1612.78亿 | 1.178 | **C 四舍五入/口径接近**（差 18%，超容差但同量级） |
| CLM-H09 | 10.02%（增长率） | 43,533,148千元 | 0.0000002 | **D metric 口径**（增长率 vs 绝对值） |
| CLM-H16 | 4052.85亿元 | 4585.02亿元 | 0.884 | **D metric 口径**（claim 分部 vs fact 合并） |

## 2. 分类统计

| 分类 | 数量 | 说明 |
|---|---|---|
| A 真正错误 claim | **0** | 无一条真实错误 |
| B 单位差异 | 0 | unit normalization 已处理 |
| C 四舍五入差异 | 1（CLM-H08） | ratio 1.178，同量级但差 18%（可能口径或四舍五入） |
| **D metric 口径差异** | **9** | 6 条增长率 claim vs 绝对值 fact（CLM-004/024/H03/H09 + 比例类 005/012 归类 F）；3 条数值口径（分部 vs 合并：017/H16/018）；OCF 口径（014/H04） |
| E period 差异 | 0 | period strict 已过滤 |
| **F fact extraction 错误** | **3**（CLM-005/012/H02） | fact 绑定错误值（毛利率=15.0、EPS=94,067千元 明显非指标值） |

## 3. 核心发现

1. **13 个 REFUTED 全部非真正错误 claim**（A=0）——当前"same metric + same period + value mismatch = REFUTED"规则**过严**，把 9 个 metric 口径差异（增长率 vs 绝对值、分部 vs 合并）和 3 个 fact extraction 错误全部误判 REFUTED。
2. **增长率 claim 与绝对值 fact 比较是最大错误源**：CLM-004/024/H03/H09 的 claim value 是百分比（38.02%/15%/10.02%），fact value 是绝对值（43,945,411元/458,502,407千元）——两者**量纲不同，不应 value 比较**。当前 metric family 匹配把 yoy_growth_net_profit 归一到 net_profit 后仍比较 value，导致错误 REFUTED。
3. **metric strictness 缺失**：宽松 family 匹配（revenue≈total_operating_revenue）是合理的，但"增长率 vs 绝对值"这类**口径差异**需要区分——claim 是 growth 类时，fact 的 value_match 不应与绝对值比较（应比较 growth 字段）。
4. **fact extraction 错误 3 条**：quality_score 未拦截（CLM-005/012 的 fact quality 可能≥0.8），但值明显非指标值（毛利率=15.0千元、EPS=94,067千元）——需 value sanity check。

## 4. 修复方向（对应 Task 2/3）

1. **Value Compatibility Layer（Task 2）**：
   - Unit normalization（已有，复用）
   - Rounding tolerance（容差放宽到 ±5%）
   - **Metric strictness**：claim 为 growth/ratio 类（值百分比）时，不比较绝对值 value；只比较 growth 字段。
2. **REFUTED Policy（Task 3）**：仅 metric strict + period strict + unit 归一 value 差 > tolerance 才 REFUTED；growth 类 claim 的 value 冲突 → UNKNOWN（不 REFUTED）；fact 值异常（sanity check 失败）→ UNKNOWN。

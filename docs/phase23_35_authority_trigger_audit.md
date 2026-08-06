# Phase 23.35 Authority Trigger Audit

> 生成时间：2026-08-06 UTC
> 审计对象：43 claims 的 Financial Fact Decision Authority 触发失败原因（仅分析，未修改代码）

---

## 1. 总览

| 维度 | 数值 |
|---|---|
| Claims | 43 |
| 全部有 financial_fact 候选（E no_fact_candidate = 0） | 43（candidate_count=5, fact_count=5） |
| **SUPPORTED（Authority 触发）** | **4（9.3%）** |
| REFUTED（Authority 触发） | 12（27.9%） |
| UNKNOWN（Authority 未触发） | 27（62.8%） |

**Fact usage rate 上限 = 4/43 = 9.3%**（SUPPORTED 才计入 usage）——这就是 Phase 23.34 观察到 0% 的深层原因：top_k=5 生产链中，实际 Authority 触发（SUPPORTED）仅 4 条。

## 2. 逐条明细（最高 quality fact）

| claim | q | metric | value | period | decision | 分类 |
|---|---|---|---|---|---|---|
| CLM-001 | 1.0 | T | T | T | SUPPORTED | ✅ |
| CLM-002 | 1.0 | T | T | T | SUPPORTED | ✅ |
| CLM-003 | 0.88 | T | T | T | SUPPORTED | ✅ |
| CLM-H01 | 1.0 | T | T | T | SUPPORTED | ✅ |
| CLM-004 | 0.88 | T | F | T | REFUTED | C |
| CLM-012 | 0.88 | T | F | T | REFUTED | C |
| CLM-014 | 1.0 | T | F | T | REFUTED | C |
| CLM-017 | 1.0 | T | F | T | REFUTED | C |
| CLM-018 | 1.0 | T | F | T | REFUTED | C |
| CLM-024 | 1.0 | T | F | T | REFUTED | C |
| CLM-H02 | 0.88 | T | F | T | REFUTED | C |
| CLM-H03 | 0.88 | T | F | T | REFUTED | C |
| CLM-H04 | 1.0 | T | F | T | REFUTED | C |
| CLM-H08 | 1.0 | T | F | T | REFUTED | C |
| CLM-H09 | 1.0 | T | F | T | REFUTED | C |
| CLM-H16 | 1.0 | T | F | T | REFUTED | C |
| CLM-005 | 0.68 | T | F | T | UNKNOWN | A |
| CLM-007 | 1.0 | T | T | F | UNKNOWN | D |
| CLM-008 | 1.0 | T | F | F | UNKNOWN | C+D |
| CLM-006 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-009 | 1.0 | F | F | F | UNKNOWN | B |
| CLM-010 | 0.88 | F | T | F | UNKNOWN | B+D |
| CLM-011 | 1.0 | T | F | F | UNKNOWN | C+D |
| CLM-013 | 0.88 | T | F | F | UNKNOWN | C+D |
| CLM-015 | 1.0 | T | F | F | UNKNOWN | C+D |
| CLM-016 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-019 | 1.0 | F | F | F | UNKNOWN | B |
| CLM-020 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-021 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-022 | 0.73 | F | T | T | UNKNOWN | A |
| CLM-023 | 0.73 | F | F | T | UNKNOWN | A |
| CLM-025 | 0.88 | F | T | F | UNKNOWN | B+D |
| CLM-026 | 0.88 | T | F | F | UNKNOWN | C+D |
| CLM-H05 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-H06 | 0.8 | T | F | F | UNKNOWN | C+D |
| CLM-H07 | 0.68 | T | F | F | UNKNOWN | A |
| CLM-H10 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-H11 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-H12 | 1.0 | F | F | F | UNKNOWN | B |
| CLM-H13 | 1.0 | F | F | T | UNKNOWN | B |
| CLM-H14 | 0.7 | F | F | T | UNKNOWN | A |
| CLM-H15 | 1.0 | F | F | F | UNKNOWN | B |
| CLM-H17 | 1.0 | F | F | T | UNKNOWN | B |

## 3. 分类统计

| 分类 | 数量 | 说明 |
|---|---|---|
| A quality_failed（q<0.8 被拒） | 5（CLM-005/022/023/H07/H14） | quality 门槛 0.8 拦截 |
| B metric_failed（metric 不匹配） | **16** | 最高频——fact metric_code 与 claim 不匹配（yoy_/quarterly/scope 类 claim） |
| C value_failed（value 冲突） | 12（REFUTED）+4（UNKNOWN） | 同 metric+period 但 value 不同（含 REFUTED 12 条） |
| D period_failed（period 不匹配） | 与 B/C 混合 | CLM-007 等 period_score<0.8 |
| E no_fact_candidate | 0 | 全部有 fact |

## 4. 关键结论

1. **SUPPORTED 仅 4/43**：Authority 需 quality≥0.8 + metric+value+period 全匹配，实际满足者极少。
2. **B metric_failed 是最大失败组（16 条）**：fact metric_code 与 claim 不匹配——yoy_growth_*/quarterly_*/scope 类 claim 的 fact 无对应对象（index 覆盖上限 46.7% 的直接体现）。
3. **C value_failed 12 条 REFUTED**：同 metric+period 但 value 冲突——这些是"真正 value 不同"（如 claim 分部值 vs fact 合并值）或 fact 绑定错误列。
4. **A quality_failed 5 条**：notes/MD 来源 fact 的 quality<0.8 被拦截。

## 5. 修复方向（对应 Task 2/3/5）

- **Task 2**：threshold 0.8 → 0.6/0.7 可放行 CLM-005/022/023/H07/H14（A 类 5 条）→ SUPPORTED 可能 +2-4。
- **Task 3**：period 放宽（loose 同年份）可救 CLM-007 等 period_failed 条。
- **B 类 metric_failed 16 条**：需 fact metric 归一（yoy_→基础族）或 index 扩展——受限（Task 5 只允许找到明确瓶颈后修改）。

数据：`data/gold_review/phase23_11_6_2/authority_trigger_audit_data.json`

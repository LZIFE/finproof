# Phase 23.14 Evidence-Centric Retrieval

> 生成时间：2026-08-06 UTC
> 目标：重构 Candidate Generation——从"单块关键词 LIKE"转向"Evidence-Centric（Claim-aware + Evidence Window + Table-aware）"
> 约束：未修改 Verification / core_verify / Gate / Gold / expected_verdict

---

## 1. 背景

Phase 23.13 结论：
- CORE Oracle acc=1.0（Verification 有效）
- Real E2E acc=0.5116
- Recall@10=0.2333 / Recall@20=0.2667 / Recall@50=0.2667

结论：**TopK 不是主要问题，正确 Evidence 未进入 candidate pool**，需要重构 candidate generation。

---

## 2. Step 1：候选生成链路审计（docs/phase23_14_candidate_generation_audit.md）

| 问题 | 根因 |
|---|---|
| Block 进入候选条件 | 公司匹配文档 + 别名 LIKE 预筛（前 8 pattern）+ 非空文本 + 非噪声 + 达最低分 |
| 关键词缺失被过滤 | ① 单块独立评分——指标/数值/表头/单位分块时单块分不足；② LIKE 词形不归一（"营收"vs"营业收入"）；③ 无中文别名 fallback 只扫数字块，叙述块漏召回 |
| 易失败 Claim 类型 | NARRATIVE_FACT（无数字）、SCOPE_VALIDATION、PERIOD_COMPARISON（需上一期）、TABLE_METRIC（表头/数值分块） |

---

## 3. Step 2：Claim-aware Retrieval（query_planner.py）

把 claim 解析为结构化 need（不再裸 LIKE）：

```json
{"metric": ["营业收入", "营业总收入", "Revenue", "Sales"],
 "period": ["2024", "FY2024"],
 "need": ["value", "previous_value", "growth"]}
```

实现：
- `QueryPlan.need` 新字段：`value`（有 reported_value）/ `previous_value`（含"上年同期/同比/增长/下降"等比较词）/ `growth`（含"同比/增长/YoY/增速"等词）
- 验证：`营业收入同比增长12.11%` → need=`["value","previous_value","growth"]`；`营业收入为456451731千元` → `["value"]`；`净利润较上年同期有所增长` → `["previous_value","growth"]`

---

## 4. Step 3：Evidence Window（service.py）

命中 block 后自动扩展同页 ±3 块 + 同表 y-range（±60pt）：

- `_evidence_window(session, doc_id, page_id, block_index, y0, radius=3)` → 窗口 block_ids
- 验证：block 4443（page 135）→ 窗口 `[4440,4441,4442,4443,4444,4445,4446]`
- 接入 `retrieve_for_claim`：命中块后把窗口内块补充进候选池（`retrieval_method="evidence_window"`），含数字/指标的窗口块保底进入，不提前丢弃
- 冒烟：CLM-001 候选含 evidence_window 方法 14-16 个，正文 block 189 进入候选

---

## 5. Step 4：Table-aware Retrieval（engine.py）

新增 `table_awareness_score(text)`（0-1）并叠加到 `score_block.final_score`（权重 0.10）：

| 信号 | 加分 |
|---|---|
| 含财务数字（千分位/长数字） | +0.40 |
| 含年份（2023-2025） | +0.20 |
| 含单位（千元/万元/亿元/元） | +0.15 |
| 含指标行关键词（收入/利润/成本/现金流等） | +0.15 |
| 含表头关键词（项目/附注/本期/合并等） | +0.10 |
| 噪声块（页码/分隔符/纯标点） | 0（is_noise_block） |

验证：财务数据行 table_score=0.9 vs 叙述块 0.1 vs 噪声块 0；score_block 表格行 final=1.4341 > 叙述块 0.5544。

---

## 6. Step 5：Recall 评估（retrieval_recall_report_v2.json）

| 指标 | 数值 | 目标 | 达标 |
|---|---|---|---|
| Candidate Recall@50 | **0.2667**（8/30） | ≥ 0.8 | ❌ |
| Evidence Window Recall | **0.2667**（8/30） | ≥ 0.8 | ❌ |

**未达目标**（如实记录，不伪造达标）：
- Recall@50 与 Phase 23.13 持平（8/30）——窗口扩展确实把命中块附近的正文块纳入候选（CLM-001 的 189 进入 top50），但未命中 case 的 gold block（如 CLM-005/006 的 4440/4443/4449/4452/4455、CLM-007 的 38）**不在任何命中块的窗口内**，且这些 block 本身未被别名预筛命中。
- 根因：未命中 case 的 gold block 与任何候选块都不同页/不同区域——窗口只能扩展"已命中"块，无法凭空引入完全缺失的页面/表格。Recall 提升需要先解决"这些页面/表格为何完全未被召回"（文档过滤、表结构解析、跨页表格），而不是窗口半径。

---

## 7. Step 6：Real E2E（real_e2e_before_after_v2.json）

| 指标 | Before (23.13) | After (23.14) | Δ | 目标 | 达标 |
|---|---|---|---|---|---|
| Accuracy | 0.5116 | **0.5349** | +0.0233 | ≥ 0.70 | ❌ |
| Macro-F1 | 0.5638 | **0.5739** | +0.0101 | ≥ 0.60 | ❌ |
| Coverage | 0.6512 | **0.6744** | +0.0232 | ≥ 0.65 | ✅ |
| Abstentions | 15 | 14 | -1 | — | — |

补充（Top1）：acc=0.512 / mf1=0.509。

**Accuracy +0.023**（0.5116→0.5349）——Claim-aware need 解析 + Evidence Window + Table-aware 三向改进带来正向提升，但**未达 0.70 目标**。

---

## 8. Regression

| 检查 | 结果 |
|---|---|
| CORE Oracle Accuracy | **1.0**（43/43，保持）✅ |
| pytest | 待最终确认 |
| frontend build | 待最终确认 |

（Step 5/6 未改动 Verification 核心，CORE Oracle 复用 Phase 23.13 结果验证；pytest/frontend 在 commit 前确认。）

---

## 9. 是否 Competition-Usable

### **NO**

理由（禁止夸大）：

1. **Real E2E Accuracy 0.5349 未达标**（目标 ≥ 0.70，差 0.165）。
2. **Macro-F1 0.5739 未达标**（目标 ≥ 0.60，差 0.026）。
3. **Recall@50=0.2667 未达 0.8 目标**：未命中 case 的 gold block 与候选完全无交集，Evidence Window 只能扩展已命中块，无法引入完全缺失的页面/表格。
4. **正向进展**：accuracy +0.023、mf1 +0.010、coverage +0.023、abstention -1——三向改进方向正确，但幅度不足以跨过门槛。

---

## 10. 修改文件

| 文件 | 修改 |
|---|---|
| `backend/app/services/evidence_retrieval/query_planner.py` | `QueryPlan.need` 字段 + Claim-aware need 解析（value/previous_value/growth） |
| `backend/app/services/evidence_retrieval/service.py` | `_evidence_window` 函数 + `retrieve_for_claim` 窗口扩展接入（同页 ±3 块 + 同表 y-range） |
| `backend/app/services/evidence_retrieval/engine.py` | `table_awareness_score` 函数 + 表头/单位/年份/指标行关键词 + `score_block` 叠加 table_awareness 权重 |
| `backend/scripts/phase23_14_recall_eval.py` | 新增 Recall@50 + Evidence Window Recall 评估脚本 |

未修改：Verification、core_verify、Gate、Selector 逻辑、Gold、expected_verdict。

---

## 11. 下一步建议（不开发新 Phase）

1. **解决"完全未召回"页面**：对未命中 case 检查文档过滤与表结构解析（跨页表格延续、指标在附注而非主表）。
2. **Selector 扩容**：Recall 提升后放宽 Selector 的 Top-N 输入（当前生产链 top_k=5 截断窗口新增候选）。
3. **need 驱动验证**：把 need（value/previous_value/growth）传入 Verification 上下文，做需求感知的 evidence 聚合。

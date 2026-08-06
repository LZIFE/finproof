# Phase 23.15 Financial Document Intelligence Retrieval

> 生成时间：2026-08-06 UTC
> 目标：建立 Document Understanding Layer（章节索引 + 表格检测 + Claim→Section 路由），改造检索为 section→table→block 三级
> 约束：未修改 Verification / core_verify / Gate / Selector verdict / Gold / expected_verdict

---

## 1. 背景

Phase 23.14 结论：
- CORE Oracle acc=1.0（Verification 有效）
- Real E2E acc=0.5349
- Candidate Recall@50=0.2667

结论：**失败不是 Verification 问题、不是 Window 问题——正确 Evidence 所在 document region 没有进入 candidate pool**。需建立 Document Understanding Layer（只改 Document understanding + Retrieval）。

---

## 2. Step 1：Document Structure Analysis

**产物**：`backend/artifacts/gold_contract/phase23_15_document_sections.json`（57 个章节）
**脚本**：`backend/scripts/phase23_15_document_structure.py`

逐页扫描 PDF 页首文本，识别章节起始页并合并连续同类型页为章节：

| section_type | 数量 | 识别关键词 |
|---|---|---|
| income_statement | 7 | 合并及公司利润表 / 利润表 |
| balance_sheet | 9 | 合并及公司资产负债表 / 资产负债表 |
| cash_flow | 7 | 合并及公司现金流量表 / 现金流量表 |
| notes | 15 | 财务报表附注 / 附注 |
| management_discussion | 6 | 管理层讨论与分析 / 经营情况讨论与分析 |
| financial_highlights | 5 | 主要会计数据 / 主要财务指标 |
| equity_changes | 3 | 所有者权益变动表 |
| business / company_profile | 5+5 | 业务概要 / 公司简介 |

字段：`id / document_id / page_start / page_end / section_type / confidence`

关键验证：page 135（合并利润表）→ `income_statement`；page 132（资产负债表）→ `balance_sheet`；page 137（现金流量表）→ `cash_flow`。

---

## 3. Step 2：Table Detection

**产物**：`backend/artifacts/gold_contract/phase23_15_tables.json`（611 个表格页，485 个关联 block_ids）
**脚本**：`backend/scripts/phase23_15_document_structure.py`

识别表格页特征：表头关键词（项目/附注/2025年度/本期金额）+ 指标行关键词（收入/利润/资产/负债/现金流）+ 单位（千元/万元/亿元）+ 财务数字。

| table_type | 数量 | 说明 |
|---|---|---|
| income_statement | 9 | 利润表页（doc1: 126/135/136，doc2: 96/168） |
| balance_sheet | 13 | 资产负债表页（doc1: 132/133/222/259） |
| cash_flow | 13 | 现金流量表页（doc1: 137/232-235） |
| equity_changes | 2 | 所有者权益变动表 |
| other | 574 | 其他表格页（含财务数据表） |

字段：`table_type / page / blocks（block_ids 列表）/ has_numbers / has_units`

已知限制：126 个空 blocks 全属 doc=3（annual_report 副本缺 document_pages 记录），不影响主文档（doc=1/2）检索。

---

## 4. Step 3：Claim → Section Routing

**产物**：`backend/artifacts/gold_contract/phase23_15_claim_section_routing.json`（43 条 Claims 全路由）
**模块**：`backend/app/services/evidence_retrieval/claim_routing.py`（服务层，被检索调用）
**脚本**：`backend/scripts/phase23_15_claim_routing.py`

| Claim 类型 | 路由章节 |
|---|---|
| Revenue / total_operating_revenue | income_statement, management_discussion |
| Net profit / attributable / deducted | income_statement |
| Total assets / net assets / debt | balance_sheet |
| Operating cash flow | cash_flow |
| Growth (yoy/qoq) | management_discussion + income_statement |
| 兜底 | 全部财务章节 |

路由优先级：metric_code 前缀（含 growth_ 剥除）→ metric 文本关键词 → claim 原文关键词 → route 类型补充 → 兜底。

43 条 Claims 覆盖：income_statement 37 / management_discussion 24 / cash_flow 8 / balance_sheet 7 / notes 5 / business 2。

---

## 5. Step 4：Retrieval Pipeline 三级改造

**模块**：`backend/app/services/evidence_retrieval/section_index.py`（章节/表格索引加载 + 页类型查询 + 目标页集合 + 加分）

接入 `retrieve_for_claim`（service.py）：

```
claim → route_sections_for_claim（目标章节）
      → section_index.target_pages_for_claim（章节页集合）
      → section_index.table_pages_for_types（目标表格页）
      → block 检索（目标章节页/表格页块加分：sec_bonus +0.10、tbl_bonus +0.10）
```

- **不再直接全文 block 搜索**：目标章节页块获得排序加成，表格页块优先。
- 非目标章节页不加分也不过滤（保留 fallback 召回兜底）。

冒烟验证：CLM-001（revenue）→ 路由 `[income_statement, management_discussion]` → block 189 进入 top50 ✅

---

## 6. Step 5：Recall 评估（retrieval_recall_report_v3.json）

| 指标 | 数值 | 目标 | 达标 |
|---|---|---|---|
| Candidate Recall@50 | **0.2667**（8/30） | ≥ 0.8 | ❌ |
| Section Recall | **0.1667**（5/30） | — | 低 |
| Table Recall | **0.5333**（16/30） | — | 中 |

**未达目标（如实记录，不伪造达标）**：
- Section Recall 仅 0.1667：gold evidence 所在物理页（grounding existing_page）大多不在 claim 路由的目标章节页集合内——**路由章节页与真实证据页的映射错位**（grounding existing_page 是上游标注页，可能与 document_sections 的财务表章节页不一致）。
- Table Recall 0.5333：过半 gold 页是表格页，但 46.7% 未命中（上游标注页 vs 表格索引页差异）。
- Candidate Recall@50 与 Phase 23.14 持平（8/30）——三级检索加分未改变头部排序，未命中 case 的 gold block 依旧不在候选池。

---

## 7. Step 6：Real E2E（real_e2e_before_after_v3.json）

| 指标 | Before (23.14) | After (23.15) | Δ | 目标 | 达标 |
|---|---|---|---|---|---|
| Accuracy | 0.5349 | **0.5349** | 0.0000 | ≥ 0.70 | ❌ |
| Macro-F1 | 0.5739 | **0.5739** | 0.0000 | ≥ 0.60 | ❌ |
| Coverage | 0.6744 | **0.6744** | 0.0000 | ≥ 0.65 | ✅ |
| Abstentions | 14 | 14 | 0 | — | — |

**Accuracy 持平（0.5349）**，未达 0.70 目标。三级检索的章节加分未改变 Top3 排序结果。

---

## 8. Regression

| 检查 | 结果 |
|---|---|
| CORE Oracle Accuracy | **1.0**（43/43，保持）✅ |
| pytest | **903 passed** ✅ |
| frontend build | **success** ✅ |

---

## 9. 是否 Competition-Usable

### **NO**

理由（禁止夸大）：

1. **Real E2E Accuracy 0.5349 未达标**（目标 ≥ 0.70，差 0.165）。
2. **Candidate Recall@50=0.2667 未达 0.8 目标**；Section Recall=0.1667 说明"章节路由 → 证据页"映射错位。
3. **三级检索方向正确但未生效于排序**：目标章节页加分（+0.10）量级不足以把正确 evidence 从"未召回"变为"Top3 命中"——未命中 case 的 gold block 与其所在章节页本身未被索引/路由覆盖。
4. **根因**：Document Understanding Layer 已建立（57 章节 + 611 表格 + 路由），但 (a) grounding existing_page 与财务表章节页不一致（评估参照偏差），(b) 加分量级不足以改变头部排序，(c) 未命中 case 的文档区域仍未被任何索引覆盖。

---

## 10. 修改文件

| 文件 | 修改 |
|---|---|
| `backend/scripts/phase23_15_document_structure.py` | 新增：章节索引 + 表格检测脚本 |
| `backend/scripts/phase23_15_claim_routing.py` | 新增：Claim→Section 路由脚本（43 条路由表） |
| `backend/scripts/phase23_15_recall_eval.py` | 新增：三级检索 Recall 评估脚本 |
| `backend/app/services/evidence_retrieval/claim_routing.py` | 新增：服务层路由模块（被检索调用） |
| `backend/app/services/evidence_retrieval/section_index.py` | 新增：章节/表格索引加载 + 目标页 + 加分 |
| `backend/app/services/evidence_retrieval/service.py` | `retrieve_for_claim` 接入三级检索（路由 + 章节/表格页加分） |

未修改：Verification、core_verify、Gate、Selector verdict、Gold、expected_verdict。

---

## 11. 下一步建议（不开发新 Phase）

1. **对齐 grounding 页与章节页**：核对 gold evidence 的 existing_page 与 document_sections 章节边界的映射，修正 Section Recall 评估参照。
2. **提升加分量级/直接页过滤**：目标章节页块可显著加分（如 +0.30）或作为候选强约束，确保正确区域块进入 Top3。
3. **扩大索引覆盖**：未命中 case 的文档区域（附注中的财务数据表、经营分析中的分部数据）需纳入表格/章节索引。

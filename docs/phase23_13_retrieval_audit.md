# Phase 23.13 Retrieval Pipeline 审计

> 生成时间：2026-08-06 UTC
> 审计对象：`backend/app/services/evidence_retrieval/`

---

## 1. Candidate Generation 在哪里？

| 环节 | 文件:行 | 说明 |
|---|---|---|
| 候选块生成 | `service.py:69-90` `_candidate_blocks` | 按指标别名 LIKE 预筛（最多 8 个 pattern）；aliases 为空或块含数字时全量扫描（fallback） |
| 块评分 | `service.py:158-194` `retrieve_for_claim` 主循环 | 对每个候选块调用 `score_block`（metric/value/period/entity/text 五分量 + page/table/section/evidence_quality 加成） |
| 阶段式候选 | `stage_retrieval.py:82-191` `stage_a_candidates` | Stage A：Top50（lexical/semantic/entity/metric/numeric/period/unit/scope 多通道评分） |
| 重排 | `stage_retrieval.py` `stage_b_rerank` | Stage B：对 Stage A Top50 重排取 Top5 |
| 表上下文 | `table_context.py` | 表格区域上下文组装 |

**结论**：候选生成存在两套并行入口——`service.retrieve_for_claim`（生产链 verify_real_e2e 使用）与 `stage_retrieval`（早期评估链）。Real E2E 实际走 `service.retrieve_for_claim`（top_k=5 默认）。

## 2. 什么时候过滤 Document？

| 环节 | 文件:行 | 过滤逻辑 |
|---|---|---|
| 文档过滤 | `service.py:42-63` `filter_documents` | ① `Document.document_role == "SOURCE_DOCUMENT"`（排除示例/模板）② `Document.company_name == entity` **精确字符串相等** ③ `Document.stock_code == stock` ④ 兜底：仅 stock_code 过滤 |

**关键风险**：
- `company_name == entity` 是**精确匹配**——若 claim 的 entity 是"美的集团"而 DB 存"美的集团股份有限公司"，或 entity 是简称"美的"，则**过滤掉全部文档 → 0 候选**（CLM-H11 cand_before=0 即此类）。
- 兜底只对 `stock` 生效，不对 entity 简称生效。

## 3. 什么时候限制 Page？

| 环节 | 文件:行 | 说明 |
|---|---|---|
| 页级限制 | 无显式页限制 | `_candidate_blocks` 遍历 doc 全部页；`retrieve_for_claim` 无 page 上限 |
| 页级加分 | `service.py:209-213` | page_bonus：同页同时含 metric+value+period 时 +0.10 |
| 表格区域 | `service.py:214-226` | y 坐标分桶（5pt）标记 table_blocks，+0.05 |

**结论**：无页数截断（页过滤不是丢召回主因），但有 page_bonus/table_bonus 排序加成。

## 4. 什么时候限制 TopK？

| 环节 | 文件:行 | 限制 |
|---|---|---|
| `retrieve_for_claim` | `service.py:245` `scored[:top_k]` | **默认 top_k=5** ← 生产链硬限制 |
| `run_retrieval` | `service.py:255` `top_k=5` | 批处理同样 5 |
| `stage_a_candidates` | `stage_retrieval.py:191` `scored[:top_k]` | top_k=50 |
| `stage_b_rerank` | 输出 Top5 | Top5 |
| `retrieve_via_channels` | `service.py:489-491` | 去重后 `[:top_k]` |

**关键风险**：生产链 `retrieve_for_claim` 直接截断 Top5——若 Gold block 排在 6-10 名，**在 Selector 之前就被丢弃**（"召回但排名低" 9/21 的直接原因之一）。

## 5. 哪些错误 Case 在过滤阶段丢失？

基于 Phase 23.12 `retrieval_failure_analysis.json`（21 个错误 case）：

### 5.1 正确 Evidence 未召回（12 条，57.1%）

| 候选丢失环节 | 原因 | 受影响特征 |
|---|---|---|
| Document 过滤（`company_name == entity` 精确匹配） | entity 简称/历史名/代码与 DB 不一致 → 文档整组丢失 | cand_before=0 或极低（CLM-H11、CLM-026、CLM-H02） |
| Block LIKE 预筛（`_candidate_blocks` 最多 8 个别名 pattern） | 指标别名未覆盖（如"营收"vs"营业收入"、"同比增长率"），LIKE 只取前 8 个 pattern | 指标块未进候选 |
| fallback 判定 | 无中文别名时全量扫含数字块，但 `MIN_CANDIDATE_SCORE` 门槛可能过滤低分块 | 含数字但指标/期间未命中的块 |

### 5.2 召回但排名低（9 条，42.9%）

| 排名丢失环节 | 原因 |
|---|---|
| `scored[:top_k=5]` 截断 | Gold block 排 6-10，Selector 前即被丢弃 |
| 排序权重偏向 | 叙述类/无数字语义主张（NARRATIVE_FACT、SCOPE_VALIDATION）在五分量下排名不足 |

### 5.3 具体错误 case 分布

| 分类 | Case 数 | 代表 Case |
|---|---|---|
| Document 过滤丢失 | 3 | CLM-H11（cand_before=0）、CLM-026、CLM-H02 |
| Block 预筛/门槛丢失 | 9 | CLM-006/009/010/011/016/019、CLM-H03/H05/H09 |
| Top5 截断（排名低） | 9 | CLM-002/003/005/022/024/025、CLM-H06/H12/H17 |

---

## 审计结论

1. **候选生成**在 `service.py:_candidate_blocks` + `score_block`；**文档过滤**在 `service.py:filter_documents`（精确 company 匹配是最大漏召回源）。
2. **TopK 截断**在生产链为 Top5（`service.py:245`），是"召回但排名低"9 条的直接原因。
3. **Page 无限制**（页过滤不是主因）。
4. **Recall 扩张重点**：(a) 文档过滤放宽（简称/代码/模糊匹配），(b) 候选 TopK 提升（5 → 20/50），(c) 指标别名扩展，(d) 表感知优先。

下一步（Step 2）：实现多阶段召回（Entity → Metric → Broad Page → Table-aware），并放宽文档过滤与 TopK。

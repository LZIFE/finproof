# Phase 23.16 Retrieval 审计

> 生成时间：2026-08-06 UTC
> 审计对象：当前 Retrieval candidate generation + ranking 全链路

---

## 1. 当前候选生成链路

```
claim
  ├─ filter_documents（公司精确匹配 → 实体别名反查 → 前2字前缀放宽）
  ├─ route_sections_for_claim（Phase 23.15：claim → 目标章节类型）
  │    └─ section_index.target_pages_for_claim / table_pages_for_types（章节页/表格页）
  ├─ _candidate_blocks（Phase 4A：指标别名 LIKE 预筛，最多 8 个 pattern）
  │    ├─ fallback_mode：无中文别名 → 全量扫描含数字块
  │    └─ Broad Page（Phase 23.13：候选不足时全量补扫含数字块）
  ├─ score_block 评分（五分量 + 加成）
  │    ├─ metric 0.35 / value 0.30 / period 0.15 / entity 0.10 / text 0.10
  │    ├─ page_bonus / table_bonus / section_bonus / evidence_quality / table_awareness（各 0.05-0.10）
  │    ├─ 单位注入（页首单位声明）
  │    └─ 噪声块归零（is_noise_block）
  ├─ _evidence_window（Phase 23.14：命中块 → 同页 ±3 块 + 同表 y-range 补充）
  ├─ 目标章节页/表格页加分（Phase 23.15：sec_bonus +0.10 / tbl_bonus +0.10）
  ├─ scored.sort(key=-final_score)
  └─ final = scored[:top_k]（生产链 top_k=5）
```

## 2. 当前 Ranking 机制

**单一加权评分**：`score_block` 输出 `final_score = Σ(w_i * score_i) + bonuses`，然后**直接按 final_score 降序取 top_k**。无第二级 reranker。

| 评分项 | 权重 | 说明 |
|---|---|---|
| metric | 0.35 | 指标别名命中（LIKE 子串） |
| value | 0.30 | 数值匹配（单位换算后） |
| period | 0.15 | 期间关键词/文档期间 |
| entity | 0.10 | 公司名/简称/代码 |
| text | 0.10 | 原文字符相似度（Jaccard） |
| page/table/section/evidence_quality/table_awareness | 0.05-0.10 | 页面/表格/章节/质量/表格感知加分 |

**瓶颈**：权重线性叠加，无跨块聚合的语义评分；`score_block` 对"指标在相邻块、数值单独一块"的组合无法给高分。

## 3. 当前 Recall 结果（Phase 23.15）

| 指标 | 数值 |
|---|---|
| Candidate Recall@50 | **0.2667**（8/30） |
| Section Recall | **0.1667**（5/30） |
| Table Recall | **0.5333**（16/30） |
| Real E2E Accuracy | **0.5349** |

**结论**：正确 Evidence 未进入 candidate pool——召回不足（不是排序不足）。

## 4. 问题定位

1. **keyword LIKE 召回面窄**：`_candidate_blocks` 只按指标别名 LIKE 预筛（前 8 个 pattern），"营业收入"与"主营业务收入"、"revenue"与"Sales"等语义等价词无法互召回。
2. **无语义检索**：无 embedding / BM25 全文本检索，叙述类/语义等价表达（如"盈利能力"↔"净利润"）漏召回。
3. **无二级 reranker**：score_block 单层加权直接排序，无法综合"语义相似 + 表格相关 + 章节相关"做精细重排。
4. **Section/Table 加分量级不足**（+0.10）：未命中 case 的 gold block 根本不在候选池，加分无法弥补召回缺口。

## 5. 修复方向（Phase 23.16 Steps 2-3）

1. **Hybrid Retrieval 三路召回**（Step 2）：
   - BM25：`document_blocks.text` 词频检索（覆盖语义等价词的词形匹配）
   - Vector：embedding 语义检索（营业收入≈主营业务收入≈revenue）
   - Rule：保留现有 entity/metric/period/section 规则召回
   - 三路 **candidate union** 合并 → 目标 Recall@50 ≥ 0.8
2. **Evidence Reranker**（Step 3）：对 union 候选做二级排序，综合 entity / metric 语义相似 / period / table relevance / semantic similarity → top50。

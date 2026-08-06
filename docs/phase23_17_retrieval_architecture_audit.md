# Phase 23.17 Retrieval Architecture 审计

> 生成时间：2026-08-06 UTC
> 审计对象：Phase 23.16 Hybrid Retrieval 架构（为何 Recall@50 0.2667→0.20 回退）

---

## 1. 问题 1：Section routing 是否在检索前过滤？

**是（部分）**。`hybrid_retrieval.py`：

- `_target_page_ids()`（L51-61）：把 claim 路由的章节类型 → 章节页集合 → **page_id 集合**
- `bm25_candidates()`（L69-74）与 `vector_candidates()`（L98-103）：**都在目标章节页内检索**（`DocumentBlock.page_id.in_(pids)`）

```python
pids = _target_page_ids(session, doc_id, target_sections)   # ← 提前过滤
    .filter(DocumentBlock.document_id == doc_id, DocumentBlock.page_id.in_(pids))
```

**影响**：BM25/vector 两路只扫描目标章节页。若 gold evidence 所在页**不在路由章节页集合**（Phase 23.15 已测得 Section Recall 仅 0.1667——路由页与真实证据页映射错位），这两路直接漏召回。**这是 Recall 下降的主因**：Phase 23.14 的窗口扩展/Broad Page 是全局的，Phase 23.16 把 BM25/vector 关进章节页后，反而失去了全局召回能力。

## 2. 问题 2：候选池是否过窄？

**是**。三路召回上限：

| 路 | 上限 | 范围 |
|---|---|---|
| Rule | 400 | 全局（`_candidate_blocks`） |
| BM25 | 200 | **仅目标章节页** |
| Vector | 200 | **仅目标章节页** |

union 后经 `retrieve_for_claim` 评分，**最终 `scored[:top_k]` 截断（生产链 top_k=5）**。且 `max_blocks_per_doc=4000` 是软上限。

**问题**：两路语义召回被页限制 + 最终 top5 截断，候选池从"全局 50"萎缩为"章节页内 top5"，Recall@50 反而下降（0.2667→0.20）。

## 3. 问题 3：BM25/vector 搜索是否受页限制？

**是（直接）**——见问题 1 的 `page_id.in_(pids)` 过滤。且 `_target_page_ids` 依赖 `target_pages_for_claim`（章节索引），而章节索引的 page_start/page_end 与 grounding existing_page 的映射存在错位（Phase 23.15 结论：Section Recall=0.1667）。**语义检索被错误的页边界约束，等于两路召回被路由误差放大。**

## 4. 问题 4：Reranker 是否在掩盖候选缺失？

**是**。`reranker.py` 的排序权重：

```
entity 0.20 + metric 0.30 + period 0.15 + table 0.15 + semantic 0.20
```

- metric 权重最高（0.30）——对"指标别名未命中但语义等价"的候选惩罚过大。
- reranker 只在**已召回候选内**排序（`rerank_candidates(claim, scored, ...)`），**无法把未进入候选池的 gold block 拉回来**——它在"掩盖"候选缺失（排序看起来合理，但池子本身就缺正确证据）。
- 且 reranker 排序后仍被 `scored[:top_k=5]` 截断（service.py L463），二次丢失。

## 5. 架构缺陷总结

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| 1 | 语义检索被章节页提前过滤 | `hybrid_retrieval.py:_target_page_ids` + `page_id.in_(pids)` | BM25/vector 漏召回全局证据 |
| 2 | 最终 top_k=5 截断 | `service.py:463 scored[:top_k]` | 排序前先丢候选 |
| 3 | Reranker 权重 metric 主导 | `reranker.py:RERANK_WEIGHTS` | 语义等价候选排名被压制 |
| 4 | Reranker 只排序不召回 | `reranker.py:rerank_candidates` | 无法弥补缺失候选 |
| 5 | Vector 检索是 TF-IDF 字符 n-gram，非真 embedding | `hybrid_retrieval.py:vector_candidates` | 语义匹配能力弱 |

## 6. 修复方向（对应 Steps 2-5）

1. **移除提前过滤**（Step 2）：全局检索 → 章节/表格/实体加分，**不丢弃候选**。
2. **真语义检索**（Step 3）：embedding 余弦（claim/block embedding + 持久缓存），替代 TF-IDF。
3. **候选扩展**（Step 4）：BM25 top50 + Embedding top50 + Rule top50 **union ≥100，无提前截断**。
4. **Reranker 重构**（Step 5）：semantic 0.40 + entity 0.20 + metric 0.15 + period 0.15 + table 0.10；**只排序不删候选**。

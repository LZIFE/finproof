# Phase 23.26 Ranking 审计

> 生成时间：2026-08-06 UTC
> 审计对象：30 条 claim 的 gold evidence 在检索候选中的排名位置

---

## 1. Gold Candidate Rank 分布

数据来源：`retrieve_for_claim(top_k=50)`，gold 参照 = grounding `candidate_block_ids`。

| 区间 | 数量 | 比例 |
|---|---|---|
| Top10 | 4 | **13.3%** |
| Top50 | 9 | 30.0% |
| 未命中 Top50 | 21 | 70.0% |

有排名的 claim（rank 升序）：

| claim | rank | | claim | rank |
|---|---|---|---|---|
| CLM-014 | 1 | | CLM-002 | 17 |
| CLM-018 | 2 | | CLM-016 | 18 |
| CLM-003 | 3 | | CLM-001 | 20 |
| CLM-012 | 5 | | CLM-017 | 27 |
| | | | CLM-024 | 33 |

**目标：Top10 gold >= 50%（15/30）。当前 4/30，差 11 条。**

---

## 2. Top10 失败原因

### 2.1 未命中 Top50（21 条，主因）

| gold blocks | 出现 claim | 说明 |
|---|---|---|
| 131/113/132 | CLM-H01~H12（12 条） | holdout 五粮液年报——全部未进入 top50 |
| 38 | CLM-007/011/015（3 条） | demo 某页块——未命中 |
| 4443/4449/4440/4452/4455 | CLM-005/006（2 条） | page 135 利润表块——未命中 |
| 165/136/160 | CLM-009/010 | 未命中 |
| 9/2/6/3/11/8/7 | CLM-H10 | 未命中 |
| 104/110/109 | CLM-H12 | 未命中 |

**根因分层**：
1. **holdout（五粮液）全组失败**：12/21 未命中 claim 集中在 holdout——五粮液文档的 gold blocks（131/113/132）从未进入候选，说明**检索对 holdout 文档的召回系统性缺失**（可能与文档过滤、别名匹配、index 覆盖相关）。
2. **demo 中高 rank 失败**：CLM-001/002 的 gold block 189/190 排在 17-20 位——**召回成功但排序不足**。
3. **完全未召回**：CLM-005/006（利润表块）等——候选生成未覆盖。

### 2.2 错误 Top 候选类型（rank 1-10 常见错误块）

| 错误类型 | 代表 block | 出现频率 |
|---|---|---|
| **附注引用块**（"参见财务报表附注二（26）（a）收入之销售商品会计政策、附注四（48）…"） | 4329 | 高频（CLM-001/002/007 等 top1） |
| 财务表头/数值混合块 | 5386（"2023年 2024年 12月31日 本年增加"） | 中 |
| 毛利率叙述块 | 1448（"毛利率比上年同…"） | 中 |
| 或有事项叙述块 | 14363（"公司不存在需要披露的重要或有事项"） | 低 |

**关键错误模式**：附注引用块（4329）因含"收入/附注/会计政策"等关键词 + 高 text_similarity 排到 top1，但它只是**指引性文本**（引用其他附注位置），不含实际数值——是典型的"指标关键词命中但无数值事实"块。

### 2.3 Top10 候选组成（方法/事实分布）

| 维度 | 分布 |
|---|---|
| retrieval_method | default 138 / evidence_window 85 / evidence_index 77 |
| financial_fact | with_fact 174 / no_fact 126 |

Top10 中 58% 候选带 financial_fact、42% 不带——**fact 标记未主导排序**（当前 reranker 权重 fact 0.45，但附注引用块等 text 高分块仍抢占头部）。

---

## 3. 修复方向（对应 Step 2）

排序优先级调整为（Financial Evidence 优先）：

```
A. financial_fact 存在（优先带结构化事实的块）
B. metric_match（fact metric 家族）
C. value_match（fact 数值匹配 claim）
D. period_match
E. growth_match
F. table_type（income_statement/balance_sheet/cash_flow）
G. semantic similarity（辅助，不再主导）
```

目标：压住"附注引用块/叙述块"（无 fact 或 fact 不完整）的排名，让正确财务表行（带 fact）进入 Top10。

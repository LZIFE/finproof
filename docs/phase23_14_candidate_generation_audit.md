# Phase 23.14 Candidate Generation 审计

> 生成时间：2026-08-06 UTC
> 审计对象：`backend/app/services/evidence_retrieval/`（候选生成链路）

---

## 1. 哪些条件导致 Block 进入候选？

### 1.1 `_candidate_blocks`（service.py:102-123）——候选池构建

| 条件 | 说明 |
|---|---|
| 文档角色 | `Document.document_role == "SOURCE_DOCUMENT"`（filter_documents 层） |
| 公司匹配 | `company_name == entity` 精确 → 别名反查（全称/简称/代码/英文名）→ 前 2 字前缀放宽（Phase 23.13） |
| 别名预筛 | 指标别名 `LIKE %alias%`，**最多取前 8 个别名 pattern**（按长度降序排序后截断） |
| fallback | 无中文别名（quarterly/scope 类）→ 全量扫描所有块 |

### 1.2 `retrieve_for_claim`（service.py:142+）——候选过滤/评分

| 条件 | 说明 |
|---|---|
| 空文本 | `if not block.text: continue`（跳过真空单元格） |
| 噪声块 | `is_noise_block` → `final_score=0`（页码/分隔符/纯标点） |
| 最低分 | `final_score < MIN_CANDIDATE_SCORE(0.05)` 过滤；fallback 模式下含数字块保底进候选 |
| Broad Page | 候选不足时全量补扫含数字块（Phase 23.13，不提前丢弃） |
| TopK | `scored[:top_k]`（生产链 top_k=5） |

**结论**：候选进入条件 = 公司匹配文档 + 别名 LIKE 命中（或 fallback 全量）+ 非空文本 + 非噪声 + 达到最低分。

---

## 2. 哪些 Evidence 因为关键词缺失被过滤？

| 过滤点 | 被过滤的 Evidence 类型 |
|---|---|
| **别名 LIKE 前 8 截断**（`_candidate_blocks:110`） | metric 别名集合 > 8 时，长尾别名（如"归属于上市公司股东的扣除非经常性损益的净利润"）不参与 LIKE，其所在块漏候选 |
| **LIKE 精确子串**（`text.like(%a%)`） | 别名与块内文本写法不一致（如"营收"vs"营业收入"、"YoY"vs"同比增长"）时 LIKE 不命中（LIKE 不支持分词/词形归一） |
| **无中文别名 fallback**（`retrieve_for_claim:161`） | quarterly_revenue/scope 类 claim：fallback 全量扫含数字块，但**不含数字的叙述块**（NARRATIVE_FACT 证据）被跳过 |
| **噪声块归零**（`is_noise_block`） | 含页码/分隔符的块——但真证据不含这些，影响有限 |
| **最低分过滤**（`MIN_CANDIDATE_SCORE=0.05`） | 指标/期间/数值均未命中的块（如指标在相邻块、数值单独一块）——**单块评分无法跨块聚合是主因** |

**关键发现**：当前是**单块独立评分**——指标行、数值行、表头、单位被拆成多个 block 时，每个 block 单独评分可能都低于门槛，但**组合成 Evidence Window 后能完整表达事实**。这是 Recall@10=0.23 的根因之一。

---

## 3. 哪些 Claim 类型容易失败？

| Claim 类型 | route | 失败模式 |
|---|---|---|
| 叙述事实 | NARRATIVE_FACT | 无数字语义 → fallback 全量扫含数字块，但证据本身是叙述块（不含数字）→ 漏召回 |
| 范围验证 | SCOPE_VALIDATION | 指标/期间命中难，单块评分低 |
| 期间比较 | PERIOD_COMPARISON | 需要上一期数值（previous_value），单块只含本期 → 聚合缺失 |
| 结构化数值 | STRUCTURED_NUMERIC | 表格拆块：指标行与数值行分离 → 单块评分不足 |
| 表格指标 | TABLE_METRIC | 表头/单位/数值分散在不同块 → 需要窗口聚合 |

**结论**：容易失败的是"事实分散在多块"（表头+单位+指标行+数值行）和"无数字叙述"两类——单块评分模型天然不匹配。

---

## 4. 修复方向（对应 Phase 23.14 Steps 2-4）

1. **Claim-aware**（Step 2）：把 claim 解析为 `{metric[], period[], need[value/previous/growth]}`，用结构化条件替代裸 LIKE。
2. **Evidence Window**（Step 3）：命中块后扩展同页 ±3 块 / 同表 y-range，形成窗口聚合评分，解决"指标与数值分离"。
3. **Table-aware**（Step 4）：检测表头/单位/年份/指标行，优先含数字/年份/单位块，降低空 cell/页码/分隔符。

---

## 5. 结论

- 候选生成位于 `_candidate_blocks` + `retrieve_for_claim`。
- 过滤主因：**单块独立评分**（跨块事实无法聚合）+ **LIKE 词形不归一** + **无中文别名 fallback 只扫数字块**。
- 需重构为 Evidence Window 聚合候选，而非纯单 block LIKE 候选。

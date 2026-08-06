# Phase 23.25 Verification Bridge 审计

> 生成时间：2026-08-06 UTC
> 审计对象：Verification → Decision → Verdict 全链路（financial_fact 为何未影响最终判定）

---

## 1. 链路回答

### Q1: financial_fact 从哪里生成？

`backend/app/services/evidence_retrieval/fact_retrieval.py:attach_financial_facts`

- 从候选的 `financial_object`（Evidence Window Reconstruction 产物，含 metric/current/previous/growth/unit/period/table_type/source_blocks）提取标准化 `financial_fact` schema
- 在 `retrieve_for_claim` 中调用（fact_retrieve_candidates → merge_evidence_index_candidates → attach_financial_facts）

### Q2: 进入哪个对象？

**evidence_candidates 每个元素的 `financial_fact` 字段**（EvidenceBundle 元素）。

`verify_evidence_set`（verification_service.py:255）入口处由 `attach_fact_verifications`（fact_verification_path.py）进一步附加 `fact_verification` 诊断字段（metric/value/prev/growth/period 匹配结果）。

### Q3: 哪个函数负责最终 verdict？

**`core_verify`**（core_pipeline.py:326）——唯一最终判定函数，被 CORE_ORACLE / NOISY_ORACLE / REAL_E2E 共用。

### Q4: 当前 verdict 使用哪些字段？

core_verify 的 evidence 消费（核心发现）：

```python
# core_pipeline.py:63
texts = [e.get("text", "") or "" for e in evidence_list]
```

**verdict 只消费 evidence 的 `text`（raw block 文本）**。其余字段（evidence_id、doc_period）仅用于 trace/上下文。claim 侧消费 metric/value/unit/period（claim 字段），对 evidence 文本做 extract_financial_values 解析。

### Q5: 为什么 financial_fact_verification 没有影响结果？

| 环节 | 状态 |
|---|---|
| financial_fact 生成 | ✅ 已进入 evidence 元素 |
| fact_verification 诊断 | ✅ 已附加（attach_fact_verifications） |
| core_verify 消费 financial_fact | ❌ **完全不读**（只读 `e.get("text")`） |
| verdict 决策融合 fact | ❌ 无任何融合逻辑 |

**根因**：financial_fact 是"附加的装饰性字段"，verdict 决策路径（core_verify）从头到尾只处理 raw block text。fact_verification 诊断被丢弃——`financial_fact verification_result` 从不进入 SUPPORTED/REFUTED/INSUFFICIENT 判定。

---

## 2. 链路图

### Current（现状——fact 未进入 verdict）

```
Claim
 ↓
Retrieval (retrieve_for_claim)
 ↓
EvidenceBundle (evidence_candidates)
 ↓
financial_fact (attach_financial_facts 附加，装饰性)
 ↓
fact_verification (attach_fact_verifications 附加，诊断性)
 ↓
core_verify —— 只读 e["text"]（raw block），忽略 financial_fact
 ↓
Verdict (SUPPORTED/REFUTED/...)
```

### Fixed（目标——fact 进入 decision adapter）

```
Claim
 ↓
Retrieval
 ↓
EvidenceBundle
 ↓
financial_fact
 ↓
fact_verification (结构化验证：metric/value/growth/period)
 ↓
Decision Adapter（新：fact + raw text 融合判定）
   ├─ fact 完整且匹配 → SUPPORTED
   ├─ fact 完整且 value 冲突 → REFUTED
   └─ fact 不完整 → fallback raw text verification（旧逻辑）
 ↓
Verdict
```

---

## 3. 修复方向

1. **Decision Adapter**（core_pipeline.py 或 verification_service.py 新函数）：在 core_verify 的 verdict 决策处，若 evidence 含已验证 financial_fact，优先用结构化事实验证结果；否则走旧 raw text 路径。
2. **融合规则**（Step 3）：fact metric+value+period 全匹配 → SUPPORTED；metric 匹配但 value 冲突 → REFUTED；fact 不完整 → fallback。
3. **不绕过 Gate**：financial_fact 只在 Gate 通过后的证据上做 verdict 增强，Gate 决策规则不变。
4. **兼容性**：block-only evidence（无 financial_fact）完全走旧流程。

---

## 4. 结论

financial_fact 已生成并进入 EvidenceBundle，但 **verdict 决策链路（core_verify）只读 raw text，未消费 financial_fact**——这是"Fact verification success rate=0.0279 但 Accuracy 不变 0.5349"的直接原因。修复落点：core_verify 的 verdict 决策处增加 Financial Fact Decision Bridge（Step 2-3）。

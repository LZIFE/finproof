# Phase 23.34 Fact Trace Report（全链路字段追踪）

> 生成时间：2026-08-06 UTC
> 追踪对象：financial_fact 字段从 Retrieval 到 core_verify 的传递
> 样例 claim：CLM-001（top_k=10）

---

## 1. 各阶段 financial_fact 存在性

| 阶段 | N | 带 financial_fact | 比例 |
|---|---|---|---|
| 1. Retrieval output（retrieve_for_claim） | 10 | **10** | 100% |
| 2. fetch_evidence（Gate input 构造） | 10 | **10** | 100% |
| 3. Gate output（evaluate_all accepted） | 9 | **0** | **0%** |
| 4. Selector output（evidence_bundle → core_verify input） | 3 | 0 | 0% |

## 2. 首失点定位

**financial_fact: true → false 的首次丢失发生在 Step 3：Evidence Gate（`evidence_gate.evaluate_all`）。**

- Retrieval（retrieve_for_claim）→ 候选带 financial_fact ✅
- fetch_evidence → 构造的 evidence 元素带 financial_fact ✅（verification_service.py L115）
- **Gate（evaluate_all）→ 接受后 0/9 带 fact ❌ ← 首失点**
- Selector（evidence_selector.select）→ 0/3（延续丢失）

## 3. 丢失机制

### Gate（evidence_gate.py）

`evaluate_all` 对每个 candidate 构造 `GateResult`（evidence_id / text / 各维度 score / final_quality_score / accepted），**未把 candidate 的 financial_fact 字段复制到 GateResult**。证据文本 `text = str(candidate.get("text") or "")`（evidence_gate.py L52 等），但 financial_fact 未透传。

### Selector（evidence_selector.py）

`select` 的 evidence_bundle 构造（L162-166）：
```python
evidence_bundle.append({
    "evidence_id": r.evidence_id,
    "text": r.text or "",
    "final_quality_score": r.final_quality_score,
})
```
**只保留 evidence_id / text / final_quality_score——financial_fact 未透传**。即使 Gate 透传，Selector 也会丢弃。

## 4. 修复目标（Task 3）

要求 financial_fact 从 retrieval **100% 到达 core_verify**：
1. Gate（evidence_gate.py）：`GateResult` 增加 financial_fact 字段，evaluate_all 构造时透传 `candidate.get("financial_fact")`。
2. Selector（evidence_selector.py）：evidence_bundle 构造增加 `"financial_fact": r.financial_fact`。
3. 不修改 retrieval / gold / expected_verdict / evaluation；只做 Evidence schema 透传。

## 5. 数据

`data/gold_review/phase23_11_6_2/`（追踪结果含于本次 debug；核心结论如上表）

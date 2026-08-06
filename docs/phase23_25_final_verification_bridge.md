# Phase 23.25 Final Verification Bridge 报告

> 生成时间：2026-08-06 UTC
> 目标：让 Financial Fact Intelligence 真正进入最终 verdict 判定

---

## 1. 根因分析

### 审计结论（docs/phase23_25_verification_bridge_audit.md）

financial_fact 已生成并进入 EvidenceBundle，但 **verdict 决策链路（core_verify）只读 evidence 的 `text`（raw block），完全不消费 financial_fact / fact_verification**：

```
Current: Claim → Retrieval → EvidenceBundle → financial_fact(装饰) → fact_verification(诊断) → core_verify(只读 text) → Verdict(忽略 fact)
Fixed:   Claim → Retrieval → EvidenceBundle → financial_fact → fact_verification → Decision Adapter → Verdict(融合 fact)
```

### Step 6 自动诊断（Accuracy 0.5349 < 0.65 触发）

| 诊断项 | 结果 |
|---|---|
| A. financial_fact 覆盖 | ✅ 30/30 claims 带 fact，top10 中 300+ fact evidence——覆盖充足 |
| B. 正确 evidence 进 Top10 | ❌ 仅 4/30（13.3%）——正确证据未进候选是端到端瓶颈 |
| C. verifier 权重 | ❌ gold 进 top10 的 4 条 fact 验证全失败——**financial_fact 与块错配** |
| D. claim parser | ✅ metric 43/43、period 42/43、value/unit 35/43——抽取基本完整 |

**C 的字段级根因**：`merge_evidence_index_candidates` 把跨块索引证据对象附加到其 source_blocks 的每个块上，导致 block 190/192/193 被附加 page 135 营业收入对象（自身内容是归母净利润/每股收益/经营现金流）——fact_verification 因 metric 错配全失败。

---

## 2. 修改文件

| 文件 | 修改 |
|---|---|
| `docs/phase23_25_verification_bridge_audit.md` | 新增：链路审计（Q1-Q5 + 现状/目标链路图） |
| `backend/app/services/verification/financial_fact_decision_bridge.py` | 新增：fact_decision_signal（SUPPORTED/REFUTED/fallback 信号） |
| `backend/app/services/verification/core_pipeline.py` | Decision Bridge 接入：core_verify 分派入口融合 fact（2.5 节），fact 明确优先、REFUTED 冲突优先、否则 fallback 旧分派 |
| `backend/app/services/evidence_retrieval/fact_retrieval.py` | 轻量修复：attach_financial_facts 增加块自身 metric 与 fact metric 家族校验，防跨块错配 |

## 3. 修改逻辑

### Decision Bridge 融合规则（Step 3）

```
fact_verification 聚合（fact_decision_signal）：
├─ metric+value+period 全匹配 → verdict_hint=SUPPORTED
├─ metric 匹配但 value 冲突   → verdict_hint=REFUTED
└─ fact 不完整 / 无 fact      → verdict_hint=None（fallback raw text 验证）

core_verify 融合（2.5 节）：
├─ hint=SUPPORTED 且无 value 冲突 → SUPPORTED（conf 0.75）
├─ hint=SUPPORTED 但 raw text 有 value 冲突 → REFUTED（冲突优先）
├─ hint=REFUTED → REFUTED（conf 0.8）
└─ hint=None → 走原分派（raw text 旧流程）
```

### 轻量修复（Step 6 C）

`attach_financial_facts` 现在校验块自身 metric 与 fact metric 同族才附加 financial_fact；错配块（如 block 190 被附加营业收入对象）→ financial_fact=None，走 raw text 验证。

---

## 4. Before / After 指标

| 指标 | Before (23.24) | After (23.25) | Δ |
|---|---|---|---|
| Real E2E Accuracy | 0.5349 | **0.5349** | 0 |
| Real E2E Macro-F1 | 0.5775 | **0.5775** | 0 |
| Real E2E Coverage | 0.6512 | **0.6512** | 0 |
| Fact verification success rate | 0.0279（12/430） | **0.0511**（12/235） | +0.023（修复后 fact 数减少但成功率提升） |
| CORE Oracle | 1.0 | **1.0** | 0（保持） |

**如实记录**：Decision Bridge 已接入并验证生效（fact 信号进入 verdict 判定、block-only 兼容、CORE Oracle 保持 1.0），Fact success rate 因 metric 错配修复从 0.0279 提升至 0.0511（分母 430→235 反映错配 fact 被正确剔除）。但 Real E2E Accuracy 0.5349 **未变**——根因是正确 evidence 仅 13.3% 进入 Top10（诊断 B），fact bridge 可影响的 case 极少。

---

## 5. 是否 Competition-Usable

### **NO**

Accuracy 0.5349 < 0.70 目标；Fact success rate 0.0511 过低。

## 6. 剩余瓶颈

1. **正确 evidence 未进 Top-K（主瓶颈）**：仅 4/30（13.3%）gold block 进入 top10——即使 fact bridge 完全生效，也仅能影响 4 条 case。需 Retrieval 召回/排序改进（Phase 23.12-23.22 已多轮尝试，未突破）。
2. **fact 验证通过率低（0.0511）**：窗口重建的 fact 对象 periods/growth 与 claim 精确对齐不足；12/235 通过核心字段验证。
3. **fact 数据质量**：跨块索引对象与块级内容错配虽已修复，但重建对象的 period 提取（如"20年"类噪音）仍有残余。

---

## 7. 声明

- 未修改 Gold labels / expected_verdict / 测试数据 / Retrieval 结果（用于提指标）/ Oracle evaluation；未绕过 Gate。
- 全部修改属允许范围：verification_service / core_verify / verdict adapter / fact verification logic。
- CORE Oracle acc=1.0（43/43）保持；903 pytest 通过；36 个 block-only 验证测试通过。

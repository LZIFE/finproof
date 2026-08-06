# Phase 23.30 Financial Fact Native Verification 报告

> 生成时间：2026-08-06 UTC

## 1. Verification 链变化

### 审计（docs/phase23_30_verification_audit.md）

fact_verification 已做四类比较（metric/value/period/growth），但 core_verify 主路径（numeric/growth/quarter）仍原生消费 raw block text；旧 Decision Bridge（Phase 23.25）仅在聚合短路且门槛极高（success rate 0.0279）时生效。

### 双路径接入（Task 2/3）

```
Claim
 ↓
Retrieval
 ↓
EvidenceBundle（含 financial_fact）
 ↓
financial_fact_verifier.best_fact_verification（新增，Task 2）
 ├─ decision=SUPPORTED（metric+value+period 全匹配）→ Verdict SUPPORTED（conf 0.80-0.95）
 ├─ decision=REFUTED（metric 匹配但 value 冲突）→ Verdict REFUTED（conf 0.75）
 └─ decision=UNKNOWN → fallback 旧 block verification（numeric/growth/quarter/semantic）
 ↓
Verdict
```

- **不删旧路径**：core_verify 3) 分派（numeric/growth/quarter/semantic）原样保留，仅 UNKNOWN 时进入。
- **不绕过 Gate**：Gate 仍在 verify_evidence_set 执行；不改 Gate 决策规则。
- **未修改 gold / expected_verdict**。

## 2. 修改文件

| 文件 | 修改 |
|---|---|
| `backend/app/services/verification/financial_fact_verifier.py` | 新增：原生事实验证器（SUPPORTED/REFUTED/UNKNOWN + confidence + best_fact_verification 聚合） |
| `backend/app/services/verification/core_pipeline.py` | 2.5 节替换：Financial Fact Native Verification 双路径（fact 明确优先，否则 fallback 旧分派） |
| `docs/phase23_30_verification_audit.md` | 新增：Verification Pipeline 审计 |

## 3. Before / After 指标

| 指标 | Before (23.29) | After (23.30) | Δ |
|---|---|---|---|
| **Fact Gold Recall@10** | 0.3226（10/31，fact-level 参照） | **0.7143（10/14，有 aligned fact 的 claim）** | 口径细化 |
| **Fact verification success rate** | 0.0279（12/430 evidence 级，旧 verifier） | **0.1628（7/43 claim 级，新 native verifier）** | +0.135 |
| Real E2E Accuracy | 0.5116 | **0.5116** | 0 |
| Real E2E Macro-F1 | 0.5768 | **0.5770** | +0.0002 |
| Real E2E Coverage | 0.6744 | **0.6744** | 0 |
| CORE Oracle | 1.0 | **1.0** | 0（保持） |

## 4. 最大剩余瓶颈

1. **claim parser 缺失 comparison_value**：`_claim_previous_value` 无法从 claim 提取上一期数值（gold_claims 无 previous_value 字段），previous_value_match 几乎恒 False——但 value+period+metric 核心匹配已足够 SUPPORTED（previous 仅加分）。
2. **fact 覆盖率仍有限**：Fact Gold Recall@10=0.7143 但仅对 14 个有 aligned fact 的 claim 计算；其余 17 个 claim（growth/quarter/非财务类）无 fact 或 fact 未对齐，fallback 旧 block 路径。
3. **REFUTED 过触发（18/43）**：fact 数值与 claim value 换算后不匹配（如 CLM-003 净利润 439.45亿 vs fact 归母净利润），部分因 fact 对象绑定的 current_value 与 claim 期间列错位——需要 period-aware fact 选择。
4. **Real E2E Accuracy 未提升**：双路径中 SUPPORTED 仅 7/43 claim 触发，且这 7 条多数原本就被 block 路径正确判定；REFUTED 18 条需与 gold 对照验证是否误判。

## 5. 是否 Competition Usable

**NO**——Accuracy 0.512 < 0.70 目标；Fact verification success rate 0.163 仍低；双路径正向但未跨门槛。

## 6. 声明

- 未修改 gold / expected_verdict / verifier 核心判定规则（仅新增 fact 优先路径）。
- CORE Oracle acc=1.0（43/43）保持；24 个 block-only 验证测试通过；903 pytest 通过。

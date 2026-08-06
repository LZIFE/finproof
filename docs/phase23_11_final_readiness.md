# Phase 23.11 Final Competition Readiness Report

> 生成时间：2026-08-06 UTC
> 管线：Phase 23.11.8-B → 23.11.10 Full Evaluation Pipeline
> Gold 版本：23.11.8-B-v3（`data/annotations/gold_evidence_v3.json`）

---

## 1. 数据状态

| 指标 | 数值 |
|---|---|
| Gold 总数（demo 29 + holdout 13） | **42** |
| 已导入（人工确认 + 无冲突 + MATCH） | **2**（EVD-001, EVD-003） |
| Blocked（claim_gold_conflicts 待第二轮裁定） | **3**（EVD-002, EVD-004, EVD-H04） |
| Rejected（NONE_FOUND） | **1**（EVD-010） |
| 未审核 | 36 |

- 旧版 Gold（demo/holdout annotations）**未修改**（before hash 保留）。
- 新版本 `gold_evidence_v3.json` 仅对 EVD-001/EVD-003 追加 `confirmed_block_ids` / `gold_confirm_status=CONFIRMED`，未改动 evidence_text / verdict。
- **Gold 闭环完成度：2/42（4.8%）—— 远未达到可支撑正式评测的完整度。**

## 2. Oracle 结果

| 指标 | CORE_ORACLE | 目标 | 达标 |
|---|---|---|---|
| Accuracy | **1.0**（43/43） | ≥ 0.85 | ✅ |
| Macro-F1 | **1.0** | ≥ 0.80 | ✅ |
| per-class F1（6 类） | 全部 1.0 | — | ✅ |
| 原 17 错误修复 | 17/17 | ≥ 14 | ✅ |
| 新回归 | 0 | ≤ 2 | ✅ |
| Confusion Matrix | 对角全满（0 错误） | — | ✅ |

**NOISY_ORACLE**：sample_count=24（grounded cohort），但 **Gate 指标仍 INVALID_PENDING_GOLD_ALIGNMENT**（候选 block_id 为空）—— 未计算，未达标。

## 3. Real E2E 结果

默认策略 `phase23_11_gate`（Retrieval → Gate → Selector(Top3) → core_verify，43 条 Development Claims）：

| 指标 | 实际 | 目标 | 达标 |
|---|---|---|---|
| Accuracy | **0.5116** | ≥ 0.70 | ❌ |
| Macro-F1 | **0.5037** | ≥ 0.60 | ❌ |
| Coverage | **0.6744** | ≥ 0.65 | ✅ |
| Abstention Rate | 14/43 = **0.3256** | — | — |
| Retrieval Failures | 1/43 | — | ✅ |
| Verification Failures | 21/43 | ≤ 3 | ❌ |
| Evidence Hit@K | 依赖 Retrieval 详情（Top50→Top5 链路） | — | 部分 |

Top1 / Top3 策略：acc=0.488 / 0.512 —— 与 Gate 策略基本一致，说明瓶颈不在 Gate。

## 4. 当前评级

### **PARTIAL**

理由（禁止夸大，逐项说明）：

1. **CORE_ORACLE 全达标**（acc=1.0, mf1=1.0）—— Gold Block 直喂 core_verify 时验证正确率高，说明核心验证器本身可靠。
2. **Real E2E 核心指标未达标**：Accuracy 0.51（目标 0.70）、Macro-F1 0.50（目标 0.60）、Verification Failures 21（目标 ≤3）。正式评测门槛未过。
3. **Gold 数据状态远未完成**：42 条中仅 2 条（4.8%）确认导入，3 条 blocked 待第二轮人工裁定，36 条未审核。`gold_evidence_v3.json` 中 40/42 条没有 confirmed_block_ids。
4. **NOISY_ORACLE Gate 指标未计算**（INVALID_PENDING_GOLD_ALIGNMENT）—— 因 Gold Alignment 未完成，Gate 的 Precision/Recall 无法评估。
5. **瓶颈定位**：Retrieval → Selector 环节（Top1/Top3/Gate 三种策略 acc≈0.49-0.51 无显著差异），非核心验证器。

### Competition-Usable：**NO**

---

## 附：不可变更声明

- 本报告评级基于当前实测数据，**未修改任何评测代码、Gold 数据或 Verifier/Gate/Selector/Retrieval**。
- 所有评测产物为新增 artifact：`oracle_final_report.json`、`real_e2e_final_report.json`、`gold_import_report.md`、`gold_import_final_preview.json`、`verdict_adjudication.json`。
- 若要提升评级至 PASS：需（a）完成 Gold 人工审核闭环（至少确认可用子集），（b）修复 Retrieval/Selector 的候选质量问题使 Real E2E acc ≥ 0.70，且（c）重算 NOISY_ORACLE Gate 指标。

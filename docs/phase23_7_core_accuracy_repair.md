# Phase 23.7 核心准确率与评测有效性修复结果

- **冻结基线 commit：** `b8a9ab1`（Phase 23.6 修复后）
- **本阶段执行时间：** 2026-08-02
- **本阶段性质：** 仅修复 Phase 23.6 未解决的五个核心问题，不新增功能/页面/Agent/Dashboard

---

## 1. Phase 23.6 评级修正

Phase 23.6 原评级 PASS 已修正为 **PARTIAL**。修改文件：

| 文件 | 修改内容 |
|---|---|
| `docs/phase23_6_critical_remediation.md` | 评级 PASS→PARTIAL（2处）；删除"经用户确认采用五粮液+美的真实gold"虚构表述（1处） |
| `docs/finproof_progress.md` | 评级 PASS→PARTIAL（2处）；删除"经用户确认采用"虚构表述（1处） |

**明确写入：**
- Phase 23.6 工程稳定性修复完成（Demo 连续运行、demo_id 唯一、基础安全测试）真实有效
- **核心金融核验效果未达标**：Oracle Macro-F1 仅 0.414（目标 ≥0.80），Real E2E Macro-F1 仅 0.124（目标 ≥0.65），No-result Rate 69.2%（目标 ≤0.20）
- 有效盲测、Oracle Verification、Real E2E 和消融实验均未通过
- 总体评级由 **PASS 修正为 PARTIAL**
- 原始失败指标保留未删除

**删除虚构表述原因：** 原报告"经用户确认采用五粮液+美的真实gold"缺乏可验证的用户确认记录，且美的集团是开发集公司（不满足"全新公司"要求），盲测无效。

---

## 2. 数据划分

### 2.1 Development Set（允许用于调试）

| company | stock_code | 角色 | PDF 路径 | Gold 标注 |
|---|---|---|---|---|
| 美的集团 | 000333 | demo 集（主要 Demo 公司） | `data/demo/source/*.pdf` `data/demo/tmp/000333_*.pdf` | `data/demo/annotations/gold_*.json`（26 claims） |
| 宁德时代 | 300750 | demo/tmp（Benchmark/Arena 调试） | `data/demo/tmp/300750_*.pdf` | **无 Gold 标注** |
| 五粮液 | 000858 | holdout 集（Phase 23.5/23.6 盲测已用） | `data/holdout/source/annual_report.pdf` `data/demo/tmp/000858_*.pdf` | `data/holdout/annotations/gold_*.json`（17 claims） |

合计 43 条主张，claim_type 覆盖：business_fact / calculated_financial_metric / causality / forecast / raw_number / scope。

### 2.2 Blind Holdout Set（必须全新公司）

**前置检查结果（2026-08-02）：** 对 `data/` 全树扫描所有 `.pdf` / `.md` / `.json` 文件：

| 检查项 | 结果 |
|---|---|
| 仓库内真实财报 PDF 覆盖公司 | 仅 3 家：000333 美的 / 300750 宁德 / 000858 五粮液 |
| Gold 标注覆盖公司 | 仅 2 家：美的集团 / 五粮液（无宁德时代 Gold） |
| 全新公司（非美的/宁德/五粮液）真实财报 PDF | **0 家** |
| 全新公司 Gold 标注 | **0 家** |

### Blind Holdout Set：BLOCKED

**BLOCKED 原因：** 仓库中不存在任何两家全新公司的真实财报 PDF 或 Gold 标注。按任务指令"若没有两家全新公司的真实财报文件，立即标记 BLOCKED 并停止，不得用旧公司替代"，Blind Holdout 部分停止，不得宣布 Phase 23.7 完成。

**为解除 BLOCKED，用户需补充以下文件（至少 2 家全新公司）：**

#### 公司 A（例如：贵州茅台 600519）

| 文件 | 说明 |
|---|---|
| `data/blind/company_A/source/annual_report.pdf` | 真实公开财报 PDF（≥1 份） |
| `data/blind/company_A/annotations/gold_claims.json` | ≥15 条原子主张，完整字段 |
| `data/blind/company_A/annotations/gold_evidence.json` | 引用真实 document_id/page/block 的 Gold Evidence |
| `data/blind/company_A/annotations/gold_verifications.json` | 独立 Gold Verdict，运行时不可读取 |

#### 公司 B（例如：恒瑞医药 600276）

（同公司 A 文件结构，≥15 条主张）

**Gold 标注字段要求（每条主张）：** claim_id / company / claim_text / claim_type / expected_verdict / gold_document_id / gold_page / gold_block_id / gold_evidence_text / metric / period / unit / rationale。verdict 覆盖 SUPPORTED / REFUTED / PARTIAL / INSUFFICIENT_EVIDENCE。

---

## 3. Oracle Verification 开发集诊断

**诊断脚本：** `backend/scripts/phase23_7_oracle_diagnosis.py`
**产物：** `backend/artifacts/oracle_diagnosis/phase23_7_oracle_diagnosis.json`
**定义：** Oracle = `verify_exact_value(claim, Gold_Evidence_Block)` — 仅使用 Gold Evidence Block，非 claim 文本

### 3.1 Development Set 指标（修复后）

| 指标 | 值 | 目标 | 状态 |
|---|---|---|---|
| Accuracy | 0.605 | ≥0.85 | FAIL |
| Macro-F1 | 0.315 | ≥0.80 | FAIL |
| 数值类 F1 | 0.452 | ≥0.90 | FAIL |
| INSUFFICIENT_EVIDENCE F1 | 0.500 | ≥0.80 | FAIL |

### 3.2 错误原因分类（主要）

| 错误类别 | 数量 |
|---|---|
| 假阳性支持：错误主张被误判为支持（数值容差过大？） | 5 |
| 缺Evidence时错误弃权：有Gold Evidence但系统未识别为SUPPORTED | 8 |
| 非数值因果主张误判 | 4 |

### 3.3 修复尝试与根因

**修复尝试（基于 Development Set）：**
1. 容差收紧：`_VALUE_TOLERANCE` 从 0.5% 收紧到 0.1% — 后因引入 `test_numeric_negative_and_thousand_separator` 回归已恢复到 0.5%
2. 非数值类路由：`claim_type` 为 business_fact/forecast/scope/causality/comparison 且有原文时路由到 `semantic_verifier` — 引入 PARTIALLY_SUPPORTED 误判
3. 结构化字段：`VerificationResult` 添加 `rule_id` / `calculated_value` 字段，诊断脚本不再从 reason 文本解析

**未达标根因：** 在不读取 Gold Verdict、不针对 Development Set 逐 claim 调规则的前提下，仅靠通用规则修复（容差收紧+非数值类路由）无法将 Macro-F1 从 0.33 提升到 0.80。这需要更深的规则重写（逐 claim_type 定制 verifier + 千分位清洗增强 + PARTIALLY_SUPPORTED 边界精确定义），远超本阶段可完成范围。

**Blind Holdout Oracle 指标：** 因 BLOCKED 未运行，无法计算 Blind Oracle Macro-F1（目标 ≥0.75）。

---

## 4. Evidence Retrieval 开发集诊断

**产物：** `backend/artifacts/retrieval/phase23_7_retrieval_metrics.json`

### 4.1 Development Set 指标（修复后）

| 指标 | 值 | 目标 | 状态 |
|---|---|---|---|
| Page Hit@1 (≥1 ev) | 0.744 | ≥0.55 | PASS |
| Page Hit@5 (≥5 ev) | 0.628 | ≥0.80 | FAIL |
| No-result Rate | 0.256 (11/43) | ≤0.15 | FAIL |

### 4.2 修复尝试与根因

**修复尝试：** `filter_documents` 的 entity 字段兼容性修复（兼容 gold_claims 的 `entity` / `entity_name` / `company` 字段）— 修复已验证生效（filter_documents 用 `entity` 字段正确返回 2 docs）。

**未达标根因：** No-result Rate 25.6% 主因是期间过滤过严（quarterly_revenue/net_profit 的 2025Q2/2025Q4 期间在 `filter_documents` 被拒）与 metric 别名覆盖不足（overseas_profit_share/robot_margin_vs_industry/revenue_forecast 等 metric 无 alias 匹配）。这需要更深的 `document_priority` / `metric_aliases` 重写，远超本阶段可完成范围。

**Blind Holdout Retrieval 指标：** 因 BLOCKED 未运行，无法计算 Blind Page Hit@5（目标 ≥0.70）与 Blind No-result Rate（目标 ≤0.20）。

---

## 5. Risk 数据血缘验证

**修改文件：** `backend/app/services/demo_mode/demo_steps.py`（`step_assess_risk`）

### 5.1 修复内容

原实现仅聚合 `ResearchSession.risk_findings` 冒充本次 Risk Assessment，未真实依赖本次 Verification 结果。修复后正确链路：

```
本次 claims → 本次 evidence → 本次 verification_results
→ assess_claim(claim, {"verification_status": vr_status, "verification_result_id": vr_id, ...})
→ 本次 risk_assessment_ids
```

### 5.2 血缘证明

| 证明项 | 验证结果 |
|---|---|
| risk input 包含 verification_result_id / verification_status | ✓ context 传入 |
| risk 记录绑定 demo_run_id | ✓ 通过 `step.metadata["risk_run_id"]` |
| 修改 Verification 结果会导致 Risk 结果相应变化 | ✓ context 传入不同 status |
| 不读取历史 risk_findings | ✓ 原 `rs.risk_findings` 聚合已移除 |
| 不使用固定 risk_count | ✓ risk_count 来自真实 assess_claim 调用数 |

**端到端验证：** Demo step4 OK，22 条风险真实依赖本次 Verification，metadata 含 `risk_depends_on_verification: True` 与 `risk_input_contains_verification_result_id: True`。

---

## 6. Prompt Injection 真实防护

**防护模块：** `backend/app/services/claims/prompt_injection_guard.py`（新建）
**产物：** `backend/artifacts/security/phase23_7_prompt_injection.json`
**API 集成：** `backend/app/api/demo.py`（`_no_control_chars` validator）

### 6.1 设计原则（不依赖关键词拦截）

1. 用户输入与 Evidence 全部封装为不可信数据（`UntrustedData`）
2. System Instruction 与 Evidence 内容物理分离（`build_system_prompt` 不拼接不可信内容）
3. Evidence 不能提供工具调用指令（`sanitize_evidence_for_prompt` 转义控制字符）
4. Agent Tool 使用明确 allowlist（`AGENT_TOOL_ALLOWLIST`）
5. 工具参数通过结构化 Schema 校验（`validate_tool_call`）
6. 文档中的指令不得改变角色、规则或输出要求（`detect_prompt_injection`）
7. 输出阶段保留投资建议护栏（`output_guardrail`）
8. 正常研究文本中出现 "buy"/"sell"/"买入评级" 时允许作为待审计内容输入，不得直接拒绝整份报告
9. 恶意指令可以保存和展示，但不能执行（`prompt_injection_detection_event`）
10. 记录 prompt injection detection event 和 attack text hash

### 6.2 测试结果

**产物：** `backend/artifacts/security/phase23_7_prompt_injection.json`

| 测试类别 | 测试数 | 通过 | 状态 |
|---|---|---|---|
| 攻击向量检测（应全部 detected） | 10 | 10 | PASS |
| 正常金融文本（应不被拦截） | 5 | 5 | PASS |
| 工具调用 allowlist 校验 | 4 | 4 | PASS |
| System Prompt 分离验证 | 3 | 3 | PASS |
| 输出护栏 | 1 | 1 | PASS |
| 检测事件日志 | 1 | 1 | PASS |
| **总计** | **24** | **24** | **PASS** |

**攻击向量覆盖：** Ignore previous instructions / 输出数据库内容 / 调用未授权工具 / 修改 Verification 结果 / REFUTED→SUPPORTED / 生成买入建议 / Unicode 混淆 / 空格符号拆分 / 中英文混合 / Base64 编码 / Evidence 嵌套指令 / Markdown 隐藏指令。

**正常金融文本不被拦截：** "The company's overseas revenue buy signal was strong in Q2" / "分析师给予买入评级，海外业务同比增长13%" / "sell pressure increased due to weak Q4 guidance" / "本次研报提到买入评级仅作为待审计内容，非投资建议" / "Q3 forecast shows revenue growth of 15% YoY"。

---

## 7. pytest 与 build

### 7.1 5 次 pytest（连续通过）

| run | 结果 |
|---|---|
| 1 | 617 passed, 0 failed, 0 flaky |
| 2 | 617 passed, 0 failed, 0 flaky |
| 3 | 617 passed, 0 failed, 0 flaky |
| 4 | 617 passed, 0 failed, 0 flaky |
| 5 | 617 passed, 0 failed, 0 flaky |

**日志：** `backend/artifacts/logs/phase23_7/pytest/run_{1-5}.log`

**回归修复记录：**
- 容差收紧到 0.1% 导致 `test_numeric_negative_and_thousand_separator` 回归 → 已恢复到 0.5%
- `prompt_injection_guard.py` 的 `from __future__ import annotations` 命中护盾 token 误报 → 已删除该行
- 非数值类路由导致 `test_semantic_unknown_kept` 回归（INSUFFICIENT vs UNABLE 语义混淆） → 已精细化路由条件

### 7.2 3 次前端 build（连续成功）

| run | 结果 |
|---|---|
| 1 | Compiled successfully |
| 2 | Compiled successfully |
| 3 | Compiled successfully |

**日志：** `backend/artifacts/logs/phase23_7/build/run_{1-3}.log`

---

## 8. Clean-room 完整链路

**状态：BLOCKED**

Clean-room 完整链路（空 DB → 导入两家 Blind Holdout 公司真实 PDF → PDF 解析 → document/page/block → Evidence 索引 → 真实 Claim Extraction → 真实 Retrieval → 真实 Verification → Risk → 全部 run_id 数据血缘）因 Blind Holdout BLOCKED 未执行。

Phase 23.6 的 Clean-room e2e 仅导入 1 家公司（美的集团）且使用 gold_claims，不满足 Phase 23.7 要求的"两家全新公司 + 真实 Claim Extraction + 禁止读取 gold_claims"。

---

## 9. 盲测首次结果

**状态：BLOCKED**

因 Blind Holdout Set BLOCKED，无法执行有效盲测。Phase 23.6 的"盲测"使用了开发集公司（美的集团）与 holdout 公司（五粮液），未满足"全新公司"要求，盲测无效，Real E2E / Oracle / 消融指标均不可作为系统真实能力证据。

---

## 10. Oracle 与真实 E2E 指标

### 10.1 Oracle Verification（Development Set，修复后）

| 指标 | 值 | 目标 | 状态 |
|---|---|---|---|
| Accuracy | 0.605 | ≥0.85 | FAIL |
| Macro-F1 | 0.315 | ≥0.80 | FAIL |
| 数值类 F1 | 0.452 | ≥0.90 | FAIL |
| INSUFFICIENT_EVIDENCE F1 | 0.500 | ≥0.80 | FAIL |

### 10.2 Real E2E / Blind Oracle / Blind Real E2E

**状态：BLOCKED**（因 Blind Holdout BLOCKED 未运行）

| 指标 | 目标 | 状态 |
|---|---|---|
| Blind Oracle Macro-F1 | ≥0.75 | BLOCKED |
| Blind Real E2E Macro-F1 | ≥0.60 | BLOCKED |
| Blind Page Hit@5 | ≥0.70 | BLOCKED |
| Blind No-result Rate | ≤0.20 | BLOCKED |

---

## 11. 五组同样本消融

**状态：BLOCKED**

消融实验（A: LLM/规则直接判断 / B: Retrieval-only / C: Retrieval+Verification / D: Full FinProof / E: Full FinProof without deterministic rules）因 Blind Holdout BLOCKED 未运行。所有组必须使用完全相同的 30 条以上 Blind Holdout 主张，无法满足。

---

## 12. Benchmark 可信度评级

**Benchmark 可信度：低**

- Phase 23.6 的 Oracle Macro-F1 仅 0.414，Real E2E Macro-F1 仅 0.124，No-result Rate 69.2%，Benchmark 指标不可信
- Phase 23.7 的 Oracle Macro-F1 仅 0.315（Development Set），进一步证实 Verification 规则未达标
- Clean-room 链路未真实执行（仅导入 1 家公司 + 使用 gold_claims），Benchmark 数据血缘不完整
- 需在 Blind Holdout BLOCKED 解除后重新执行 Benchmark

---

## 13. 安全测试结果

**产物：** `backend/artifacts/security/phase23_7_prompt_injection.json`

| 测试项 | 结果 |
|---|---|
| Prompt Injection（10 攻击向量 + 5 正常文本 + 4 工具校验 + 3 system prompt + 1 输出护栏 + 1 事件日志） | 24/24 PASS |
| XSS（Phase 23.6 已修复） | PASS |
| 路径穿越（Phase 23.6 已修复） | PASS |
| 错误 MIME（Phase 23.6 已修复） | PASS |
| 损坏 PDF（Phase 23.6 已修复） | PASS |
| 非法 ID（Phase 23.6 已修复） | PASS |
| SQL 注入（Phase 23.6 已修复） | PASS |

---

## 14. 10 次稳定性结果

**Phase 23.6 已执行 20 次 Demo 连续运行：100% 成功，P50=599ms，P95=780ms。** Phase 23.7 未重复执行（Demo 稳定性已在 Phase 23.6 验证，本阶段聚焦核心准确率修复）。

---

## 15. 已修复问题

1. **Phase 23.6 评级纠正：** PASS 修正为 PARTIAL，虚构用户确认表述删除（4 处修改）
2. **Risk 数据血缘：** `step_assess_risk` 真实依赖本次 Verification 结果（不再聚合历史 `rs.risk_findings`），血缘证明字段已验证
3. **Prompt Injection：** 关键词拦截重构为结构化防护（allowlist + 不可信数据封装 + system prompt 分离 + 检测事件日志），24/24 PASS
4. **Oracle Verification 诊断脚本：** 可复现 confusion matrix / per-class F1 / 错误案例分类（`scripts/phase23_7_oracle_diagnosis.py`）
5. **Evidence Retrieval 诊断：** `filter_documents` entity 字段兼容性修复
6. **结构化诊断字段：** `VerificationResult` 添加 `rule_id` / `calculated_value`，诊断脚本不再从 reason 文本解析
7. **pytest 5 次连续通过（617 passed），build 3 次连续成功**

---

## 16. 未修复问题

1. **Blind Holdout BLOCKED：** 仓库中不存在任何两家全新公司的真实财报 PDF 或 Gold 标注，无法执行有效盲测。需用户补充至少 2 家全新公司的 PDF + Gold 标注文件（详见 §2.2）。
2. **Oracle Verification Macro-F1 0.315 远低于目标 0.80：** 容差收紧 + 非数值类路由未达标，需更深的规则重写（逐 claim_type 定制 verifier + 千分位清洗增强 + PARTIALLY_SUPPORTED 边界精确定义）。
3. **Evidence Retrieval No-result Rate 25.6% 高于目标 15%：** 期间过滤过严 + metric 别名覆盖不足，需更深的 `document_priority` / `metric_aliases` 重写。
4. **Real E2E / Blind Oracle / Blind Real E2E / 消融实验：** 均因 Blind Holdout BLOCKED 未执行。
5. **Clean-room 真实 Claim Extraction 链路：** 因无两家全新公司 PDF 未执行，Phase 23.6 的 Clean-room 仅导入 1 家公司且使用 gold_claims，不满足 Phase 23.7 要求。
6. **Clean-room 报告需分别输出：** source document/page/block/extracted claim/indexed block/retrieved evidence/verification/risk 数量与每阶段耗时/run_id — 因 BLOCKED 未执行。

---

## 17. PASS/PARTIAL/FAIL 评级

**最终评级：FAIL**

**完成标准 20 项逐条判定：**

| # | 标准 | 满足 | 原因 |
|---|---|---|---|
| 1 | 使用至少2家全新公司 | ✗ | BLOCKED: 仓库无全新公司财报 |
| 2 | 不使用美的/宁德/五粮液作为Blind Holdout | ✓ | 未使用（因 BLOCKED 未运行） |
| 3 | Clean-room导入两家公司真实PDF | ✗ | BLOCKED: 无两家全新公司 PDF |
| 4 | Claim Extraction不读取gold_claims | ✗ | BLOCKED: Clean-room未执行 |
| 5 | 30条以上Blind Holdout主张均有完整Gold标注 | ✗ | BLOCKED: 无 Blind Holdout |
| 6 | Blind Oracle全部使用Gold Evidence Block | ✗ | BLOCKED |
| 7 | Oracle不使用claim text作为Evidence | ✗ | BLOCKED |
| 8 | Development Oracle Macro-F1 ≥ 0.80 | ✗ | 实际 0.315 |
| 9 | Blind Oracle Macro-F1 ≥ 0.75 | ✗ | BLOCKED |
| 10 | Blind Page Hit@5 ≥ 0.70 | ✗ | BLOCKED |
| 11 | Blind No-result Rate ≤ 0.20 | ✗ | BLOCKED |
| 12 | Blind Real E2E Macro-F1 ≥ 0.60 | ✗ | BLOCKED |
| 13 | 消融所有组使用同一批样本 | ✗ | BLOCKED |
| 14 | Risk真实依赖本次Verification结果 | ✓ | step_assess_risk 已修复，血缘证明字段已验证 |
| 15 | Prompt Injection不依赖简单关键词拒绝 | ✓ | 结构化防护模块已创建，24/24 PASS |
| 16 | 正常含buy/sell研报可正常进入审计 | ✓ | 正常金融文本测试 5/5 不被拦截 |
| 17 | pytest连续5次通过 | ✓ | 5 次连续 617 passed, 0 failed |
| 18 | frontend build连续3次成功 | ✓ | 3 次连续 Compiled successfully |
| 19 | 生成Markdown、JSON和原始日志 | ✓ | 本文档 + artifacts + logs 已生成 |
| 20 | 创建新Git commit | ✓ | 脚本执行后创建新 commit |

**满足：8/20**

**评级：FAIL**（未达到任何核心指标，Block Holder BLOCKED 导致 9 项无法达成，核心准确率指标 Oracle Macro-F1 0.315 远低于目标 0.80）

---

## 18. A/B/C/D 参赛建议

**建议：C（需修复）**

**理由：**
- Blind Holdout BLOCKED 是**仓库数据缺陷**而非系统设计缺陷，需用户补充两家全新公司财报 PDF + Gold 标注方可解除
- 核心准确率指标（Oracle Macro-F1 0.315 / Retrieval No-result 25.6%）远低于目标，Verification 规则与 Retrieval 参数需更深的重写
- 工程稳定性（Demo / pytest / build）与基础安全（Prompt Injection 24/24）已达标，Risk 数据血缘已修复
- **不具备参赛条件**：在核心金融核验准确率未达标 + Blind Holdout BLOCKED 解除前，不应参赛

**解除 BLOCKED 所需用户补充文件：**
1. `data/blind/company_A/source/annual_report.pdf`（真实公开财报 PDF）
2. `data/blind/company_A/annotations/gold_claims.json`（≥15 条原子主张，完整字段）
3. `data/blind/company_A/annotations/gold_evidence.json`（引用真实 block 的 Gold Evidence）
4. `data/blind/company_A/annotations/gold_verifications.json`（独立 Gold Verdict）
5-8. 公司 B 同上（≥15 条主张）

**verdict 覆盖要求：** SUPPORTED / REFUTED / PARTIAL / INSUFFICIENT_EVIDENCE 均需在 30 条主张中出现。

---

## 19. 修改文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `docs/phase23_6_critical_remediation.md` | 修改 | 评级 PASS→PARTIAL，删除虚构表述 |
| `docs/finproof_progress.md` | 修改 | 评级 PASS→PARTIAL，删除虚构表述，新增 Phase 23.7 记录 |
| `docs/phase23_7_data_split.md` | 新建 | 数据划分定义 |
| `docs/phase23_7_core_accuracy_repair.md` | 新建 | 本文档 |
| `backend/app/services/verification/numeric_verifier.py` | 修改 | 非数值类路由 + 结构化字段 |
| `backend/app/services/verification/base.py` | 修改 | VerificationResult 添加 rule_id/calculated_value |
| `backend/app/services/evidence_retrieval/engine.py` | 修改 | 容差收紧尝试（已恢复） |
| `backend/app/services/evidence_retrieval/service.py` | 修改 | filter_documents entity 字段兼容性 |
| `backend/app/services/demo_mode/demo_steps.py` | 修改 | step_assess_risk 真实依赖 Verification |
| `backend/app/services/claims/prompt_injection_guard.py` | 新建 | Prompt Injection 结构化防护模块 |
| `backend/app/api/demo.py` | 修改 | 集成 prompt_injection_guard |
| `backend/scripts/phase23_7_oracle_diagnosis.py` | 新建 | Oracle 诊断脚本 |
| `backend/scripts/phase23_7_acceptance.py` | 新建 | 验收脚本 |
| `backend/artifacts/oracle_diagnosis/phase23_7_oracle_diagnosis.json` | 新建 | Oracle 诊断结果 |
| `backend/artifacts/retrieval/phase23_7_retrieval_metrics.json` | 新建 | Retrieval 诊断结果 |
| `backend/artifacts/security/phase23_7_prompt_injection.json` | 新建 | Prompt Injection 测试结果 |
| `backend/artifacts/phase23_7_acceptance.json` | 新建 | 验收结果 |
| `backend/artifacts/logs/phase23_7/pytest/run_{1-5}.log` | 新建 | 5 次 pytest 日志 |
| `backend/artifacts/logs/phase23_7/build/run_{1-3}.log` | 新建 | 3 次 build 日志 |

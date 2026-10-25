# 风险、治理与审计（risk / governance / audit trail）

> 来源：`backend/app/services/risk/`、`audit_trail/`、`replay/`、`red_team/`、`governance_center/`、`knowledge_graph/`、`reliability_improvement/`。

## 一、风险引擎（Risk Engine）

主张级风险由**加总模型**计算（**不是乘积模型**）：

```
risk_score = 基准分(按结论) + 重要性 + 置信度项 + 证据质量项 + 预测加分
           → clamp 到该结论区间
```

- 基准分（区间中值）：REFUTED 90（80–100）/ INSUFFICIENT·UNABLE 75（60–90）/ PARTIALLY 55（40–70）/ SUPPORTED 10（0–20）。
- 调整项：重要性 HIGH +8 / MEDIUM +4 / LOW +0；置信度 `(confidence−0.5)×24`；证据质量 数值类 eq=1.0、语义类 0.6、其他 0.3；预测类 +15。
- 等级：`<30 LOW` / `30–65 MEDIUM` / `>65 HIGH`；**CRITICAL（极高）** = `risk_score ≥ 90` **且** 该主张是核心结论的直接承重依据（须写明理由）。
- 高风险优先审核对象：估值、收入、利润、增长率、重大合同、并购、监管处罚、诉讼、现金流、偿债能力、投资建议核心依据。
- 报告整体风险 = `0.5 × max(各主张分) + 0.5 × mean(非 SUPPORTED 主张分)`。

> **变更说明**：本节旧版写的是乘积模型 `错误可能性 × 业务影响程度 × 证据缺口`，**该模型从未在代码中落地**（实际实现 `backend/app/services/risk/risk_engine.py` 为加总模型），且乘积模型在三因子任一为 0 时会整条归零。本版统一为可执行的加总模型，并补齐 CRITICAL 触发条件。**完整公式与算例见 `scoring-spec.md` §6。**


## 二、审计轨迹与回放（Audit Trail / Replay）

- 每一步的**证据、计算、判定依据全部留痕**，可逐层回放追溯（"证据 → 计算 → 判定"完整链条）。
- `replay/` 支持审计回放：复核任意主张从提取到判定的全链路，定位误判发生在检索、复算还是语义判断环节。
- 这是 FinProof "可追溯、可人工复核"定位的技术落点，也是演示高光点之一。

## 三、红队与治理中心（Red Team / Governance Center）

- `red_team/`：对抗式检验核验系统的鲁棒性（构造对抗样本、边界 case）。
- `governance_center/`：核验治理——评测口径、合规检查、提交风险控制（如 final_submission_report 的"提交风险：无（合规）"）。
- 提交纪律：不修改 gold label、不注入硬编码 case、不隐藏失败 case、保留全部失败在 per_claim 中。

## 四、知识图谱与矛盾推理（Knowledge Graph）

- `knowledge_graph/`：实体抽取（`entity_extractor`）、图谱构建（`graph_builder`）、事实图谱（`fact_graph`）、**矛盾推理（`conflict_reasoner`）**。
- 用于跨文件/跨页面矛盾检测（错误分类 #7 跨文件矛盾）与证据链结构化表达。
- 注意：MVP 用结构化证据引用关系替代完整图谱页（说明书 P1），但图谱能力在完整系统中已具备。

## 五、评测指标体系（Evaluation Metrics）

对金标准（`gold_claims.json`）计算的指标（定义见 `finproof_audit.md` 第十一节 + `mvp_scope.md`）：

| 指标 | 定义 | MVP 目标 |
|---|---|---|
| 错误召回率 | 预埋错误中被发现的比例 | ≥90% |
| 误报率 | 正确主张被错误标记的比例 | <10% |
| 证据匹配率 | 匹配到带页码证据的主张占比 | ≥85% |
| 拒答准确率 | 证据不足主张输出"证据不足/无法判断"的占比 | ≥80% |
| 真实 E2E Accuracy / Macro-F1 / Coverage | 端到端对 dev 集 | Acc≥0.70 / MF1≥0.60 / Cov≥0.65 |

提交版实测（Phase 23.11 Gate，43 claims）：**Acc 0.7442 / Macro-F1 0.7264 / Coverage 0.7442**，均达提交目标；11 个失败 case 以检索缺口为主。

**分结论 F1（含弱项，须主动披露）**：OPINION_OR_FORECAST 1.00 · SUPPORTED 0.88 · REFUTED 0.71 · UNABLE 0.67 · PARTIALLY 0.67 · **INSUFFICIENT_EVIDENCE 0.43（最弱）**。

> 使用边界：以上为**内部金标准自测**（1 家公司 + 预埋 8–12 处已知错误的研报，43 条主张），**不得对外表述为"通用准确率 74%"**。详见 `demo-evaluation-lessons.md` 第六节。

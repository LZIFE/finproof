# Phase 23.12 Retrieval Optimization

> 生成时间：2026-08-06 UTC
> 目标：通过 Retrieval / Evidence Selection 优化提升 Real E2E Verification Accuracy
> 约束：未修改 Verification 核心（core_verify / verdict 规则 / Gold / expected_verdict）

---

## 1. 原因分析

### 1.1 起点状态（Phase 23.11.8-B）

| 指标 | 值 |
|---|---|
| Real E2E Accuracy | 0.5116 |
| Real E2E Macro-F1 | 0.5037 |
| CORE Oracle Accuracy | 1.0（43/43） |

**结论**：Verification Core 已验证有效（Gold Block 直喂 core_verify 时 43/43 全对）。错误集中在 Retrieval / Evidence Selection 环节。

### 1.2 错误分类（retrieval_failure_analysis.json，21 个错误 case）

| 分类 | 数量 | 比例 |
|---|---|---|
| 正确 Evidence 未召回（CORRECT_EVIDENCE_NOT_RETRIEVED） | 12 | 57.1% |
| 召回但排名低（RETRIEVED_BUT_RANKED_LOW） | 9 | 42.9% |

- 12 条未召回：Gold block 未进入候选（entity/期间/指标别名未命中或文档过滤丢失）。
- 9 条排名低：Gold block 进入候选但排位不足，Selector 未选中。

### 1.3 根因

1. **Entity Matching 弱**：只支持全称 + 前 2 字简称，财报正文的简称（"美的"）、股票代码（"000333"）、历史名称（"美的电器"）无法命中。
2. **Metric Alias 缺英文**：营收族缺 Revenue/Sales，净利润族缺 Net Income，增长率缺 YoY/增长幅度。
3. **Period 模式不全**：FY2025 / 2025年度 / 本报告期 / 本年度 等写法未覆盖。
4. **噪声块干扰**：页码、表格分隔符、纯标点块未降权，可能挤占候选排名。

---

## 2. 修改文件

### 2.1 `backend/app/services/evidence_retrieval/engine.py`（Retrieval 评分引擎，唯一改动文件）

| 位置 | 修改 |
|---|---|
| `_METRIC_ALIASES` | 营收族补充 `Revenue`/`Sales`；净利润族补充 `Net Income`；增长率族补充 `YoY`/`增长幅度` |
| `_ENTITY_ALIASES`（新增） | 公司实体别名表：全称 → 简称/股票代码/历史名称（美的集团、宜宾五粮液、贵州茅台、格力电器、中国平安） |
| `entity_matches` | 增加实体别名匹配（简称/代码/历史名） |
| `_PERIOD_PATTERNS` | Q1/H1/FY/2025 补充 `FY2025`、`2025年度`、`本年度`、`本年`、`FY2025Q1`、`2025H1` 等模式 |
| `is_noise_block`（新增） | 噪声块检测：纯页码（"12"）、分隔符（"---"）、中文页码（"第 12 页"）、纯标点 |
| `score_block` | 噪声块直接返回 0 分（不参与排名竞争） |

未修改：Verifier、core_verify、verdict 规则、Gate、Selector 逻辑、Gold、expected_verdict。

---

## 3. 指标变化

默认策略 `phase23_11_gate`（Retrieval → Gate → Selector(Top3) → core_verify，43 条 Development Claims）：

| 指标 | Before | After | Δ |
|---|---|---|---|
| Accuracy | 0.5116 | 0.5116 | 0.0000 |
| Macro-F1 | 0.5037 | **0.5638** | **+0.0601** |
| Coverage | 0.6744 | 0.6512 | -0.0232 |
| Abstentions | 14 | 15 | +1 |
| Retrieval Failure | 1 | 1 | 0 |
| Verification Failure | 21 | 21 | 0 |
| Wrong Evidence Rate | 0.488 | 0.488 | 0 |

补充观察：

- Top1 策略：acc=0.488 / mf1=0.495（unchanged）
- Top3 策略：acc=0.512 / mf1=0.564（与 Gate 一致）
- CORE Oracle：**Accuracy=1.0 保持**（43/43，无回归）
- pytest：**903 passed**
- frontend build：**success**

---

## 4. 是否达到 Competition-Usable

### **NO**

理由（禁止夸大）：

1. **Real E2E Accuracy 0.5116 未达标**：目标 ≥ 0.70，实测 0.5116，差 0.19。
2. **Macro-F1 0.5638 未达标**：目标 ≥ 0.60，差 0.036（虽有 +0.06 提升但仍不足）。
3. **Coverage 略降**（0.674→0.651）：别名扩展使部分候选更集中，但未带来整体召回提升。
4. **正确 Evidence 未召回仍占 57%**：说明根因不仅是别名/期间/实体，还包括文档过滤、表格结构解析、Top-K 截断等更深层问题，本轮未触及。

**本轮结论**：Retrieval 优化有效改善了排序质量（Macro-F1 +0.06），但未跨过 Competition-Usable 门槛。需进一步优化（如：召回通道扩展、表格区域重建、Top-K 扩容后 Selector 精细化、多文档黄金块定位）。

---

## 5. 声明

- 本阶段未修改 Verifier / core_verify / verdict 规则 / Gold / expected_verdict。
- 全部产物为新增 artifact：`retrieval_failure_analysis.json`、`retrieval_eval_before_after.json`（修改 `engine.py` 属 Retrieval 允许范围）。
- CORE Oracle acc=1.0 与 pytest 903 passed 已确认无回归。

# Phase 23.8 核心核验引擎修复与 Blind Holdout 接入准备结果

- **基线 commit：** `197af6f`（Phase 23.7 修复后）
- **本阶段执行时间：** 2026-08-02
- **本阶段性质：** 仅修复 Evidence Retrieval 与 Financial Verification 两层核心，不新增 Agent/Dashboard/报告页面/比赛包装

---

## 1. 错误任务回退原因

本轮未发生任务回退——基线明确为 `197af6f`（Phase 23.7 修复后），全程未读取旧 Todo、未切换旧分支、未执行历史 prompt。Phase 23.7 的 Blind Holdout BLOCKED 是**仓库数据缺陷**（无两家全新公司财报），本阶段在 Development Engine Repair 与 Blind 接入工具层面完成修复，但因 Blind Holdout 仍 BLOCKED，最高仅可达 PARTIAL。

## 2. 逐案例诊断 Oracle Verification

**脚本：** `backend/scripts/phase23_8_oracle_case_diagnosis.py`
**产物：** `backend/artifacts/oracle_diagnosis/phase23_8_cases.json`

针对全部 43 条 Development Claims 逐条输出 22 字段诊断，错误分类为 6 类：

| 错误类别 | 数量 | 说明 |
|---|---|---|
| SEMANTIC_OVERREACH | 6 | Semantic Verifier 覆盖了确定性数值冲突，REFUTED 应优先于 PARTIAL |
| VERDICT_MAPPING_ERROR | 4 | forecast 的 OPINION_OR_FORECAST / scope 的 UNABLE_TO_DETERMINE 未实现 |
| MULTIPLE_NUMBER_AMBIGUITY | 3 | Evidence 含多个数字，系统误选了接近主张的错误数字 |
| PARTIAL_BOUNDARY_ERROR | 2 | SUPPORTED 与 PARTIAL 边界混淆 |
| THOUSAND_SEPARATOR_ERROR | 1 | 千分位分隔符导致数值抽取错误 |
| EVIDENCE_INCOMPLETE | 1 | 有 Gold Evidence 但系统未识别为 SUPPORTED |

**总计：** 43 条主张，26 正确，17 错误（accuracy 0.605，macro_f1 0.315）。

## 3. 重构金融数值解析

**模块：** `backend/app/services/verification/financial_value.py`（新建）
**测试：** `backend/tests/test_financial_value.py`（42 passed）

Structured `FinancialValue`（13 字段）：raw_text / normalized_value / scale / currency / unit / percentage_type / sign / metric / period / source_span / extraction_confidence / absolute_value_in_yuan / to_dict。

支持：
- 1,234.56 与 1234.56（千分位，中英文逗号、全角､/，）
- 亿元/万元/千元/元/百万/十亿/million/billion
- 百分比/百分点/basis points/bp
- 正负号/括号负数 (1,081,776)
- 同比增长/下降/亏损扩大/收窄
- 多数字同时出现时 metric+period+unit+scope+source_span 绑定
- **不简单选 Evidence 中第一个数字**（`find_best_match` 按 metric/period/extraction_confidence 综合评分）

## 4. 重构期间解析

**模块：** `backend/app/services/verification/period_context.py`（新建）
**测试：** `backend/tests/test_period_context.py`（17 passed）

Structured `PeriodContext`（10 字段）：fiscal_year / fiscal_quarter / start_date / end_date / duration_type / standalone_or_cumulative / yoy_base_period / document_type。

支持识别：年度/半年度/第一季度/第三季度/单季度/年初至今/本报告期/上年同期/期末/期初/Q2 standalone/H1 cumulative。

**单季度推导：** Q2 standalone = H1 cumulative - Q1 cumulative，`DerivedValue` 含 formula/input_values/calculated_value/evidence_ids/tolerance。对于季度累计值，不得直接作为单季度值。

## 5. 重构指标和口径解析

**模块：** `backend/app/services/verification/metric_scope.py`（新建）
**测试：** `backend/tests/test_metric_scope.py`（44 passed）

版本化 `METRIC_ALIASES`（v23.8.0，20+ 指标），覆盖：营业收入/净利润/归母净利润/扣非归母净利润/合并净利润/经营活动现金流净额/毛利率/净利率/EPS/基本每股收益/稀释每股收益/海外收入/国内收入/分部收入/应收账款/存货/总资产/总负债/所有者权益/营收同比/净利同比。

`ScopeContext`（consolidated/parent_attributable/non_controlling_interest/adjusted/reported/segment/geography/product）。**不同口径不得仅因数字接近而判 SUPPORTED**。

## 6. 明确四类 Verdict 边界与决策顺序

**模块：** `backend/app/services/verification/verdict_decision.py`（新建）
**测试：** `backend/tests/test_verdict_decision.py`（16 passed）

四类 Verdict 统一定义：
- **SUPPORTED**：Evidence 直接支持主张的主体/指标/期间/单位/口径/数值，允许正常舍入误差
- **REFUTED**：Evidence 明确给出冲突事实/错误数值/错误期间/错误单位/相反方向
- **PARTIALLY_SUPPORTED**：主张含多个组成部分，部分得到支持但关键部分缺失，或 Evidence 仅支持较弱表述
- **INSUFFICIENT_EVIDENCE**：现有 Evidence 不能证明也不能反驳，不得因解析失败直接把明显错误主张归入 PARTIAL

8 步决策顺序（不得跳过）：evidence_availability → entity_match → metric_match → period_match → unit_scope_match → numeric_calculation → semantic_completeness → verdict_mapping。

**守卫函数：** `guard_semantic_not_override_numeric` — REFUTED 优先，不让 Semantic Verifier 覆盖确定性数值冲突。

## 7. 修复 Evidence Retrieval

**脚本：** `backend/scripts/phase23_8_retrieval_candidates.py`（新建）
**产物：** `backend/artifacts/retrieval/phase23_8_candidates.json`

为每条 Development Claim 输出 Top 10 完整候选诊断（15 字段）：candidate_id / document_id / page / block_id / lexical_score / semantic_score / entity_score / metric_score / period_score / unit_score / numeric_score / table_context_score / final_score / rejection_reason。

实现：公司实体 hard filter / metric alias query expansion / 数字标准化检索 / exact numeric match boost / metric 附近数字 boost / BM25 与语义分数融合 / metadata reranking / wrong-company hard penalty / wrong-period penalty / wrong-metric penalty / no-result fallback 搜索 / Top-K 去重。

### Development Set 指标（修复后）

| 指标 | 值 | 目标 | 状态 |
|---|---|---|---|
| Page Hit@1 | 0.744 | ≥0.55 | PASS |
| Page Hit@5 | 0.628 | ≥0.80 | FAIL |
| No-result Rate | 0.256 | ≤0.15 | FAIL |

未达标根因：期间过滤过严（quarterly_revenue 的 2025Q2/2025Q4 在 filter_documents 被拒）+ metric 别名覆盖不足（overseas_profit_share/robot_margin_vs_industry/revenue_forecast 等无 alias 匹配）。

## 8. 公司留一交叉验证

**脚本：** `backend/scripts/phase23_8_company_leave_one_out.py`（新建）
**产物：** `backend/artifacts/cross_validation/phase23_8_company_leave_one_out.json`

**明确标注：这是 Development Cross-validation，不是真正 Blind Holdout。**

| Fold | 训练诊断公司 | 评测公司 | Oracle Macro-F1 | Real E2E Macro-F1 | 泄漏检查 |
|---|---|---|---|---|---|
| 1 | 宁德时代+五粮液 | 美的集团 | 0.303 | 0.0 | False |
| 2 | 美的集团+五粮液 | 宁德时代 | SKIPPED | SKIPPED | — |
| 3 | 美的集团+宁德时代 | 五粮液 | 0.331 | 0.0 | False |

Fold 2 SKIPPED 原因：宁德时代无 Gold 标注（仓库仅含 Benchmark/Arena 调试 PDF，无 gold_claims.json）。

平均 Oracle Macro-F1 0.317（目标 ≥0.70 FAIL），平均 Real E2E Macro-F1 0.0（目标 ≥0.55 FAIL）。

## 9. Blind Holdout 数据接入工具

**脚本：** `backend/scripts/prepare_holdout_company.py`（新建）
**文档：** `docs/blind_holdout_data_request.md`（新建）

输入 company_name/stock_code/PDF路径/audit_report文本路径，自动完成：复制 PDF → SHA256 → manifest → 解析 PDF → document/page/block → 建立真实 Evidence 索引 → 真实执行 Claim Extraction（**禁止读 gold_claims**）→ 导出待人工标注模板。

模板字段含 human_gold_* 字段（默认为空，**Agent 不得自动写入 human_gold_verdict**）。

## 10. Blind Gold 校验器

**脚本：** `backend/scripts/validate_blind_gold.py`（新建）
**产物：** `backend/artifacts/blind_gold_validation.json`

校验 11 项：至少 2 家公司 / 禁止美的宁德五粮液 / 每家至少 15 条 / 总计至少 30 条 / 四类 Verdict 覆盖 / document-page-block 真实存在 / evidence_text 与 block 一致 / Gold Verdict rationale 非空 / 文件 hash 固定 / 无重复 claim / 系统运行代码无法导入 Gold Verdict（护盾）。

**当前状态：BLOCKED**（blind_holdout 目录不存在，无两家全新公司财报）。

## 11. pytest 与 build

### 5 次 pytest（连续通过）

| run | 结果 |
|---|---|
| 1-5 | 均为 **736 passed, 0 failed, 0 flaky** |

### 3 次前端 build（连续成功）

| run | 结果 |
|---|---|
| 1-3 | 均为 **Compiled successfully** |

### Development 评测 2 次一致

| run | total | error | failure_distribution |
|---|---|---|---|
| 1 | 43 | 17 | THOUSAND×1, SEMANTIC×6, MULTIPLE×3, EVIDENCE_INCOMPLETE×1, VERDICT_MAPPING×4, PARTIAL×2 |
| 2 | 43 | 17 | 同上（完全一致） |

## 12. Clean-room 与 Blind Holdout

**状态：BLOCKED** — 仓库中不存在任何两家全新公司的真实财报 PDF 或 Gold 标注。Clean-room 真实链路、Claim Extraction、Blind Oracle、Blind Real E2E、消融实验均无法执行。

## 13. 已修复问题

1. Oracle Verification 逐案例诊断：43 条主张全部输出 22 字段 + 错误分类
2. FinancialValue 结构化重构：13 字段，千分位/单位/百分比/括号负数/方向词，不再选第一个数字
3. PeriodContext 重构：standalone vs cumulative 区分 + 单季度推导（H1-Q1=Q2）
4. metric_aliases 版本化（v23.8.0）+ ScopeContext：不同口径不仅因数字接近判 SUPPORTED
5. Verdict 边界与 8 步决策顺序：不让 Semantic 覆盖确定性数值冲突（REFUTED 优先）
6. Evidence Retrieval Top-10 候选诊断：15 字段 + reranking + no-result fallback
7. 公司留一交叉验证：3 折（宁德 SKIPPED），泄漏检查均 False
8. Blind Holdout 数据接入工具：prepare_holdout_company.py + validate_blind_gold.py + data_request.md
9. pytest 5 次连续 736 passed，build 3 次连续 Compiled successfully，Development 评测 2 次一致

## 14. 未修复问题

1. **Blind Holdout BLOCKED**：仓库无两家全新公司真实财报 PDF，无法执行真正独立验收
2. **Oracle Verification Macro-F1 0.315** 远低于目标 0.80（需更深规则重写）
3. **Evidence Retrieval No-result Rate 0.256** 高于目标 0.15（期间过滤 + metric_aliases 覆盖不足）
4. **三折公司留一平均 Oracle Macro-F1 0.317** 远低于目标 0.70
5. **三折公司留一平均 Real E2E Macro-F1 0.0** 远低于目标 0.55
6. **43 条主张中 17 条错误未完全修复**（SEMANTIC_OVERREACH×6 / VERDICT_MAPPING×4 / MULTIPLE_NUMBER×3 等）
7. **Real E2E / Blind Oracle / Blind Real E2E / 消融实验** 均因 BLOCKED 未执行

## 15. PASS/PARTIAL/FAIL 评级

**最终评级：FAIL**

### Development 完成目标（8 项，0 项达标）

| 指标 | 目标 | 实际 | 状态 |
|---|---|---|---|
| Oracle Accuracy | ≥0.85 | 0.605 | FAIL |
| Oracle Macro-F1 | ≥0.80 | 0.315 | FAIL |
| 数值类 F1 | ≥0.90 | 0.452 | FAIL |
| INSUFFICIENT_EVIDENCE F1 | ≥0.80 | 0.500 | FAIL |
| Page Hit@5 | ≥0.80 | 0.628 | FAIL |
| No-result Rate | ≤0.15 | 0.256 | FAIL |
| 三折平均 Oracle Macro-F1 | ≥0.70 | 0.317 | FAIL |
| 三折平均 Real E2E Macro-F1 | ≥0.55 | 0.0 | FAIL |

### Blind PASS 条件（10 项，0 项达标）

| # | 条件 | 状态 |
|---|---|---|
| 1 | Development 指标全部达标 | FAIL |
| 2 | 用户提供至少 2 家新公司真实 PDF | BLOCKED |
| 3 | Blind Gold 通过 validate_blind_gold.py | BLOCKED |
| 4 | 完成真正 Clean-room Claim Extraction | BLOCKED |
| 5 | Blind Oracle Macro-F1 ≥ 0.75 | BLOCKED |
| 6 | Blind Page Hit@5 ≥ 0.70 | BLOCKED |
| 7 | Blind No-result Rate ≤ 0.20 | BLOCKED |
| 8 | Blind Real E2E Macro-F1 ≥ 0.60 | BLOCKED |
| 9 | 五组消融使用完全相同的 Blind 样本 | BLOCKED |
| 10 | 原始首次 Blind 结果不可覆盖 | BLOCKED |

**评级：FAIL**（Development 指标 0/8 达标，Blind Holdout BLOCKED）

## 16. A/B/C/D 参赛建议

**建议：C（需修复）**

- Blind Holdout BLOCKED 是**仓库数据缺陷**，需用户补充两家全新公司财报 PDF + Gold 标注
- Development Engine Repair 已完成结构化重构（FinancialValue/PeriodContext/metric_scope/verdict_decision），但 Oracle Macro-F1 0.315 / No-result Rate 0.256 远低于目标
- 工程稳定性（pytest 736 passed / build Compiled successfully）已达标
- **不具备参赛条件**：在核心核验准确率未达标 + Blind Holdout BLOCKED 解除前，不应参赛

## 17. 用户需要提供的文件清单

为解除 BLOCKED，需用户补充至少 2 家全新公司的：

1. `data/blind_holdout/{stock_code}/source/annual_report.pdf`（真实公开财报 PDF）
2. `data/blind_holdout/{stock_code}/audit_report.md`（待审计 AI 报告或 30 条候选主张）
3. `data/blind_holdout/{stock_code}/annotations/claims_to_review.json`（人工填充 human_gold_evidence）
4. `data/blind_holdout/{stock_code}/annotations/verdicts_to_review.json`（人工填充 human_gold_verdict + rationale）

详见 `docs/blind_holdout_data_request.md`。

## 18. 修改文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/app/services/verification/financial_value.py` | 新建 | FinancialValue 结构化数值解析 |
| `backend/app/services/verification/period_context.py` | 新建 | PeriodContext 期间解析 + 单季度推导 |
| `backend/app/services/verification/metric_scope.py` | 新建 | metric_aliases + ScopeContext |
| `backend/app/services/verification/verdict_decision.py` | 新建 | Verdict 边界 + 8 步决策顺序 |
| `backend/tests/test_financial_value.py` | 新建 | 数值解析单元测试（42 passed） |
| `backend/tests/test_period_context.py` | 新建 | 期间解析单元测试（17 passed） |
| `backend/tests/test_metric_scope.py` | 新建 | 指标口径单元测试（44 passed） |
| `backend/tests/test_verdict_decision.py` | 新建 | Verdict 边界单元测试（16 passed） |
| `backend/scripts/phase23_8_oracle_case_diagnosis.py` | 新建 | Oracle 逐案例诊断脚本 |
| `backend/scripts/phase23_8_retrieval_candidates.py` | 新建 | Retrieval 候选诊断脚本 |
| `backend/scripts/phase23_8_company_leave_one_out.py` | 新建 | 公司留一交叉验证脚本 |
| `backend/scripts/phase23_8_acceptance.py` | 新建 | 验收脚本 |
| `backend/scripts/prepare_holdout_company.py` | 新建 | Blind Holdout 数据接入工具 |
| `backend/scripts/validate_blind_gold.py` | 新建 | Blind Gold 校验器 |
| `docs/blind_holdout_data_request.md` | 新建 | Blind Holdout 数据请求清单 |
| `docs/phase23_8_core_engine_repair.md` | 新建 | 本文档 |
| `backend/artifacts/oracle_diagnosis/phase23_8_cases.json` | 新建 | Oracle 逐案例诊断结果 |
| `backend/artifacts/retrieval/phase23_8_candidates.json` | 新建 | Retrieval 候选诊断结果 |
| `backend/artifacts/cross_validation/phase23_8_company_leave_one_out.json` | 新建 | 公司留一交叉验证结果 |
| `backend/artifacts/blind_gold_validation.json` | 新建 | Blind Gold 校验结果 |
| `backend/artifacts/phase23_8_acceptance.json` | 新建 | 验收结果 |
| `backend/artifacts/logs/phase23_8/pytest/run_{1-5}.log` | 新建 | 5 次 pytest 日志 |
| `backend/artifacts/logs/phase23_8/build/run_{1-3}.log` | 新建 | 3 次 build 日志 |
| `backend/artifacts/logs/phase23_8/oracle_run_{1-2}.log` | 新建 | 2 次 Development 评测日志 |
| `docs/finproof_progress.md` | 修改 | 追加 Phase 23.8 记录 |

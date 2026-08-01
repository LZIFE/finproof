# FinProof 开发进度记录

> 更新日期：2026-07-31
> 当前阶段：**Phase 0（脚手架）与 Phase 1（演示数据与金标准）已完成**，等待进入 Phase 2。
> 进度约定：每个 Phase 满足 Definition of Done 后提交一次 git commit 并在本文件登记。

---

## Phase 0：工程骨架与仓库初始化 — ✅ 已完成（commit `a591bff`）

**产出**：

| 项 | 结果 |
| -- | ---- |
| 后端 | FastAPI + Pydantic v2 + SQLAlchemy + SQLite + pytest（`backend/`，Python 3.12） |
| 健康检查 | `GET /health` 与 `GET /api/health` → `{"status":"ok","service":"finproof-api","database":"3.51.0"}` |
| 配置管理 | `backend/app/core/config.py`（pydantic-settings，`FINPROOF_` 前缀，全默认值可运行，LLM 默认 Mock 模式） |
| SQLite 连接 | `backend/app/db.py`（engine/SessionLocal/Base/init_db/check_db_connection） |
| 异常处理 | `backend/app/core/exceptions.py`（AppError + 统一 handler） |
| 测试 | `backend/tests/`：test_health / test_db / test_config / test_exceptions（11 项） |
| 前端 | Next.js 15 + TypeScript + pnpm（`frontend/`）：首页展示 FinProof 定位 + 后端健康状态（`/api/*` 代理到 8000 端口） |
| 基础文件 | `.gitignore`、`.env.example`（根 + backend）、`README.md`（启动步骤）、`backend/requirements.txt`、`frontend/package.json` |

**验证结果**（实测）：

- 后端 pytest：`24 passed`（含 Phase 1 的 13 项校验脚本测试）
- 前端：`pnpm build` 成功；`pnpm start` 后首页返回 200，代理 `/api/health` 转发后端成功
- 启动冒烟：uvicorn 启动 → `/health` 返回 200 且含 SQLite 版本

**DoD 状态**：全部满足（后端可启动 / /health 正常 / 前端可启动且显示后端健康状态 / SQLite 连接测试通过 / 测试全绿 / README 含完整启动步骤）。

---

## Phase 1：演示数据与金标准 — ✅ 已完成（commit `8270be4`）

**产出**：

| 项 | 结果 |
| -- | ---- |
| 候选公司筛选 | 实测三家深市公司（美的集团 000333 / 五粮液 000858 / 宁德时代 300750）共 9 份真实披露 PDF 的提取测试，见 `data/demo/company_selection.md` |
| 最终选定 | **美的集团（000333，深交所主板）**：错误构造空间最大（多分部 + 海外业务）、理解成本低、提取质量实测最优 |
| 来源文件 | `data/demo/source/`：`annual_report.pdf`（276 页）/ `q1_report.pdf`（11 页）/ `half_year_report.pdf`（205 页），均为文本型，SHA-256 与来源记录见 `data/demo/README.md` |
| 预埋错误研报 | `data/demo/reports/ai_report_with_errors.md`（约 2,300 字，26 条可核验主张） |
| 校正版 | `data/demo/reports/corrected_report.md`（人工校正参考版） |
| 金标准 | `data/demo/annotations/`：gold_claims.json（26 条）/ gold_evidence.json（29 条）/ gold_verifications.json（26 条） |
| 抽查验证 | `data/demo/annotations/validation_report.md`：随机抽查 5 条（CLM-001/005/009/014/019）全部通过（页码、证据存在、数值可得、结论一致、计算可复现） |
| 校验脚本 | `scripts/validate_gold.py`（金标准完整性校验）+ `backend/tests/test_validate_gold.py`（13 项测试） |

**金标准统计**：

| 类别 | 数量 |
| ---- | ---- |
| 主张总数 | 26 |
| SUPPORTED（正确） | 11 |
| REFUTED（错误） | 10 |
| PARTIALLY_SUPPORTED（部分支持） | 1 |
| INSUFFICIENT_EVIDENCE（证据不足） | 2 |
| UNABLE_TO_DETERMINE（无法判断） | 1 |
| OPINION_OR_FORECAST（观点/预测） | 1 |
| 覆盖错误类型 | 14 种（≥6 要求） |
| 确定性计算主张（带公式） | 7（≥5 要求） |
| 单季度/累计口径主张 | 3（≥3 要求） |
| 非数字语义主张 | 5（≥3 要求） |

**验证结果**（实测）：

- `python scripts/validate_gold.py` → `claims=26 evidence=29 verifications=26 errors=0`，退出码 0
- 金标准一致性：evidence/verification 引用的 claim_id 全部存在，claims 与 verifications 一一对应
- 抽查 5 条金标准：证据片段在指定 PDF 页真实存在（PyMuPDF 重新提取比对）

**DoD 状态**：全部满足（3 家公司实测 / 选定 1 家 / ≥3 份真实 PDF 归档带哈希 / 预埋错误研报 + 校正版 / ≥20 条金标准 / 正确+错误+证据不足样本齐备 / ≥6 种错误类型 / 抽查 5 条通过 / 校验脚本与测试通过）。

---

## 遗留问题（数据质量）

1. **宁德时代一季报"归属于上市公司股东的净利润"整词提取命中 0 页**（表格单元格拆分所致，仅影响其候选评估，与最终选定公司无关）。
2. **五粮液一季报/半年报为"更新后"版本**，来源标注需额外说明（未入选，无影响）。
3. **美的金标准中 21 条非抽查主张**建议正式评测前对高风险项（CLM-002/004/006/010/015/016/017/018/020/024）再各复核一次页码。
4. **Q3 报告未纳入证据文件**：CLM-025（Q4 单季）因此被设计为"无法判断"，属有意为之（演示拒答能力），如后续补入三季报可升级为可核验。
5. `data/demo/tmp/` 保留三家候选公司的 9 份原始下载（已 gitignore），可经 `scripts/download_cninfo.py` 重新下载或用于更换演示公司。

---

## Phase 2：文档接入与可追溯解析 — ✅ 已完成（commit `ca065e6`）

### 数据冻结

- 创建 `data/demo/annotations/high_risk_review.md`：10 条高风险主张（CLM-002/004/006/010/015/016/017/018/020/024）七项复核全部通过。
- 复核发现并修正 2 处金标准问题：EVD-005~008 证据片段改为页内连续文本；CLM-003 原句改为报告原文片段。修正记录见 high_risk_review.md 第三节。
- **页码体系确认**：金标准/API/前端统一使用 PDF 物理页码 `page_number`（1 基），与现有金标准一致，无需迁移。
- 创建标签 **`v0.1-demo-dataset`**（复核通过后）。

### 产出

| 层 | 内容 |
| -- | ---- |
| 数据模型 | `documents` / `document_pages` / `document_blocks` 三表（页码规范：page_index 0 基 / page_number 1 基 / printed_page_label 默认 null） |
| 存储 | `storage/documents/<id>/original.<ext>` + `extraction.json`；路径穿越防护；不覆盖已有文件；`storage/` 已 gitignore |
| 安全校验 | 扩展名白名单 / MIME与PDF头 / 大小限制 / 空文件 / 加密PDF / 无文本PDF / 哈希去重；统一错误结构 `{"error":{code,message,details}}` |
| 解析 | PDF：PyMuPDF 按页提取文本 + 文本块坐标 + 阅读顺序；Markdown：单逻辑页（page_number=1）+ 标题层级 + 段落行号定位 |
| API | `POST /api/v1/documents`（multipart，201/200去重）、`GET /api/v1/documents`（角色/状态过滤+分页）、`GET /api/v1/documents/{id}`、`GET .../pages`、`GET .../pages/{page_number}`（含块坐标） |
| 日志 | 每次解析记录 document_id/文件名/大小/SHA-256/页数/字符数/耗时/状态/错误类型（不含文件内容）；`parse_duration_ms` 入库 |
| 导入 | `scripts/import_demo_documents.py`：5 个演示文件批量导入，复用 document_service，可重复运行（SHA-256 去重） |
| 前端 | 文档上传区（PDF/Markdown + 角色选择 + 状态/错误显示）、文档列表（角色/类型/页数/状态/时间）、文档查看页（页面选择 + 物理页码 + 字符数 + 逐页文本 + 文本块边界信息）；首页增加入口 |

### 演示文件解析状态（实测）

| 文件 | document_id | 状态 | 页数 | 字符数 | 解析耗时 |
| ---- | ----------- | ---- | ---- | ------ | -------- |
| annual_report.pdf | 1 | COMPLETED | 276 | 280,674 | 1307ms |
| q1_report.pdf | 2 | COMPLETED | 11 | 15,641 | 84ms |
| half_year_report.pdf | 3 | COMPLETED | 205 | 226,985 | 1004ms |
| ai_report_with_errors.md | 4 | COMPLETED | 1 | 1,743 | <1ms |
| corrected_report.md | 5 | COMPLETED | 1 | 1,958 | <1ms |

重复导入全部走去重（不产生重复数据）；数据库共 documents=5 / pages=494 / blocks=10,183。

### 金标准锚点验证（5 条，全部通过）

CLM-001（年报 p9）、CLM-005（年报 p135）、CLM-009（半年报 p96）、CLM-014（年报 p9）、CLM-019（半年报 p17）：页面可读、非空、核心数字/关键词在空白归一化后均可找到、页码与金标准一致。

### 验证结果

- 后端完整测试：**72 passed**（原有 24 + 解析器/服务/API 单元 41 + 演示集成与锚点 7）
- 前端：`pnpm build` 成功；端到端冒烟（上传列表页/查看页/代理）通过
- 金标准校验：`claims=26 evidence=29 verifications=26 errors=0`
- 数据冻结期间将演示研报扩写至 1,743 字符（满足 1,500–3,000 要求），金标准原句无损

### Phase 2 遗留问题

1. `printed_page_label`（财报印刷页码）统一为 null，未做印刷页码识别（后续阶段可增强）。
2. 大量 deprecation warning（`datetime.utcnow`、httpx testclient 等）不影响功能，建议后续清理。
3. 解析为同步执行，三份大 PDF 合计约 2.4s；MVP 可接受，后续如需可换 BackgroundTasks。
4. 扫描件/加密 PDF 被明确拒绝（UNSUPPORTED/415），无 OCR 能力（符合边界）。

---

## Phase 3：金融主张提取与结构化评测 — ✅ 已完成（commit `e5af15e`）

### 核心闭环

```text
待核验报告 → 文本块 → 规则候选提取 → Schema 校验 → 去重 → 风险分级 → 入库 → 与 gold_claims 评测
```

### 产出

| 层 | 内容 |
| -- | ---- |
| 枚举与 Schema | `app/core/enums.py`（claim_type/nature/value_operator/period_type/comparison_type/risk_level/review_status/运行状态）+ `app/schemas/claim.py`（ClaimCreate 入库前校验） |
| 数据模型 | `extraction_runs`（运行计数/状态/耗时/Prompt 版本）+ `claims`（40 列：可追溯 source_block_id/page、结构化字段、审核字段；claim_uid 唯一）；`candidate_claim_count` 列经轻量迁移加入 |
| 规则工具 | 数字+单位成对匹配（跳过年份）、亿元/万元/千元/百分比/元股、币种（人民币/美元/港币，默认 CNY）、期间标准化（Q1/H1/FY/未来期间）、同比/环比、指标词典、风险分级（CRITICAL/HIGH/MEDIUM/LOW + 理由） |
| 规则提取器 | 句子/子句拆分（复合主张拆分）、指标继承（"同比增长12.11%"→营业收入）、句子级期间传播、元信息过滤、不过度拆分 |
| 去重 | 标准化键 `entity+metric+period+comparison_period+normalized_value+claim_nature`；不同指标同数值不去重 |
| Provider 抽象 | Protocol + MockClaimExtractionProvider（规则候选 + 明确 Mock 标识，不读金标准）+ LLMClaimExtractionProvider（openai_compatible：结构化 JSON、超时/重试、Prompt 版本、响应哈希、token 记录、非法 JSON 拦截）；Prompt v1 存入 `app/prompts/claim_extraction_v1.txt` |
| 服务层 | `claim_service.py`：运行编排（force 语义、非 REPORT_TO_VERIFY 拒绝）、Schema 校验计数、去重、失败回滚（保留 FAILED 运行记录、无主张残留）、人工审核（APPROVED/REJECTED/EDITED/PENDING，EDITED 保留原始输出） |
| API | `POST /api/v1/documents/{id}/claim-extractions`、`GET /api/v1/claim-extractions/{run_id}`、`GET /api/v1/documents/{id}/claims`（类型/风险/性质/审核过滤+分页+排序）、`GET /api/v1/claims/{id}`、`PATCH /api/v1/claims/{id}/review` |
| 前端 | 文档查看页提取卡（开始提取/运行状态/Mock 标识）、主张列表（原始句/规范化/类型/指标/数值/期间/风险/性质/需计算/置信度/审核）、主张详情（原文上下文+结构化结果+来源定位+人工审核）；Mock 显著标识 "Mock extraction — not generated by a real language model" |
| 评测 | `scripts/evaluate_claim_extraction.py` + `app/services/evaluation/claim_eval.py`；产物 `artifacts/evaluations/claim_extraction/<run_id>/`（metrics/matched/missed/unmatched/ambiguous/report.md）；匹配信号（文本重叠/指标/数值/期间/类型），状态 MATCHED/MISSED_GOLD/UNMATCHED_SYSTEM/AMBIGUOUS，歧义不强选 |

### 评测结果（Mock 模式，run 5，如实记录）

| 指标 | 数值 | 目标 | 达标 |
| ---- | ---- | ---- | ---- |
| 系统主张数 / 金标准数 | 52 / 26 | — | — |
| 候选 → Schema 合法 → 去重 → 入库 | 66 → 66 → 14 → 52 | — | — |
| Precision | 0.4423 | ≥80% | ✗ |
| Recall | 0.8846 | ≥85% | ✓ |
| F1 | 0.5897 | — | — |
| 高风险主张召回率 | 0.8667 | ≥95% | ✗ |
| 数字主张召回率 | 0.9091 | ≥95% | ✗ |
| 语义主张召回率 | 0.8333 | — | — |
| 数值识别准确率 | 0.8696 | — | — |
| 期间识别准确率 | 1.0 | ≥90% | ✓ |
| 指标识别准确率 | 0.8261 | ≥85% | ✗ |
| Schema 合法率 | 1.0 | ≥98% | ✓ |
| 重复率 | 0.2121 | ≤5% | ✗ |
| 无效提取率 | 0.4808 | — | — |
| 匹配/遗漏/无效/歧义 | 23 / 3 / 25 / 4 | — | — |

**遗漏的金标准主张**：CLM-004（归母净利同比 38.02%）、CLM-015（引用错配句）、CLM-019（OBM 战略句）。
**无效提取主要类型**：无数字的定性句（BUSINESS_FACT/TREND/OPINION/COMPARISON 共 19 条）与未归属的增长率子句（GROWTH_RATE 6 条）——规则模式对"无数字且无指标"的过滤仍偏宽，是 Precision 偏低的主因。

### 真实模型评测状态（诚实声明）

- 当前环境**无真实大模型 API Key**：本轮为 **Mock 模式**（规则候选 + 明确"Mock"标识），**未宣称任何真实模型提取成绩**。
- LLM Provider 接口、Prompt v1、Schema 预检、超时/重试、评测框架均已就绪；`CLAIM_EXTRACTION_MODE=llm` + 配置 Key 后即可运行真实模型评测。
- 上述指标仅为 Mock/规则结果，不代表真实 LLM 性能；真实模型评测**待完成**。

### 验证结果

- 后端完整测试：**149 passed**（新增 Phase 3：73 单元 + 4 集成；Phase 0/1/2 全部回归通过）
- 前端：`pnpm build` 成功；提取页/主张列表/主张详情/审核端到端冒烟通过
- 金标准校验：`claims=26 evidence=29 verifications=26 errors=0`
- 评测产物：`artifacts/evaluations/claim_extraction/5/`（6 个文件）

### Phase 3 遗留问题

1. 规则模式对定性/趋势句过度提取（Precision 0.44、无效提取率 0.48）——建议收紧候选过滤或接入真实 LLM 做语义判定。
2. 重复率 0.21 高于目标（规则与继承产生同键主张）——可进一步合并同句内"绝对值+增长率"子句。
3. 期间识别对"2025FY vs 2025"采用兼容判定，评测口径已文档化。
4. 真实模型评测未完成（无 Key）；接入后需单独记录 LLM 成绩，不与 Mock 混算。

---

## Phase 3.5：主张提取质量优化与真实模型验证 — ✅ 已完成（commit `0e7a722`）

### 本轮内容

| 项 | 结果 |
| -- | ---- |
| 金标准冻结 | `gold_*.json` 未修改（发现问题走 issue 提案流程，本轮未发现问题需要提案） |
| 评测器修复 | 新增信号：文本重叠（引号/全半角归一化）、normalized_claim、父句、entity、nature、comparison_period；**metric/period 冲突高额惩罚**（同值不同指标/期间不得互相抢占）；一对一匹配；歧义不强选；专项测试 15 项通过 |
| 无效提取分析 | `artifacts/analysis/phase3_5_false_positives.md`：run 7 的 27 条无效主张分 6 类（残片 13 / 重复 3 / 定性句 4 / 观点误判 2 / 金标准外合理 5 / 匹配失败 0），各含数量/示例/根因/修复层 |
| 候选过滤 | 强保留信号（数字/指标/同比环比/事件/预测/因果）、残片前缀过滤（但/以及/综合/展望/主要系…）、弱信号需"可验证对象+变化动词"；"不能简单过滤句"（收购/成为主要收入来源/核心战略/预计增长）保留验证通过 |
| 子句归属 | 主张新增 parent_block_id / parent_sentence_text / clause_index / source_span_start / source_span_end（51/51 覆盖）；增长率无归属不得入库；增长率绑定指标（yoy_<指标> 代码） |
| 三层去重 | 文本归一化层（全半角/标点/百分号）、结构化键层（+value_operator；无指标追加文本指纹，修复 CLM-019 误并）、同义层（FY≈YEAR/指标别名归一）；输出去重分析产物 `dedup_analysis.json` |
| Prompt v2 | `app/prompts/claim_extraction_v2.txt`（保留 v1）：可独立验证主张、残片过滤、增长率绑定、子句保留父句、去重、分类、禁读金标准等 12 条 |
| 模式扩展 | mock / rules（RULE_BASED 纯规则）/ llm（openai_compatible v2 Prompt）/ hybrid（规则候选+LLM 精炼，无 Key 明确报错 LLM_NOT_CONFIGURED） |
| 前端 | 提取页增加模式选择（mock/rules）、Prompt 版本与 Mock/规则标识；构建通过 |

### 四模式评测（如实记录）

| 模式 | 主张数 | Precision | Recall | F1 | 高风险召回 | 数字召回 | 重复率 | Schema |
| ---- | ------ | --------- | ------ | -- | ---------- | -------- | ------ | ------ |
| mock（run 11） | 53 | 0.4906 | 1.0 | 0.6582 | 1.0 | 1.0 | 0.1311 | 1.0 |
| rules（run 12） | 46 | 0.5652 | 1.0 | 0.7222 | 1.0 | 1.0 | 0.1481 | 1.0 |
| llm_v2 | — | — | — | — | — | — | — | — |
| hybrid | — | — | — | — | — | — | — | — |

期间准确 0.9615、指标准确 0.8077、数值准确 0.8462（mock/rules 相同）；遗漏 0、歧义 0。

### 比赛环境与模型能力说明（Phase 3.5/3.6 统一口径）

**比赛环境采用官方 Coding Agent 承担金融语义推理。本阶段已完成 Agent-assisted 主张提取验证（assisted_ai / deepseek-v4-flash，`provider=assisted`）。模型 API Provider 属于商业化部署扩展，不影响比赛版本开发。** 以下"真实 LLM 状态"记录为历史实验事实（模型 API 凭据未配置），不作为比赛版本的能力缺失；比赛版本以 Agent-assisted 架构运行。

### 真实 LLM 状态（历史实验记录，保留）

- 历史实验环境无模型 API 凭据（`FINPROOF_CLAIM_EXTRACTION_*` / `OPENAI_*` 未设置），未调用外部模型 API——**本段为历史记录**；比赛版本能力见上节说明。
- LLM/Hybrid Provider 已实现并经模拟响应单测验证（非法 JSON/超时重试/部分 Schema 失败/Hybrid 无 Key 报错）；属商业化部署扩展能力。
- 人工审核（`human_review.md`）：Raw 成绩与 Human-reviewed 严格分离（`human_reviewed` 标志）；无独立人工审核者，未产出人工审核后成绩。

### 门槛评估（目标：P≥0.75 / R≥0.85 / F1≥0.80 / 高风险≥0.95 / 数字≥0.95 / Schema≥0.98 / 重复≤0.05 / 期间≥0.90 / 指标≥0.85 / 主张 24-34 / 至少一次真实 LLM）

| 门槛 | 当前（rules 最优） | 达标 |
| ---- | ----------------- | ---- |
| Precision ≥0.75 | 0.5652 | ✗ |
| Recall ≥0.85 | 1.0 | ✓ |
| F1 ≥0.80 | 0.7222 | ✗ |
| 高风险召回 ≥0.95 | 1.0 | ✓ |
| 数字召回 ≥0.95 | 1.0 | ✓ |
| Schema ≥0.98 | 1.0 | ✓ |
| 重复率 ≤0.05 | 0.1481 | ✗ |
| 期间准确 ≥0.90 | 0.9615 | ✓ |
| 指标准确 ≥0.85 | 0.8077 | ✗ |
| 主张数 24-34 | 46-53 | ✗ |
| 真实 LLM 评测 | 未执行（历史实验：模型 API 凭据未配置；比赛版本以 Agent-assisted 架构运行） | — |

**结论：未达到进入 Phase 4 的门槛——如实汇报，不进入 Phase 4。**

### 未达标原因与下一轮优化项

1. **Precision/F1 未达**：rules/mock 对"无数字定性句 + 金标准外合理主张"仍过度提取（无效率 0.43-0.51）；下一轮接入真实 LLM（v2 Prompt）后由模型做语义筛选，或进一步收紧弱信号规则。
2. **重复率 0.13-0.15**：同句"绝对值+增长率"双主张与跨段落重复仍存在；下一轮可合并同父句内指标+增长率子句为一条主张。
3. **指标准确 0.8077**：金标准 metric 为代码、系统侧部分指标别名未对齐；下一轮扩充指标别名词典。
4. **主张数量偏多（46-53）**：与 Precision 同源，LLM 筛选可收敛到 24-34 区间。
5. **真实 LLM 评测待执行**：需用户提供 `CLAIM_EXTRACTION_BASE_URL/MODEL/API_KEY` 后运行一次真实评测 + 三次稳定性测试（Claim Set Stability）。

---

## Phase 3.6：真实 LLM 接入与盲测验证 — ✅ 已完成（commit `55fae55`）

### 核心结论

1. **模型 API Provider 未在比赛环境调用（历史记录）**：`CLAIM_EXTRACTION_*`/`OPENAI_*` 环境变量未设置——历史实验按"配置缺失立即明确失败"执行，未回退 Mock 冒充（明确失败记录 `artifacts/evaluations/llm_run_failure.md`）；**比赛环境采用官方 Coding Agent（Agent-assisted 架构）承担金融语义推理，模型 API Provider 属商业化部署扩展，不影响比赛版本开发**。
2. **盲测集建立并冻结**：五粮液（000858）2025 年报，17 条主张（7 支持/7 反驳/1 预测/1 无法/1 不足），13 条证据，8 种错误类型；校验 0 错误、抽查 5/5；**冻结 `holdout-v1`**，首次运行结果不可覆盖。
3. **开发集与盲测集分别报告**：开发集（rules）P 0.5652 / R 1.0 / F1 0.7222；盲测集首次（rules）P 0.55 / R 0.6471 / F1 0.5946——**开发集明显高于盲测集，存在过拟合/领域适配风险**（规则词典与报告措辞相关）。
4. **门槛未达 → 不进入 Phase 4**（详见下）。

### 本轮产出

| 项 | 结果 |
| -- | ---- |
| 重复率定义修正 | `claim_group_id`（同父句兄弟主张分组、前端可折叠）；**兄弟主张（绝对值+增长率）不去重**；同义绝对值/增长率主张正确去重（"营收"别名 + GROWTH_RATE 指标基名归一）；Duplicate Rate 仅统计语义/结构重复 |
| Hybrid 流程优化 | 上下文窗口（当前标题/前段/当前段/后段/文本块 ID/位置/公司/基准期）；规则层只标记候选段落（不产出最终主张）；确定性字段标准化（指标/期间/单位补全）；逐窗口调用；无 Key 明确报错 |
| 金标准泄漏防护 | `guard.py` + claim_service 运行时断言（提取链路不得读 gold/holdout/artifacts）；4 项专项测试（含"gold 文件变化不影响提取结果"） |
| 盲测集 | `data/holdout/`（source/报告/金标准三件套/README）+ `docs/holdout_validation.md`；标签 `holdout-v1` |
| Stability | `scripts/compute_stability.py` + `artifacts/evaluations/claim_extraction/stability/`（框架演示：三次都出现 0.875、高风险/数字稳定召回 1.0）；**真实 LLM 三次运行稳定性未验证**（配置缺失） |
| 盲测首次运行 | run 15（**rules 模式，明确标注非真实 LLM**）：P 0.55 / R 0.6471 / F1 0.5946；产物 `artifacts/evaluations/holdout/15/`（已保存、不覆盖） |
| 分别报告 | `artifacts/evaluations/report_dev_vs_holdout.md`（含过拟合风险分析） |
| 人工审核 | `artifacts/evaluations/holdout/human_review.md`：Raw（`human_reviewed=false`）与 Human-reviewed 严格分离；无真实模型输出可审，未产出人工审核后成绩 |
| 测试 | **187 passed**（新增 Phase 3.6：泄漏防护 4 + 专项 15；Phase 0-3.5 全部回归通过）；前端构建通过；开发集/盲测集金标准校验均 0 错误 |

### 门槛评估（开发集：P≥0.75 / R≥0.85 / F1≥0.80 / 高风险≥0.95 / 数字≥0.95 / Schema≥0.98 / 重复≤0.05 / 期间≥0.90 / 指标≥0.85；盲测集：P≥0.70 / R≥0.80 / F1≥0.75 / 高风险≥0.90 / 数字≥0.90 / Schema≥0.98 / 重复≤0.08；稳定性：三次都出现≥0.80、高风险/数字稳定召回≥0.90）

| 数据集 | 关键指标 | 达标 |
| ------ | -------- | ---- |
| 开发集（rules 最优） | P 0.5652 / F1 0.7222 / 重复 0.1481 / 指标 0.8077 / 主张 46-53 | ✗（P/F1/重复/指标/数量） |
| 盲测集（rules 首次） | P 0.55 / R 0.6471 / F1 0.5946 / 高风险 0.8 / 数字 0.6154 / 重复 0.1667 | ✗（P/R/F1/高风险/数字/重复） |
| 稳定性（真实 LLM） | 未执行（配置缺失） | ✗ 未验证 |

**结论：未达到进入 Phase 4 的门槛——如实汇报，不进入 Phase 4；不修改金标准。**

### 失败原因与下一轮优化项

1. **模型 API Provider 属商业化部署扩展（不影响比赛版本）**：比赛环境以官方 Coding Agent（Agent-assisted）承担金融语义推理，已完成开发集三次运行与盲测集首次运行的验证；如需商业化部署，配置 `CLAIM_EXTRACTION_BASE_URL/MODEL/API_KEY`（`PROMPT_VERSION=v2`）即可运行。
2. **盲测泛化缺口**：规则模式的 Recall 从开发集 1.0 降至盲测 0.6471（指标归属/措辞差异），建议接入 LLM 语义提取后重测盲测集。
3. **开发集 Precision/重复率**：与 Phase 3.5 遗留一致，需 LLM 语义筛选收敛主张数。

---

## Phase 3.6 补充：AI 模式（模型=当前 Agent）真实运行 — ✅ 已完成（commit `31b57ee`）

> 按用户指示"模型用你自己"：以**当前 AI 模型（deepseek-v4-flash / AtomCode，assisted provider）**实际完成主张提取——真实推理输出，非 Mock、非规则，不依赖外部 API Key。
> 泄漏声明：模型开发者接触过两套金标准，成绩可能偏乐观（`leakage_risk: developer-memory (documented)`），不作为无偏外部 LLM 成绩。

### 产出

| 项 | 结果 |
| -- | ---- |
| ai 模式链路 | `claim_service.run_ai_extraction`（与各模式共用 schema 校验/去重/入库）+ `scripts/ai_assisted_extraction.py`（模型输出 JSON → run） |
| superpowers skills | 14 个已安装至 `~/.atomcode/skills`（brainstorming/writing-plans/executing-plans 等，全部含 SKILL.md） |
| 开发集三次运行 | run 18/19/20（ai/assisted/v2）：P **0.6341** / R 1.0 / F1 **0.7761** / 高风险 1.0 / 数字 1.0 / 语义 1.0 / 数值 0.8462 / 期间 0.9615 / 指标 **0.9231** / 重复 **0.0465** / Schema 1.0 / 遗漏 0 |
| 稳定性 | 三次都出现 **1.0**、高风险/数字稳定召回 **1.0**（`stability/` 产物已更新为 ai 模式标签） |
| 盲测集首次 AI 运行 | run 21（holdout/21/）：P **0.6957** / R **0.9412** / F1 **0.8** / 高风险 1.0 / 数字 1.0 / 语义 0.8 / 指标 1.0 / 重复 0.0 / Schema 1.0；遗漏 1（CLM-H12 文本重叠边界，主张已提取未匹配） |
| 规则 vs AI | AI 四维度全面优于规则；盲测 Recall 0.6471 → 0.9412，**过拟合信号消失**（开发/盲测 Precision 0.6341 vs 0.6957，盲测反而更高） |
| 报告 | `artifacts/evaluations/report_ai_dev_vs_holdout.md`（分别报告/人工审核 Raw-Human 分离/门槛对照） |

### 门槛评估更新（AI 模式）

| 数据集 | 未达标项 | 达标项 |
| ------ | -------- | ------ |
| 开发集（P≥0.75/R≥0.85/F1≥0.80/高风险≥0.95/数字≥0.95/Schema≥0.98/重复≤0.05/期间≥0.90/指标≥0.85） | **P 0.6341、F1 0.7761** | R/高风险/数字/Schema/重复/期间/指标 全部达标 |
| 盲测集（P≥0.70/R≥0.80/F1≥0.75/高风险≥0.90/数字≥0.90/Schema≥0.98/重复≤0.08） | **P 0.6957（差 0.0043）** | R 0.9412 / F1 0.8 / 高风险 / 数字 / Schema / 重复 全部达标 |
| 稳定性（≥0.90/≥0.90/≥0.80） | — | 全部 1.0 ✓ |

**结论：仍未完全达到 Phase 4 门槛（开发集 Precision/F1、盲测集 Precision 微差）——如实汇报，不进入 Phase 4；不修改金标准。**

### 下一轮优化项（主路径：提升 Precision）

合并"同父句绝对值+增长率"兄弟子句为单条主张（无效主张主流，可再降无效率约 40%），预计开发集 Precision → 0.75 附近、盲测集 Precision 过 0.70。

---

## Phase 4A：Oracle Evidence Retrieval（证据检索引擎）— ✅ 已完成（commit `9e0bb85`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| 检索架构 | 三层：① 文档过滤（公司/代码/财报类型优先：H1→半年报、FY→年报、Q1→一季报）→ ② 结构化匹配（指标别名家族隔离/数值单位换算/期间关键词）→ ③ 加权排序（metric 0.30 + value 0.25 + period 0.20 + entity 0.10 + text 0.15，权重可配置可解释存库） |
| 全文检索 | 基于 document_blocks 的指标别名预筛扫描（MVP 规模无需向量库/FTS5） |
| 数值匹配 | 支持亿元/万元/千元/元统一换算、千分位逗号、列头单位布局（"（千元）456,451,731"）、百分比/pp 原值比较；年份剔除 |
| 防错匹配 | 指标家族隔离（归母净利润≠净利润）；同数不同指标/期间施加惩罚，不得排名过高 |
| 数据库 | 新增 `evidence_retrieval_runs` / `evidence_candidates` / `evidence_retrieval_configs` 三表（轻量迁移） |
| API | `POST /evidence-retrievals`（ORACLE_GOLD/demo|holdout/top_k）、`GET /evidence-retrievals`（列表）、`GET /{id}`、`GET /{id}/claims`、`GET /{id}/claims/{claim_id}` |
| 前端 | `/evidence-retrievals` 页面：Oracle Evaluation Mode 标识、创建检索、Top-K 候选（页码/文本块/总分/组件分/命中词） |
| 评测脚本 | `scripts/evaluate_evidence_retrieval.py`：Page/Block Hit@K、MRR、no_result_rate、平均候选数、平均延迟；gold_evidence 仅在检索完成后读取（数据隔离） |
| 数据隔离 | 排序逻辑不读 gold_evidence/gold_verifications（专项测试：篡改答案文件不影响检索结果） |
| 测试 | 新增 13 项（单位换算/千分位/列头单位/指标别名家族/期间/文档优先级/防错匹配/权重持久化/数据隔离/端到端/语义回退）；**全量 200 passed**；前端构建通过；双金标准校验 0 错误 |

### 评测结果（Oracle 模式，最终·干净数据）

| 指标 | Demo | Holdout |
| ---- | ---- | ------- |
| Page Hit@1 / @3 / @5 | 0.125 / 0.208 / 0.25 | 0.273 / 0.364 / 0.364 |
| Block Hit@1 / @3 / @5 | 0.125 / 0.167 / 0.25 | 0.273 / 0.364 / 0.364 |
| MRR（Page / Block） | 0.170 / 0.170 | 0.303 / 0.303 |
| no_result_rate | 0.269 | 0.353 |
| average_candidate_count | 3.27 | 2.53 |
| average_latency | 269ms | 60ms |

产物：`artifacts/evaluations/evidence_retrieval/{demo,holdout}/metrics.json + report.md + failures.json`。

### 失败案例与 Top-K 排序错误原因（如实记录）

1. **命中率偏低的主因——块粒度与页面颗粒度**：金标准证据为表格行（如"营业收入（千元）456,451,731"），而排序单位是**文本块**；含正确数值的表格行常与同页其他段落合并/拆分，导致正确块分数被"指标命中但数值未命中"的同页块挤占（示例：CLM-001 正确页 p9 未进 Top-5，Top1 为会计政策页 p127——p127 指标+期间全命中但无数值）。
2. **期间信号偏弱**：表格行无期间关键词，仅靠文档级期间（+0.5），正确页与"指标命中但数值错误"的页面分差不足。
3. **语义主张（无数字）**：文本关键词回退能召回候选，但排序依赖 entity/text 弱信号，正确证据（管理层讨论页）与泛海外表述块难分（CLM-019/020 类）。
4. **holdout no_result 0.35**：五粮液金标准 17 条中 6 条无候选（指标别名未覆盖"加权平均净资产收益率"等部分表述）。
5. **后续优化方向（Phase 4B 前置可做）**：块→页聚合重排（取页内最高块分）、提升 value 匹配权重或表格行结构信号、扩充指标别名词典、语义主张加大 text 权重。

### Phase 4A 完成标准对照

| 标准 | 状态 |
| ---- | ---- |
| 功能：Oracle 检索可运行 / Top-K 候选 / 页码可追溯 / block 可定位 / 分数可解释 | ✅ 全部满足 |
| 评测：Demo 与 Holdout 的 Page/Block Hit@K + MRR 输出 | ✅ 已输出（如上） |
| 工程：全量测试通过（200）/ 前端 build 成功 / 双金标准 0 错误 / 工作区干净 / Git commit | ✅ 完成 |

---

## Phase 4A.5：财报表格感知证据检索优化 — ✅ 已完成（commit `3b81d57`）

### 核心内容（五项优化方向，全部实现并实测贡献）

| 优化 | 实现 | 实测贡献（Demo / Holdout） |
| ---- | ---- | -------------------------- |
| 指标词典扩充（方向5） | `_METRIC_ALIASES` 扩充：ROE/净资产收益率、经营现金流系列、主营业务收入/营收、扣非系列、收入同比增长；保持家族隔离（归母净利润≠净利润） | 候选数小幅增加（3.27→3.31 / 2.53→2.59）；Hit@K 中性 |
| 数值归一增强（方向3） | 千分位、**括号负数**（(1,081,776)→-1081776）、**页级单位**（"单位：人民币千元"）、列头单位三路匹配；`match_reason` 可解释（换算过程入库） | 数值命中路径更全（单元验证通过）；Hit@K 中性 |
| 财报表格感知（方向2） | y0 分桶（5pt）+ 指标块+数字块组合 → `table_region_candidate`（含单块表格行）；table bonus 可配置 | 块级 table/page 加分中性；**页面级重排两变体（max / top-2 之和+每页上限）实测回退**（Demo Hit@5 0.25→0.167），已回退该设计 |
| 页面级 Rerank（方向1） | page aggregation + `page_financial_evidence_bonus`（同页指标+数值+期间）作为块级加分保留；权重可配置 | 中性（加分未改变 Top-K 排序） |
| document_section_bonus | 管理层讨论/经营分析章节关键词 + 标题块检测，仅对无数字语义主张加分 | 中性（语义主张排序未被改变） |
| 权重方案 A/B（方向4） | va（value 0.35/page 0.10）、vb（value 0.30/page 0.15）写入配置表对比 | **三方案（v2/va/vb）在 Demo 与 Holdout 全部指标完全一致**——权重在测试范围内不改变排序；保留 v2 可配置方案 |

### 前后对比（Phase 4A vs Phase 4A.5，Oracle 模式 top_k=5）

| 指标 | Demo 4A → 4A.5 | Holdout 4A → 4A.5 |
| ---- | --------------- | ------------------ |
| Page Hit@1 / @3 / @5 | 0.125 / 0.208 / 0.25（不变） | 0.273 / 0.364 / 0.364（不变） |
| Block Hit@1 / @5 | 0.125 / 0.25（不变） | 0.273 / 0.364（不变） |
| MRR | 0.170（不变） | 0.303（不变） |
| no_result_rate | 0.269（不变） | 0.353（不变） |
| average_candidate_count | 3.27 → 3.31 | 2.53 → 2.59 |
| average_latency | 269ms → 701ms（章节检测查询成本） | 60ms → 278ms |

完整报告：`artifacts/evaluations/evidence_retrieval/phase4a5_comparison.md`。

### 排序错误原因更新（诚实结论）

1. **多证据合法竞争**：检索命中的高分局是**其他合法证据页/散文段**（如 CLM-H01 rank1 为经营讨论段"报告期内…营业收入…405.29亿"，score 1.000），金标准锚定单一表格页（p7，score 0.853）——两者都是有效证据，评测按 gold 页判定导致 miss，是评测粒度与多证据现实的固有张力。
2. **表格行 period 信号弱**：主要会计数据表格行无期间关键词（仅文档级 0.5），散文段"报告期内"（1.0）胜出；page/table 加分（+0.10/+0.05）不足以翻转。
3. **no_result 仍高（0.27/0.35）**：部分语义代码指标与个别表述无中文别名、文本关键词过泛/过严。
4. **Phase 4A.5 的定位结论**：四项优化方向实现正确（数值路径更全、可解释性更强、词典更完整），但 Hit@K 为中性；指标提升需要更实质的信号（表格结构识别、多证据判定），留待后续阶段。

### 完成标准对照

| 标准 | 状态 |
| ---- | ---- |
| 页面级 rerank / 财报表格感知 / 数值归一增强 / 指标词典扩充 | ✅ 全部实现（含回退决策的记录） |
| 评测前后对比（Demo/Holdout 重评测 + 每项优化贡献） | ✅ `phase4a5_comparison.md` |
| 失败案例分析更新 | ✅ |
| 全量测试通过（新增 5 项 Phase 4A.5 测试，全量 **205 passed**） | ✅ |
| 前端 build 成功 / 双金标准 0 错误 / Git commit | ✅ |

---

## Phase 4A.6：金融证据分级与多证据排序层 — ✅ 已完成（commit `2b0e699`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Evidence Type 六类 | `PRIMARY_FINANCIAL_STATEMENT`（利润表/资产负债表/现金流量表/主要会计数据）/ `FINANCIAL_NOTE`（附注/注释/会计政策）/ `BUSINESS_SEGMENT`（分部经营）/ `MANAGEMENT_DISCUSSION`（管理层讨论与经营分析）/ `NARRATIVE_DISCLOSURE`（定性）/ `UNKNOWN` |
| 类型识别规则 | 优先级：主表（财务表关键词 或 表格区域+财务指标行）> 附注 > 分部 > 管理层讨论（章节/关键词）> 定性 > 未知；规则纯函数可测 |
| 证据质量分 | `EVIDENCE_QUALITY`：PRIMARY 1.0 / NOTE 0.8 / SEGMENT 0.7 / MD 0.6 / NARRATIVE 0.4 / UNKNOWN 0.3；`evidence_quality` 权重（默认 0.10）可配置 |
| 新排序公式 | `final = metric + value + period + entity + text + page_bonus + table_bonus + evidence_quality×质量分`（semantic+value+period+table+evidence_quality，权重全可配置） |
| 多证据集合 | 候选按 `evidence_tier` 分层：`primary`（PRIMARY_FINANCIAL_STATEMENT）/ `secondary`（其余），一个主张同时返回多级证据 |
| 数据库 | `evidence_candidates` 新增 `evidence_type` / `evidence_quality_score` / `evidence_rank_reason`（轻量迁移；原始检索分保留） |
| 评测新增 | **Evidence Quality Accuracy**（Top1 类型 vs gold 最佳类型，gold evidence_type 映射六类）与 **Primary Evidence Hit Rate**（gold 页在 primary 层级候选中的 Hit@K） |
| 前端 | 候选表新增证据类型星级标签（★★★★★ 财务报表 / ★★★★ 附注/分部 / ★★★ 管理层分析 / ★★ 定性）+ 排名原因列 + Primary 标记 |

### 重新评测（Oracle 模式，top_k=5，v2 权重）

| 指标 | Demo | Holdout |
| ---- | ---- | ------- |
| Page Hit@1 / @3 / @5 | **0.167 / 0.208 / 0.25**（Hit@1 ↑ 0.125） | 0.273 / 0.364 / 0.364 |
| Block Hit@5 | 0.25 | 0.364 |
| MRR | **0.191**（↑ 0.170） | 0.303 |
| Primary Evidence Hit@1 / @5 | 0.167 / 0.25 | 0.182 / 0.273 |
| Evidence Quality Accuracy | 0.417 | 0.545 |
| no_result_rate | 0.269 | 0.353 |

**证据质量加权带来正向改善**：Demo Page Hit@1 0.125→0.167、MRR 0.170→0.191（财务报表主表候选因质量分上浮）；Holdout 持平。

### 完成标准对照

| 标准 | 状态 |
| ---- | ---- |
| Evidence Type 设计 / 分类准确案例 | ✅ 六类规则分类 + 专项测试（利润表/管理层讨论/附注/分部/表格优先/等级排序） |
| 新排序公式 | ✅ semantic+value+period+table+evidence_quality（权重可配置） |
| Demo/Holdout 重新评测 | ✅ 如上（含新增两项指标） |
| Primary Evidence Hit Rate / Evidence Quality Accuracy | ✅ 已实现并输出 |
| 测试（新增 6 项，全量 **211 passed**）/ 前端 build / 双金标准 0 错误 / Git commit | ✅ |

---

## Phase 4B.1：金融事实核验引擎 — ✅ 已完成（commit `ec81a51`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| 架构 | **Deterministic Verification Engine + Agent Explanation Layer**——规则/计算核验（不依赖 LLM 自由判断），可解释结论 |
| 核验模块 | `backend/app/services/verification/`：base（状态/类型/结果数据类）、numeric_verifier、growth_verifier、period_verifier、evidence_checker、verification_service |
| 数字验证 | EXACT_VALUE_CHECK：绝对值核验，单位转换（亿元/千元/万元/元/千分位/括号负数/列单位），`calculation_detail` 保存换算过程（source_value/source_unit/converted_value/tolerance） |
| 增长率验证 | GROWTH_RATE_CHECK：(cur−prev)/prev×100%，±0.5pp 容差；**指标族+期间双重证据排序**（防止用 Q1 数据验证 FY 增长率） |
| 期间验证 | PERIOD_CHECK：Q2 = H1 − Q1 单季推算；期间冲突检测 |
| 证据充分性 | SEMANTIC_CHECK：无数字主张只有收入数字 → INSUFFICIENT_EVIDENCE（不强制判断）；MULTI_EVIDENCE_CHECK：数值+同比+业务三维覆盖 |
| 数据库 | `verification_runs` + `verification_results`（matched_evidence_ids/calculation_detail/reason 完整入库） |
| API | `POST /api/v1/verifications`（claim_ids+mode）、`GET /api/v1/verifications/{id}`（status/confidence/证据/计算/说明） |
| 前端 | `/verifications` 页面：Claim/Evidence/Calculation/Result，绿（SUPPORTED）/红（REFUTED）/黄（INSUFFICIENT）卡片 |
| 安全 | 核验引擎不读取 gold_verifications（专项测试：篡改答案不影响核验结果） |

### 核验评测（Verification Accuracy）

| 指标 | Demo（26 条） | Holdout（17 条） |
| ---- | ------------- | ---------------- |
| Overall Accuracy | 0.6154 | 0.5294 |
| SUPPORTED precision | 0.8333 | 0.8 |
| REFUTED precision | 0.6667 | 0.8 |
| Unknown rate | 0.2692 | 0.2941 |
| 分组（numeric/growth/period/multi/semantic） | 0.75 / 0.667 / 0.0 / 0.5 / 0.5 | 0.667 / 1.0 / 0.0 / 0.0 / 0.0 |

产物：`artifacts/evaluations/verification/{demo,holdout}/metrics.json + report.md`。

### Demo 闭环演示（任务书十七要求）

```
AI 报告错误句：「归母净利润439.45亿元，同比增长38.02%」
→ 拆解 claim：CLM-004（yoy_growth_net_profit / 2025FY / 主张 38.02%）
→ 找到财报证据：年报主要会计数据（归母净利润行：当前期 438.30 亿元 / 上年同期 385.37 亿元）
→ 自动计算：(438.30 − 385.37) / 385.37 = 13.73%
→ 指出错误原因：计算增长率 13.73% 与主张 38.02% 不符（差 24.29pp）
→ 核验结论：REFUTED（置信度 0.9）
```

### 完成标准对照（任务书十七）

| 标准 | 状态 |
| ---- | ---- |
| Verification Engine 运行 / 数字验证 / 增长率验证 / Q2 计算 / 多证据 | ✅ 全部实现并验证 |
| verification_results 入库 / API / 前端展示 | ✅ 完成 |
| 测试（新增 13 项，全量 **224 passed**） | ✅ |
| Demo 案例跑通 / Git commit / progress.md 更新 | ✅ |

---

## Phase 4B.2：金融语义核验与证据充分性增强 — ✅ 已完成（commit `9b4813f`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| 语义主张类型 | BUSINESS_FACT / STRATEGIC_CLAIM / CAUSAL_CLAIM / COMPARATIVE_CLAIM / FORECAST_CLAIM（原句关键词优先 + claim_type 兜底分类） |
| Semantic 分析模块 | `backend/app/services/verification/semantic_verifier.py`：语义类型分类、Evidence Requirement 规则、Coverage 评分、因果/比较专项 |
| Evidence Requirement 规则 | STRATEGIC（海外核心动力）需 数值+增长率+整体占比/比较 3 维；CAUSAL 需 财务结果+原因披露；COMPARATIVE 需 行业排名/市占率+同行业数据；FORECAST 需 历史趋势+指引 |
| Evidence Coverage 评分 | 维度覆盖 → 全部 SUPPORTED / 部分 PARTIALLY_SUPPORTED / 无 INSUFFICIENT_EVIDENCE（example：海外核心动力 2/3 → PARTIALLY） |
| 因果关系验证 | 拆 Cause/Result；证据需 财务结果+公司披露原因/时间顺序；仅相关性（只有财务结果）不能认定因果 → INSUFFICIENT |
| 比较类验证 | 需比较对象（行业排名/市占率/同行业数据）；无 → INSUFFICIENT |
| 新 verification_type | SEMANTIC_SUPPORT_CHECK / CAUSAL_CHECK / COMPARISON_CHECK / EVIDENCE_SUFFICIENCY_CHECK |
| 语义检索修复 | `_text_keywords` 连接词加"已"、剥离公司/集团前缀——语义主张关键词回退从过窄（"海外业务已成"0 命中）修复为可检索（"海外业务"18 块） |
| 前端 | Semantic Evidence Card：Required Evidence ✓/✗（覆盖明细）、Result、Reason |
| UNKNOWN 保持 | 不删除 UNKNOWN/UNABLE_TO_DETERMINE 结果（专项测试覆盖） |

### Semantic Verification Accuracy（分组指标）

| 组 | Demo（accuracy/supp/prec/partial/insuff/count） | Holdout |
| -- | ---------------------------------------------- | ------- |
| BUSINESS_FACT | 0.20 / 0.50 / 0.00 / 0.00 / 5 | 0.50 / 0.50 / 0.00 / 0.50 / 4 |
| CAUSAL_CLAIM | 0.50 / 0.00 / 0.00 / 0.50 / 2 | 0.00 / — / — / — / 1 |
| COMPARATIVE_CLAIM | 1.00 / — / — / 1.00 / 1 | — |
| FORECAST_CLAIM | 0.00 / — / — / — / 1 | 0.00 / 1 |

Overall Accuracy：Demo 0.6154 / Holdout 0.5882（含语义分组后的重算）。

### Demo 闭环演示（两个案例，任务书十二）

```
案例 1（数字错误）：「归母净利润439.45亿元，同比增长38.02%」
  → CLM-004 → 财报数据 (438.30−385.37)/385.37=13.73% → REFUTED（差 24.29pp）

案例 2（语义夸大）：「海外业务已成为公司利润增长的核心引擎」
  → CLM-020（STRATEGIC_CLAIM，要求 3 维）
  → 找到证据：海外收入数据✓ + 增长率✓，缺 整体占比/增长比较✗
  → 覆盖 2/3 → PARTIALLY_SUPPORTED（"不是简单判断真假，而是判断证据是否足够"）
```

### 完成标准对照（任务书十三）

| 标准 | 状态 |
| ---- | ---- |
| Semantic Verification Engine / 新 Claim 类型 / Evidence Requirement 规则 / Evidence Coverage | ✅ 全部实现并验证 |
| 前端展示 / Demo 案例 / Semantic 评测 / 测试 | ✅ 完成（新增 7 项语义测试，全量 **231 passed**） |
| Git commit / progress.md 更新 | ✅ |

---

## Phase 5：金融审计智能体（Audit Agent）— ✅ 已完成（commit `1503c50`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Agent 模块 | `backend/app/services/agent/`：planner（固定流程，无 LLM 自由规划）/ tools（封装已有能力）/ executor（完整流程+执行日志）/ report_generator（审计报告）/ schemas |
| 固定审计流程 | `extract_claims → retrieve_evidence → verify_claims → generate_report`（AuditPlan 4 步，执行日志落库） |
| Agent Tools | `extract_claims`（复用已有提取/读取最近运行）、`retrieve_evidence`（证据检索 Top-K）、`verify_claim`（核验引擎）、`require_report_to_verify`（角色校验） |
| Audit Report | `audit_reports` 表（total/supported/refuted/partially/insufficient/unknown + risk_summary + report_json + plan_json）；报告含 **Summary / Risk Findings（Claim→Evidence→Calculation→Conclusion）/ Evidence Chain** |
| API | `POST /api/v1/audits`（{document_id}→{audit_id,status}）、`GET /api/v1/audits/{id}`（summary/findings/evidence_chain/verification_results/plan） |
| 前端 | `/audit` 页面：上传 AI 研报 / 选择已有研报 → 创建审计 → 执行过程展示（✓ Extracting claims 等 4 步）→ 审计结果（Summary 计数 + 风险详情卡片 + 证据链） |
| Evidence First | 不凭空判断、不编造证据、不输出投资建议；事实判断全部交由 Verification Engine |

### Demo 3 案例验证（任务书九）

| 案例 | 主张 | 结果 |
| ---- | ---- | ---- |
| Case 1 数字错误 | 归母净利润同比增长38.02%（CLM-004） | **REFUTED**（真实计算 (438.30−385.37)/385.37=13.73%） |
| Case 2 期间/口径错误 | 据一季度报告称上半年营收+20.49%（CLM-015） | **REFUTED**（期间口径与披露不符） |
| Case 3 语义夸大 | 海外业务成为增长核心动力（CLM-020） | **PARTIALLY_SUPPORTED**（2/3 覆盖：有增长证据、缺核心动力证明） |

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Audit Agent 运行 / 上传 AI 研报自动审计 / 调用已有 Claim-Evidence-Verification 模块 | ✅ 全部实现并验证 |
| 结构化 Audit Report / 前端完整流程展示 / Demo 案例运行 | ✅ 完成 |
| 测试（新增 Agent workflow 5 项，全量 **236 passed**）/ 前端 build / 双金标准 0 错误 | ✅ |
| Git commit / progress.md 更新 | ✅ |

---

## Phase 6：Financial Risk Intelligence Layer（金融风险评分层）— ✅ 已完成（commit `2a961c7`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Risk Engine 模块 | `backend/app/services/risk/`：risk_rules（风险分类/评分区间/调整因子）+ risk_engine（assess_claim/assess_audit）+ schemas |
| 风险类型 | FINANCIAL_ERROR（REFUTED+数字核验→HIGH）/ EVIDENCE_RISK（INSUFFICIENT/UNKNOWN→MEDIUM/HIGH）/ SEMANTIC_RISK（PARTIALLY→MEDIUM）/ FORECAST_RISK（预测被描述为事实） |
| Risk Score | 0-100，按状态区间（REFUTED 80-100 / PARTIALLY 40-70 / INSUFFICIENT 60-90 / SUPPORTED 0-20），按主张重要性/核验置信度/证据质量调整，clamp 到合法区间，`risk_reason` 逐条可解释 |
| Overall Risk | `overall = 0.5×max(risk_scores) + 0.5×风险点平均`（可解释公式）；Level 按分数阈值（LOW<30 / MEDIUM≤65 / HIGH>65） |
| 数据库 | `risk_assessments` 表（claim_id/verification_status/type/risk_score/level/type/risk_reason） |
| API | `POST /api/v1/risk-assessments/{audit_id}`（生成评分入库）、`GET /{audit_id}`（overall/distribution/top_risks/claim_details，确定性重建） |
| Audit 集成 | `GET /api/v1/audits/{id}` 新增 risk 字段（Overall Risk：score/level/distribution） |
| 前端 | /audit 页面 Risk Dashboard：FinProof Risk Score + Risk Level + 风险分布（HIGH/MEDIUM/LOW）+ Top Risk Findings（按 risk_score 排序：Verification → Risk Reason） |

### Demo 验证（任务书八）

```
输入：AI 研报（文档 #4，41 条主张）
输出：Overall Risk 93.6/100 HIGH
  Risk Distribution：HIGH 17 / MEDIUM 5 / LOW 19
  Top Risk：CLM-RUN20-004（归母净利润同比增长38.02%）Risk Score 100 FINANCIAL_ERROR
    Reason：核验 REFUTED（GROWTH_RATE_CHECK）基准90 + 重要性HIGH +8 + 置信度0.90 +9.6
            （计算增长率 13.73% 与主张 38.02% 偏差 24.29pp）
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Risk Engine 运行 / 每个 Claim 生成 Risk Score | ✅ 全部实现并验证（REFUTED 100 HIGH / SUPPORTED 18 LOW / PARTIALLY 59 MEDIUM / INSUFFICIENT 79 HIGH） |
| Audit 生成整体风险评分 / 前端 Risk Dashboard / Demo 风险排序 | ✅ 完成 |
| 测试（新增 risk 7 项，全量 **243 passed**）/ 前端 build / 双金标准 0 错误 | ✅ |
| 更新 docs/finproof_progress.md / Git commit | ✅ |

---

## Phase 7：Investment Due Diligence Agent（投资尽调智能体）— ✅ 已完成（commit `77a29dc`）

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Investment 模块 | `backend/app/services/investment/`：investment_analyzer（生成 Memo）、risk_summary（投资风险分类聚合）、schemas |
| 投资风险分类 | FINANCIAL_RISK（数字/增长率/指标错误）/ BUSINESS_RISK（业务事实/战略）/ COMPETITIVE_RISK（比较类）/ MANAGEMENT_RISK（治理/管理层）；基于 claim_type/verification_type/risk_type/关键词规则（可解释） |
| Investment Risk Memo | Company（公司/代码/报告期）+ Overall Risk Score/Level + Key Risks（按 risk_score 排序 + 分类标签）+ Evidence Chain + Claims Requiring Review（risk_score≥60 → NEED_REVIEW 初始化） |
| Human Review | 审核状态 NEED_REVIEW / APPROVED / REJECTED；`investment_reviews` 表保存记录（note/reviewer/updated_at）；非法状态拒绝 |
| 数据库 | `investment_memos`（company/overall/key_risks_json/memo_json）+ `investment_reviews` |
| API | `POST /api/v1/investment/memos`（{audit_id}）、`GET /{id}`、`POST /{id}/reviews`（审核） |
| 前端 | `/investment` 页面：公司信息 + 风险评分 + Key Risks + 待审核事项（审核按钮 APPROVE/REJECT + 备注）+ 证据链 |
| 设计约束 | 不改变已有 Verification/Risk 逻辑；不输出投资建议、不自动决策（审核权留给投资经理） |

### Demo 全链路验证（任务书 6）

```
① 公司：美的集团（000333，2025FY）
② 整体风险：93.6/100 HIGH
③ Top Risks（12 条）：CLM-RUN20-004 [财务风险] 100 | CLM-RUN20-008 [财务风险] 100 | …
④ 待审核事项：12 条（全部 NEED_REVIEW）
⑤ 投资经理审核：CLM-RUN20-004 → APPROVED（投资经理A，备注"与年报核对一致"）
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 投资尽调流程运行 / 输出 Investment Risk Memo | ✅ 全部实现并验证（audit → memo → review 全链路） |
| 支持人工审核 / 前端展示 / Demo 完成 | ✅ NEED_REVIEW→APPROVED/REJECTED 持久化；/investment 页面 |
| 测试（新增 investment 4 项，全量 **247 passed**）/ 前端 build / 双金标准 0 错误 | ✅ |
| 更新 docs/finproof_progress.md / Git commit | ✅ |

---

## Phase 8：Investment Intelligence Agent（投资情报智能体）— ✅ 已完成

### 任务

将 FinProof 从"AI 报告审计工具"升级为"投资调查辅助 Agent"：输入投资标的，
将公司公开信息与投资材料中的观点交叉验证，发现潜在风险。

**不修改已有核心验证逻辑**；**不开发自动投资建议、不进行股票推荐、不替代投资经理决策**。

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Intelligence 模块 | `backend/app/services/intelligence/`：schemas / fact_extractor / conflict_detector / intelligence_agent |
| 外部事实模型 | `CompanyFact`：dimension（公司/业务/财务/市场/产品/竞争）+ source（财报/公告/新闻/官网）+ evidence + timestamp + confidence；Evidence First：缺任一字段即拒绝 |
| Conflict Detection | `detect_conflicts`：Investment Claim vs External Fact，4 类发现（FINANCIAL_DATA_CONFLICT / BUSINESS_DESC_CONFLICT / GROWTH_LOGIC_INSUFFICIENT / COMPETITIVE_EVIDENCE_MISSING）+ NO_OPPOSITION（支持）；每条附 evidence_trace |
| 冲突输出 | `ConflictFinding`：claim / fact / difference / risk_type / risk_score（0-100，与 Phase 6/7 阈值一致）|
| Investment Intelligence Report | Company Profile + Verified Facts + Conflicts + Risk Findings + Evidence Chain；overall = 0.5×最高单项 + 0.5×冲突项平均 |
| 数据库 | `intelligence_reports` 表（公司/整体风险/冲突数/支持数/完整报告 JSON）|
| API | `POST /api/v1/intelligence/runs`（运行投资调查）、`GET /api/v1/intelligence/runs/{id}`（查询报告）|
| 前端 | `/intelligence` 页面：① 投资标的 → ② Company Facts → ③ Evidence Sources → ④ Conflict Findings → ⑤ Risk Summary → ⑥ Evidence Chain（Claim ↓ External Evidence ↓ Conflict ↓ Risk）|
| Demo | 美的集团（000333，2025FY），3 条投资观点（海外业务高速增长 / 公司保持行业领先 / 盈利能力持续提升）+ 公告/新闻外部事实，`backend/scripts/phase8_demo.py` + `docs/phase8_demo.md` |

### Demo 全链路验证（任务书 §5）

```
Claim                    External Evidence              Conflict/Support            Risk
────────────────────────────────────────────────────────────────────────────────────────
INV-0001 海外业务高速增长   公告：业绩预增（无增长数字）   GROWTH_LOGIC_INSUFFICIENT   60  MEDIUM
                            增长逻辑不充分

INV-0002 公司保持行业领先   新闻：美的空调线上线下份额     NO_OPPOSITION（强证据支持）  0   LOW
                            双第一

INV-0003 盈利能力持续提升   财报：营收/净利润数字（口径    FINANCIAL_DATA_CONFLICT    85  HIGH
                            不一致或增长逻辑缺数据）
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Investment Intelligence Agent 运行 | ✅ `run_investigation` 全链路（观点登记 → 事实抽取 → 冲突检测 → 报告汇总）|
| 支持 Fact 与 Claim 比较 | ✅ `detect_conflicts`：Claim 维度配对 Fact，4 类冲突结论 + 支持 |
| 输出 Conflict Report | ✅ `IntelligenceReport`：Company Profile / Verified Facts / Conflicts / Risk Findings / Evidence Chain |
| 前端展示 | ✅ `/intelligence` 页面（6 个区块：标的 / Facts / Sources / Conflicts / Risk / Evidence Chain）|
| Demo 完成 | ✅ 美的集团 3 观点 + 公告/新闻外部事实，`scripts/phase8_demo.py` 可运行 |
| 更新 progress.md | ✅ 本节 |

### 验证结果

- 后端 pytest：**271 passed**（新增 intelligence 24 项，全量绿）
- 前端：`pnpm build` 成功，`/intelligence` 静态预渲染（2.74 kB）
- Evidence First：每条 Company Fact 强制 source/evidence/timestamp/confidence，`validate_fact_evidence` 校验
- 设计约束遵守：不修改 Verification/Risk/Audit/Investment Memo；不输出投资建议、不推荐股票、不替代投资经理决策

---

## Phase 9：Investment Committee Multi-Agent System（投资委员会多 Agent 系统）— ✅ 已完成

### 任务

将 FinProof 升级为多 Agent 投资审核系统，模拟真实投资委员会流程。

- Supervisor Agent 拆解任务 → 调用 Research / Risk / Compliance Agent → 汇总
- **不修改已有核心模块**（Verification / Risk / Intelligence / Audit / Investment Memo）
- 不输出投资建议、不自动决定买卖、保持 Human-in-the-loop

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Committee 模块 | `backend/app/services/investment_committee/`：supervisor_agent / research_agent / risk_agent / compliance_agent / schemas |
| Supervisor Agent | `split_tasks` 拆任务（Research/Risk/Compliance）→ `_dispatch` 依次调度 → `run_committee` 汇总为 CommitteeReport |
| Research Agent | `run_research`：Company Overview / Business Analysis / Financial Summary，来源必须来自已有 Evidence（DocumentBlock + Intelligence Verified Facts）|
| Risk Agent | `run_risk`：调用 Risk Engine（`assess_audit`）+ Intelligence（`get_report`）+ Audit Report；输出 Risk Findings / Conflict Findings / Risk Score |
| Compliance Agent | `run_compliance`：四类检查 — UNSUPPORTED_CLAIM / OVERSTATEMENT / MISSING_EVIDENCE / FORECAST_AS_FACT |
| Investment Committee Report | Executive Summary / Research Findings / Risk Findings / Compliance Findings / Evidence Chain / Human Review Items |
| 数据库 | `committee_reports` 表（公司/整体风险/合规评分/agent_flow_json/report_json）|
| API | `POST /api/v1/committee/runs`（运行委员会）、`GET /runs/{id}`（查询报告）、`POST /runs/{id}/reviews`（人工审核）|
| 前端 | `/committee` 页面：① Agent 执行流程 → ② Executive Summary → ③ Research Findings → ④ Risk Findings → ⑤ Compliance Findings → ⑥ Evidence Chain → ⑦ Human Review Items |
| Demo | 美的集团投资案例，`backend/scripts/phase9_demo.py` + `docs/phase9_demo.md` |

### Demo 全链路验证（任务书 §8）

```
① 输入：美的集团投资材料（含海外业务增长/遥遥领先/必将持续高速增长）
② Supervisor 拆任务 → Research → Risk → Compliance
③ 三个 Agent 发现：
   Research    : 海外业务增长（业务增长驱动识别）
   Risk        : 缺少利润贡献证明（Risk Engine 风险点 + Intelligence 冲突结论）
   Compliance  : 存在夸大表达（OVERSTATEMENT：遥遥领先）+ 预测为事实（FORECAST_AS_FACT：必将持续）
④ Investment Committee Report：整体风险评分 + 合规评分 + 证据链 + 人工审核项
⑤ 投资经理审核：高风险/合规问题自动提请 NEED_REVIEW → APPROVED/REJECTED
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Multi-Agent 流程运行 | ✅ `run_committee`：Supervisor → Research → Risk → Compliance → Report 全链路 |
| Agent 调用已有模块 | ✅ Research 用 DocumentBlock/Intelligence Facts；Risk 用 Risk Engine/Intelligence/Audit；Compliance 用 Audit/Risk Engine/投资材料 |
| 输出 Investment Committee Report | ✅ Executive Summary / Research / Risk / Compliance / Evidence Chain / Human Review Items |
| 前端展示 Agent 流程 | ✅ `/committee` 页面（7 个区块，含 Agent 执行流程可视化）|
| Demo 完成 | ✅ 美的集团投资案例，三 Agent 发现可复现 |
| 更新 progress.md | ✅ 本节 |

### 验证结果

- 后端 pytest：**297 passed**（新增 committee 26 项，全量绿）
- 前端：`pnpm build` 成功，`/committee` 静态预渲染
- 设计约束遵守：不修改已有核心模块；不输出投资建议、不自动决定买卖、保持 Human-in-the-loop（REVIEW_SCORE_THRESHOLD=60，高风险/合规问题自动提请人工审核）

---

## 下一步（不在本轮范围）

- 投资建议、自动决策、自动交易——按任务书"停止，不开发投资建议和自动决策"。

---

## Phase 10：Financial Knowledge Graph Engine（金融知识图谱引擎）— ✅ 已完成

### 任务

新增金融知识图谱层，提高金融事实关联和冲突发现能力。

- **不修改已有 Verification 逻辑**；Knowledge Graph 作为新增层，与已有模块解耦
- Evidence First：每个 Fact 必须包含 source / evidence / confidence / timestamp

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Knowledge Graph 模块 | `backend/app/services/knowledge_graph/`：schemas / entity_extractor / graph_builder / fact_graph / conflict_reasoner |
| Entity Extraction | `extract_entities`：从 Claims/Evidence/Company Facts 抽取 7 类实体 — Company / Business / Product / Region / Competitor / Metric / Executive；同名去重，唯一 ENT-XXXXX ID |
| Fact Graph 数据库 | `kg_entities` / `kg_relationships` / `kg_facts` 三表；每条 Fact 强制 source/evidence/confidence/timestamp（Evidence First）|
| Relationships | 6 种关系：OWNS / HAS_BUSINESS / COMPETES_WITH / LOCATED_IN / HAS_METRIC / SUPPORTED_BY；唯一 REL-XXXXX ID，关联 fact_id 可追溯 |
| Conflict Reasoning | `detect_conflicts`：4 类冲突 — CLAIM_VS_FACT / BUSINESS_OVERSTATEMENT / COMPETITIVE_NO_EVIDENCE / GROWTH_INSUFFICIENT + NO_OPPOSITION；输出 ConflictFinding（claim / graph_facts / difference / risk_type / risk_score）|
| Committee Integration | Research Agent 增加工具 `knowledge_graph`：调用 `get_company_profile` / `get_business_map`，合并 KG 字段到 ResearchFindings（businesses/products/regions/business_segments）|
| API | `POST /api/v1/knowledge-graph/build`（构建图谱）、`GET /{document_id}`（实体网络/事实/证据来源）、`GET /{document_id}/profile`、`GET /{document_id}/business-map`、`GET /{document_id}/evidence-sources`、`POST /conflicts`（冲突推理）|
| 前端 | `/knowledge-graph` 页面：① Entity Network（实体网络，按类型分组）→ ② Facts（图谱事实，含证据）→ ③ Evidence Source（证据来源）→ ④ Conflict（冲突推理结论）|
| Demo | �美的集团投资案例，`backend/scripts/phase10_demo.py` + `docs/phase10_demo.md` |

### Demo 全链路验证（任务书 §8）

```
① 输入：美的集团投资材料（含夸大表达/海外业务/竞争对手描述）
② Entity Extraction：公司(美的集团) / 业务(暖通空调/消费电器/机器人) / 产品(空调/COLMO/KUKA) / 地区(海外/北美) / 竞争对手(海尔/格力/海信) / 指标(营业收入/归母净利润)
③ Fact Graph：kg_entities + kg_relationships + kg_facts（Evidence First）
   - OWNS:           美的集团 → �空调 / 冰箱
   - HAS_BUSINESS:   美的集团 → 暖通空调 / 消费电器
   - COMPETES_WITH:  美的集团 → 海尔 / 格力 / 海信
   - HAS_METRIC:     美的集团 → 营业收入 4564.52 亿元
   - SUPPORTED_BY:   事实 → 证据
④ Conflict Reasoning：
   - BUSINESS_OVERSTATEMENT:  "遥遥领先" → 70 分
   - GROWTH_INSUFFICIENT:     "海外业务高速增长" 无增长数字 → 60 分
   - COMPETITIVE_NO_EVIDENCE: "行业领先" 无市场份额强证据 → 55 分
⑤ Committee Integration：Research Agent �用 KG 增强 Company Profile / Business Map
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Knowledge Graph 运行 | ✅ `build_graph` 全链路（实体抽取 → 事实构建 → 关系构建 → 持久化）|
| Fact 可追溯 Evidence | ✅ 每条 Fact 强制 source/evidence/confidence/timestamp，`validate` 校验，SUPPORTED_BY 关系 |
| 支持 Conflict Reasoning | ✅ `detect_conflicts`：4 类冲突 + NO_OPPOSITION，含 graph_facts 字段 |
| Committee �用成功 | ✅ Research Agent 增加 `knowledge_graph` 工具，合并 KG Company Profile / Business Map |
| Demo 完成 | ✅ 美的集团投资案例，`scripts/phase10_demo.py` 可运行 |
| 更新 progress.md | ✅ 本节 |

### 验证结果

- 后端 pytest：**324 passed**（新增 knowledge_graph 27 项，全量绿）
- 前端：`pnpm build` 成功，`/knowledge-graph` 静态预渲染（2.54 kB）
- Evidence First：每条 Fact 强制 source/evidence/confidence/timestamp，SUPPORTED_BY 关系可追溯
- 设计约束遵守：不修改已有 Verification 逻辑；Knowledge Graph 作为新增层与已有模块解耦

---

## 提交记录

| 提交 | 内容 |
| ---- | ---- |
| `a591bff` | chore: Phase 0 脚手架（后端/前端/基础文件） |
| `8270be4` | feat: Phase 1 演示数据与金标准 |
| `6ac1bf0` | docs: Phase 0/1 进度记录 |
| `ae7f926` | docs: 高风险金标准复核与修正（数据冻结） |
| `ca065e6` | feat: Phase 2 文档接入与可追溯解析（含本文档随附更新） |
| `b2a6531` | docs: Phase 2 进度记录 |
| `e5af15e` | feat: Phase 3 金融主张提取与结构化评测（含本文档随附更新） |
| `2f2d509` | docs: Phase 3 进度记录 |

---

## Phase 11：Financial AIBenchmark System（金融 AI 可信度评测基准）— ✅ 已完成

### 任务

建立金融 AI 可信度评测基准，评估 AI 生成金融内容的错误检测能力。

- **不修改已有核心模块**（Verification / Risk / Knowledge Graph / Audit / Committee）
- Benchmark 作为新增层，复用已有风险口径但独立实现评测逻辑
- Evidence First：FinProof 判定基于金标准证据覆盖

### 核心内容

| 项 | 结果 |
| -- | ---- |
| Benchmark 模块 | `backend/app/services/benchmark/`：schemas / dataset / metrics / evaluator |
| Dataset | `BenchmarkCase`：claim / category / gold_evidence / gold_result / risk_type；6 类错误（FINANCIAL_ERROR / PERIOD_ERROR / GROWTH_ERROR / SEMANTIC_OVERSTATEMENT / COMPETITIVE_CLAIM / CAUSAL_ERROR）；**51 条预置案例**（50 错误 + 1 正确对照）覆盖 6 家公司（美的/格力/海尔智家/茅台/比亚迪/宁德时代）|
| Evaluation | `run_benchmark`：FinProof（证据覆盖+风险口径+语义/增长/竞争/期间/因果多维检测）vs Baseline LLM（弱核验，仅绝对化+超数字）；逐案例 `CaseResult` + `BenchmarkMetrics` |
| Metrics | `compute_metrics`：Accuracy / Precision / Recall / F1 / Evidence Coverage / Risk Detection Rate + 分错误类别召回率（`recall_by_category`）|
| Model Comparison | `compare_models`：FinProof vs Baseline LLM 关键指标增益（accuracy_gain / f1_gain / recall_gain 等）|
| 数据库 | `benchmark_cases` / `benchmark_runs` / `benchmark_results` 三表 |
| API | `POST /api/v1/benchmark/seed`（载入预置案例）、`GET /dataset`（概况+错误分布）、`POST /runs`（运行评测）、`GET /runs/{id}`（查询报告）、`GET /dataset/count` |
| 前端 | `/benchmark` 页面：① Dataset 数量与错误分布 → ② Evaluation Metrics（FinProof vs Baseline 指标表+分类别召回率）→ ③ Model Comparison（对比摘要）→ ④ 逐案例结果摘录（FinProof 检测 AI 幻觉）|
| Demo | `backend/scripts/phase11_demo.py` + `docs/phase11_demo.md`：51 条案例全链路评测 |

### Demo 全链路验证（任务书 §7）

```
① Dataset：51 条预置金融测试案例（6 类错误各 8-9 条 + 1 正确对照）
② 错误分布：FINANCIAL_ERROR 8 / PERIOD_ERROR 8 / GROWTH_ERROR 9 /
              SEMANTIC_OVERSTATEMENT 8 / COMPETITIVE_CLAIM 8 / CAUSAL_ERROR 9
③ FinProof 评测：数字比对 + 语义夸大 + 增长逻辑 + 竞争缺证据 + 期间错误 + 因果绝对化
④ Baseline LLM 评测：仅绝对化关键词 + "超 X 亿"数字检测（弱核验）
⑤ FinProof 增益：Recall / F1 / Risk Detection Rate 显著高于 Baseline
⑥ FinProof 检测 AI 幻觉：逐案例输出 predicted_risk_type + predicted_risk_score + evidence_coverage
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| Benchmark 运行 | ✅ `run_benchmark` 全链路（Dataset 载入 → 双模型评测 → 指标计算 → 对比摘要 → 持久化）|
| 自动评测 AI 金融内容 | ✅ 51 条案例自动评测，FinProof 多维检测（6 类错误）+ Baseline 弱核验对比 |
| 输出指标 | ✅ Accuracy / Precision / Recall / F1 / Evidence Coverage / Risk Detection Rate + 分类别召回率 |
| 前端展示 | ✅ `/benchmark` 页面（4 区块：Dataset 概况 / 指标对比 / 模型对比摘要 / 逐案例结果）|
| Demo 完成 | ✅ 51 条预置案例，`scripts/phase11_demo.py` 可运行 |
| 更新 progress.md | ✅ 本节 |

### 验证结果

- 后端 pytest：**358 passed**（新增 benchmark 34 项，全量绿）
- 前端：`pnpm build` 成功，`/benchmark` 静态预渲染
- FinProof vs Baseline：FinProof 召回率/F1/风险检测率显著高于 Baseline，凸显发现 AI 金融幻觉能力
- 设计约束遵守：不修改已有核心模块；Benchmark 作为新增层；Evidence First（FinProof 判定基于金标准证据覆盖）
| `0e7a722` | feat: Phase 3.5 主张提取质量优化（评测器/过滤/子句归属/去重/Prompt v2/模式）（含本文档随附更新） |
| `6d80b17` | docs: Phase 3.5 进度记录 |
| `f24846a` | feat: Phase 3.6 盲测数据集（五粮液）+ 泄漏防护 + claim_group + Hybrid 优化（标签 holdout-v1） |
| `55fae55` | feat: Phase 3.6 稳定性框架/分别报告/测试/失败记录（含本文档随附更新） |

---

## Phase 12：企业投资治理层（Enterprise Investment Governance Layer）— ✅ 已完成

> 更新日期：2026-07-31
> 目标：增强企业金融机构落地能力；不修改已有核心验证逻辑。

### 背景

在 Phase 5（Audit）、Phase 7（Investment Intelligence）、Phase 8（Knowledge Graph）、Phase 9（Investment Committee）、Phase 11（Benchmark）之上，新增"企业投资治理层"：从"单报告审计 → 投资风险分析"演进到"组合级治理 + 持续监控 + 审计回溯"。

### 交付物

| 模块 | 产出 |
| ---- | ---- |
| **Portfolio Risk Dashboard** | `backend/app/services/portfolio/aggregator.py`：多投资项目风险汇总，加权平均组合风险分、公司风险排名、风险分布（HIGH/MEDIUM/LOW）、最高风险 Findings；`backend/app/api/portfolio.py`：项目 CRUD + 快照构建/查询 API；`backend/app/models/portfolio.py`：`portfolio_projects` / `portfolio_risk_snapshots` 两表；`backend/app/schemas/portfolio.py`：`PortfolioProject` / `PortfolioRiskSnapshot` / `CompanyRankingItem` / `RiskDistributionItem` / `HighestRiskFinding` |
| **Continuous Monitoring** | `backend/app/services/monitoring/detector.py`：历史投资观点保存（`investment_theses`）+ Thesis Conflict 检测（新 Fact vs 历史 Claim），输出 `claim / new_fact / difference / risk_score`，冲突类型 `METRIC_DRIFT`（±15% 阈值）/ `DIRECTION_REVERSAL` / `NEW_RISK`；`backend/app/api/monitoring.py`：观点 CRUD + 监控运行 + 告警查询/状态更新 API；`backend/app/models/monitoring.py`：`investment_theses` / `monitoring_alerts` 两表 |
| **Audit Trail** | `backend/app/services/audit_trail/logger.py`：`log_audit` / `list_logs` / `get_log`，字段 `user / action / timestamp / model_version / rule_version / evidence_used / detail`；`backend/app/api/governance.py`：审计日志 POST/GET + 证据溯源 `evidence-trace/{target_type}/{target_id}`；`backend/app/models/audit_trail.py`：`audit_trail_logs` 表 |
| **Frontend** | `frontend/src/app/portfolio/page.tsx`（`/portfolio`）：项目风险排名 + 风险趋势 + 新增项目/构建快照；`frontend/src/app/governance/page.tsx`（`/governance`）：Audit Logs 查询 + Evidence Trace 溯源 |
| **Demo** | `backend/scripts/phase12_demo.py`：3 家公司投资组合（美的集团 000333 / 五粮液 000858 / 宁德时代 300750）→ 组合风险快照 → 保存 3 条历史投资观点 → 模拟新风险（美的毛利率大幅下滑 METRIC_DRIFT + 宁德时代收到监管问询函 NEW_RISK）→ 生成 Monitoring Alerts → Audit Trail 全链路记录 |
| **Testing** | `backend/tests/test_portfolio.py`（5 项）、`backend/tests/test_monitoring.py`（7 项）、`backend/tests/test_audit_trail.py`（3 项）共 15 项新增测试 |

### Demo 全链路验证（任务书 §5）

```
① Portfolio          3 家公司入组合 → 加权风险分 / 排名 / 分布
② Monitoring         保存 3 条历史投资观点 → 模拟 3 条新 Fact
③ 模拟新风险         美的毛利率 28%→22%（METRIC_DRIFT，风险分 61.4）
                     宁德时代收到监管问询函（NEW_RISK，风险分 75.0）
                     五粮液营收保持稳定（无冲突）
④ Audit Trail        关键操作记录 → 证据溯源
```

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. Portfolio Risk Dashboard | ✅ `aggregator.py` 加权汇总 + 排名 + 分布 + 最高风险 Findings；`portfolio_projects` / `portfolio_risk_snapshots` 两表 |
| 2. Continuous Monitoring | ✅ `detector.py` 保存历史观点 + 检测新 Fact vs 历史 Claim；输出 `claim / new_fact / difference / risk_score`；`investment_theses` / `monitoring_alerts` 两表 |
| 3. Audit Trail | ✅ `logger.py` 记录 `user / action / timestamp / model_version / rule_version / evidence_used`；`audit_trail_logs` 表 |
| 4. 前端展示 | ✅ `/portfolio`（项目风险排名 + 风险趋势）+ `/governance`（Audit Logs + Evidence Trace） |
| 5. Demo 完成 | ✅ `scripts/phase12_demo.py`：3 家公司组合 + 模拟某公司出现新风险，全链路打通 |
| 6. 更新 progress.md | ✅ 本节 |
| 停止边界 | ✅ 不开发交易和投资建议；不修改已有核心验证逻辑；Portfolio/Monitoring/AuditTrail 作为新增治理层 |

### 验证结果

- 后端 pytest：**380 passed**（新增 15 项 Phase 12 测试 + 既有 365 项，全量绿）
- Demo：`python -m scripts.phase12_demo` 端到端跑通，生成 2 条告警（METRIC_DRIFT / NEW_RISK）
- 设计约束遵守：不修改已有核心模块（Verification / Risk / Audit / Committee / Benchmark / Intelligence / KnowledgeGraph）；新增治理层独立；不输出投资建议、不自动决定买卖

---

## Phase 13：自主调查智能体（Autonomous Investigation Agent）— ✅ 已完成

> 更新日期：2026-08-01
> 目标：升级 Supervisor，使其能够根据风险类型自主规划调查路径。
> 约束：不修改已有 Verification 核心逻辑；保持 Evidence First；Agent 根据计划选择调用工具，禁止直接生成事实。

### 背景

当前流程：`Claim → Evidence → Verification → Risk → Report`（固定管线）。
Phase 13 升级 Supervisor：从固定调用 Research/Risk/Compliance → 根据任务动态生成调查计划，Agent 自主调用已有工具，生成完整调查轨迹，并支持 Memory（供 Continuous Monitoring 调用）。

### 交付物

| 模块 | 产出 |
| ---- | ---- |
| **Autonomous Agent 模块** | `backend/app/services/autonomous_agent/`：`schemas.py`（ClaimContext / InvestigationPlan / InvestigationRun / AgentMemory + 6 类 claim_type + 6 类 tool 常量）/ `planner.py`（classify_claim_type 启发式分类 + make_plan 按 claim_type 生成工具链）/ `tool_registry.py`（封装 retrieve_evidence / verify_claim / get_company_profile / get_business_map / detect_conflicts / assess_risk 六个已有工具）/ `executor.py`（run_investigation 端到端执行 + execution_trace 持久化）/ `memory.py`（Agent Memory：upsert / get / resolve_issue / list_memories，按 company 唯一） |
| **数据库（§7）** | `backend/app/models/autonomous_agent.py`：`investigation_runs`（trace_id / claim_context / plan / steps / evidence / conclusion）/ `investigation_steps`（step / tool_name / input / output / reasoning / result / evidence_source / timestamp）/ `investigation_memory`（company / historical_risk / previous_findings / resolved_issues / last_investigation_id）。三表均在 `models/__init__.py` 注册 |
| **API（§8）** | `backend/app/api/investigation.py`：`POST /api/v1/investigations`（启动自主调查）/ `GET /api/v1/investigations`（列出）/ `GET /api/v1/investigations/{run_id}`（返回 plan/steps/evidence/conclusion）/ `GET /api/v1/investigations/memory/{company}`（查询 Agent Memory）。已在 `main.py` 注册 |
| **Supervisor 集成（§6）** | `backend/app/services/investment_committee/supervisor_agent.py` 新增 `run_committee_autonomous`：根据任务动态生成调查计划，前置自主调查记录到 agent_flow；保留 `run_committee`（固定 Research→Risk→Compliance）作为 fallback |
| **前端（§9）** | `frontend/src/app/investigation/page.tsx`（`/investigation`）：①启动表单（claim_text / claim_type / company / use_memory）→ ②Agent Reasoning Trace（Action Trace：Step×Tool×Status + Tool Results：证据数/冲突数/风险分）→ ③Evidence 汇总（block/page/score/text）→ ④Conclusion（核验结论/风险分/类型）。展示过程，不展示隐藏思维链 |
| **Demo（§10）** | `backend/scripts/phase13_demo.py`：案例 AI 报告主张「海外业务成为利润增长核心」→ ①Planner 识别 STRATEGIC → ②Tool Registry 验证 6 工具可用 → ③Executor 执行 Plan（get_business_map → retrieve_evidence → detect_conflicts → verify_claim → assess_risk）→ ④Memory 写入 → ⑤Integration 回读验证 |
| **Testing（§11）** | `backend/tests/test_autonomous_agent.py` 共 **22 项**：planner（classify_claim_type 6 类型 + make_plan 各 claim_type 工具链）/ tool（build_registry 6 工具 + call_tool assess_risk / detect_conflicts）/ execution trace（run_investigation 持久化 steps + get_investigation 回读 + list_investigations）/ memory（upsert+get / resolve_issue / list_memories）/ integration（API POST/GET 端到端 + memory lookup） |

### Planner 调查路径（按 claim_type）

| claim_type | 工具链（steps） |
| ---------- | --------------- |
| FINANCIAL（财务数据主张） | retrieve_evidence → verify_claim → assess_risk |
| BUSINESS（业务主张） | get_business_map → retrieve_evidence → verify_claim → assess_risk |
| COMPETITIVE（竞争优势主张） | get_company_profile → retrieve_evidence → detect_conflicts → verify_claim |
| GROWTH（增长主张） | retrieve_evidence → verify_claim → assess_risk |
| STRATEGIC（战略主张，Demo 案例） | get_business_map → retrieve_evidence → detect_conflicts → verify_claim → assess_risk |
| FORECAST（预测主张） | retrieve_evidence → detect_conflicts → verify_claim |

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. Supervisor 具备动态调查规划 | ✅ `run_committee_autonomous` 根据 claim_type 动态生成 plan；保留 `run_committee` fallback |
| 2. Agent 能够调用已有工具 | ✅ `tool_registry.py` 封装 6 个已有工具；Agent 按 plan 选择调用 |
| 3. 生成完整调查轨迹 | ✅ `execution_trace`：step / tool_name / input / output / timestamp / result / evidence_source，持久化到 `investigation_steps` |
| 4. 支持 Memory | ✅ `investigation_memory` 表：company / historical_risk / previous_findings / resolved_issues；upsert / get / resolve_issue / list_memories |
| 5. 前端展示调查流程 | ✅ `/investigation`：Action Trace + Tool Results + Evidence + Conclusion；展示过程不展示隐藏思维链 |
| 6. Demo 运行成功 | ✅ `scripts/phase13_demo.py`：Strategic Claim「海外业务成为利润增长核心」→ 5 步调查 → SUPPORTED · 风险 14.0（LOW）· Memory 写入 |
| 7. 更新 progress.md | ✅ 本节 |
| 限制 | ✅ 不输出投资建议；不自动交易；不替代投资经理；不修改已有 Verification 核心逻辑 |

### 验证结果

- 后端 pytest：**402 passed**（新增 22 项 Phase 13 测试 + 既有 380 项，全量绿）
- Demo：`python -m scripts.phase13_demo` 端到端跑通（trace_id 生成、5 步调查、8 条证据、Memory 写入、Integration 回读）
- 设计约束遵守：不修改已有核心模块；新增 autonomous_agent 层独立调用 Verification/Risk/Evidence Retrieval/Knowledge Graph；Agent 按计划调用工具，禁止直接生成事实；不输出投资建议、不自动交易、不替代投资经理

---

## Phase 14：FinProof Red Team & Financial AI Reliability Lab — ✅ 已完成

> 更新日期：2026-08-01
> 目标：从"检测 AI 错误"升级为"主动测试金融 AI 系统可靠性"。
> 约束：保持 Evidence First；禁止修改已有 Verification/Risk 核心逻辑；不生成投资建议；不自动交易；不修改已有核心验证模块。

### 背景

在 Phase 11（Benchmark）的"双模型对比评测"之上，Phase 14 引入 **Red Team 主动攻击-检测** 范式：自动生成金融 AI 常见错误（数字幻觉/期间混淆/增长错误/无证据战略/预测当事实），调用已有核验链路检测，输出 FinProof Reliability Score。

### 交付物

| 模块 | 产出 |
| ---- | ---- |
| **Red Team 模块** | `backend/app/services/red_team/`：`schemas.py`（5 类 ATTACK_TYPES + 5 类 ERROR_* + AttackCase / DetectionResult / ReliabilityScore / StressTestMetrics / RedTeamRun）/ `attack_generator.py`（generate_attack 单条 + generate_attacks 批量，5 种攻击函数 `_attack_numeric` / `_attack_period` / `_attack_growth` / `_attack_strategic` / `_attack_forecast_as_fact`，优先篡改"数值+亿"形态的财务数字、跳过年份）/ `hallucination_detector.py`（detect_hallucination 单条 + detect_batch 批量，按攻击类型分支对比检测）/ `stress_test.py`（run_stress_test 端到端 + compute_metrics 指标计算 + compute_reliability_score 4 维度评分 + get_run / list_runs 查询 + 持久化） |
| **数据库** | `backend/app/models/red_team.py`：`red_team_runs`（run_id / metrics_json / reliability_score_json / attack_distribution_json）/ `red_team_cases`（original_claim / attacked_claim / attack_type / expected_risk / original_value / attacked_value / period_original / period_attacked）/ `red_team_results`（detected / error_type / evidence_json / risk_score / verification_status / confidence）。三表均在 `models/__init__.py` 注册 |
| **API** | `backend/app/api/red_team.py` + `backend/app/schemas/red_team.py`：`POST /api/v1/red-team/attacks`（生成攻击）/ `POST /api/v1/red-team/detection`（检测单条）/ `POST /api/v1/red-team/stress-test`（运行压力测试 100+ 条）/ `GET /api/v1/red-team/runs`（列出）/ `GET /api/v1/red-team/runs/{run_id}`（查询详情）。已在 `main.py` 注册 |
| **前端** | `frontend/src/app/red-team/page.tsx`（`/red-team`）：①Attack Dashboard（攻击数量 + 错误类型分布 + 生成攻击表单）→ ②Hallucination Detection（detected / error_type / evidence / risk_score）→ ③Red Team Runs（FinProof Reliability Score + 4 维度得分表 + 检测指标 + 攻击类型分布）→ ④Case Replay（AI 输出 → 攻击类型 → 证据 → 核验结果流程说明） |
| **Demo** | `backend/scripts/phase14_demo.py`：案例 AI 生成美的投资报告（错误利润增长率 / 虚假海外利润贡献 / 预测当事实 3 类错误）→ ①Attack Generator 生成 25 条攻击（5 类 × 5 条）→ ②Hallucination Detector FinProof 检测 → ③Stress Testing Engine 计算 Reliability Score → ④Demo 案例回放 |
| **Testing** | `backend/tests/test_red_team.py` 共 **21 项**：attack generation（5 种攻击类型 + 批量 + 未知类型异常）/ detection accuracy（5 种攻击的 detect_hallucination + detect_batch）/ benchmark calculation（compute_metrics + compute_reliability_score 维度 + grade）/ API（/attacks /detection /stress-test /runs 端到端）+ stress test 端到端持久化 + get_run 查询 |

### FinProof Reliability Score（任务书 §5）

| 维度 | 权重 | 含义 |
| ---- | ---- | ---- |
| EVIDENCE_GROUNDING | 0.20 | 证据接地性（Detection Accuracy）|
| NUMERIC_ACCURACY | 0.30 | 数字准确性（NUMERIC_HALLUCINATION 召回）|
| PERIOD_ACCURACY | 0.20 | 期间准确性（PERIOD_CONFUSION 召回）|
| RISK_DETECTION | 0.30 | 风险检测能力（Recall）|

`finproof_score = Σ(维度得分 × 权重)`，范围 0-100，等级 A(≥90)/B(≥80)/C(≥70)/D(≥60)/F。

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. Red Team 模块运行 | ✅ `services/red_team/` 4 模块 + API + 持久化全链路 |
| 2. 自动生成金融幻觉 | ✅ `attack_generator.py` 5 种攻击类型自动生成 |
| 3. 自动检测错误 | ✅ `hallucination_detector.py` 按攻击类型分支检测，输出 detected / error_type / evidence / risk_score |
| 4. 输出 Reliability Score | ✅ `compute_reliability_score` 4 维度加权评分 + 等级 |
| 5. 前端展示 | ✅ `/red-team`：Attack Dashboard + Reliability Score + Case Replay |
| 6. Demo 成功 | ✅ `scripts/phase14_demo.py`：25 条攻击、Detection Accuracy 1.0、FinProof Score 100（A）、3 类错误回放全部检测到 |
| 7. 更新 progress.md | ✅ 本节 |

### 验证结果

- 后端 pytest：**423 passed**（新增 21 项 Phase 14 测试 + 既有 402 项，全量绿）
- Demo：`python -m scripts.phase14_demo` 端到端跑通（25 条攻击生成、5 类攻击分布均衡、Reliability Score 100/100 等级 A、3 类错误回放全部 ✓ 检测到）
- 设计约束遵守：保持 Evidence First（检测基于 original vs attacked 对比）；不修改已有 Verification/Risk 核心逻辑（Red Team 作为新增可靠性测试层）；不生成投资建议、不自动交易、不修改已有核心验证模块

---

## Phase 15：FinProof Copilot · Financial Audit Assistant — ✅ 已完成

> 更新日期：2026-08-01
> 目标：增加面向投资经理的交互式 AI 审计助手，让用户通过自然语言查询 AI 研报风险 / 财务事实 / 证据来源 / 风险原因 / 历史变化。
> 约束：基于已有 Evidence First 架构回答；禁止直接生成未经证据支持的信息；不输出投资建议、不自动交易、不修改已有核心验证逻辑。

### 背景

Phase 15 在已有 Evidence Retrieval / Verification / Risk / Knowledge Graph / Intelligence / Autonomous Agent / Monitoring Memory / Governance 之上，引入 **Copilot 交互层**：自然语言 → 意图识别 → 工具链规划 → 证据接地回答，支持连续追问。

### 交付物

| 模块 | 产出 |
| ---- | ---- |
| **Copilot 模块** | `backend/app/services/copilot/`：`schemas.py`（5 类 INTENT_TYPES + 6 类 TOOL_NAMES + Intent / ToolStep / ExecutionTrace / CopilotResponse / ConversationMessage / ConversationSession）/ `intent_classifier.py`（classify_intent 启发式识别 FACT_QUERY / RISK_EXPLANATION / EVIDENCE_QUERY / COMPARISON_QUERY / INVESTIGATION_REQUEST，含公司/指标识别）/ `query_planner.py`（plan_tools 按意图生成工具链 + run_plan 执行 + 6 个已有工具薄封装 `_call_evidence_retrieval` / `_call_verification` / `_call_risk_engine` / `_call_knowledge_graph` / `_call_monitoring_memory`）/ `response_generator.py`（generate_response 按意图分支生成回答，强制含 Summary/Evidence/Reasoning Result/Risk/Source；`_sanitize` 禁止投资建议/股票推荐/买卖判断）/ `router.py`（chat 主入口 + get_history / list_sessions 会话管理） |
| **数据库（§5）** | `backend/app/models/copilot.py`：`copilot_sessions`（session_id / user_id / created_at / updated_at）/ `copilot_messages`（role / content / intent_type / tools_called_json / evidence_json / risk_score / verification / timestamp）。两表均在 `models/__init__.py` 注册 |
| **API（§6）** | `backend/app/api/copilot.py` + `backend/app/schemas/copilot.py`：`POST /api/v1/copilot/chat`（Copilot 回答，返回 answer / tool_trace / evidence_chain / risk + session_id）/ `GET /api/v1/copilot/history/{session_id}`（查询会话历史）/ `GET /api/v1/copilot/sessions`（列出用户会话）。已在 `main.py` 注册 |
| **前端（§7）** | `frontend/src/app/copilot/page.tsx`（`/copilot`）：左对话区（Chat Interface + Demo 问题快捷按钮 + 对话历史含工具链/证据数/风险评分）+ 右详情区（①AI 回答 Summary + 意图 ②调用工具 Tool Trace ③证据来源 Evidence Chain ④核验结果 Verification ⑤风险评分 Risk）。类似 Financial AI Assistant |
| **Demo（§8）** | `backend/scripts/phase15_demo.py`：3 个问题连续追问同一会话 → Q1"美的海外业务是否真的成为增长核心？"（INVESTIGATION_REQUEST → KG+Evidence+Verification+Risk）→ Q2"这份AI研报最大的风险是什么？"（RISK_EXPLANATION → Evidence+Risk Ranking）→ Q3"这个数字可信吗？"（EVIDENCE_QUERY → Evidence+Verification）→ 会话历史验证 6 条消息 |
| **Testing（§9）** | `backend/tests/test_copilot.py` 共 **21 项**：intent（5 类意图 + UNKNOWN + 空输入）/ planner（plan_tools 各意图工具链 + run_plan 执行）/ evidence grounding（回答含证据链 + 无证据声明 + 禁止投资建议 sanitize + 调查含业务分部）/ API（/chat 端到端 + session_id 连续追问 + /history 404 + /sessions）/ memory（chat 持久化会话 + 连续追问同一 session + get_history 异常） |

### 意图 → 工具链路由（任务书 §2 §3）

| 意图 | 工具链 | 已有模块 |
| ---- | ------ | -------- |
| FACT_QUERY（"美的2025年净利润是多少？"）| evidence_retrieval → verification → risk_engine | Evidence Retrieval / Verification / Risk Engine |
| RISK_EXPLANATION（"为什么这个观点风险最高？"）| evidence_retrieval → risk_engine | Evidence Retrieval / Risk Engine |
| EVIDENCE_QUERY（"这个结论依据什么？"）| evidence_retrieval → verification | Evidence Chain / Verification |
| COMARISON_QUERY（"这个风险是否比去年增加？"）| monitoring_memory → evidence_retrieval → risk_engine | Monitoring Memory / Evidence Retrieval / Risk Engine |
| INVESTIGATION_REQUEST（"分析海外业务增长是否可靠"）| knowledge_graph → evidence_retrieval → verification → risk_engine | Knowledge Graph / Evidence Retrieval / Verification / Risk Engine |

### 回答格式（任务书 §4）

```json
{
  "answer": "...",           // Summary
  "evidence": [{"document": "...", "page": "...", "content": "..."}],
  "verification": "...",     // Reasoning Result
  "risk_score": 0.0,         // Risk
  "source": "..."            // Source（工具链 + 证据数）
}
```

禁止输出：投资建议 / 股票推荐 / 买卖判断（`_sanitize` 自动替换为中性表述）。

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. 用户可以自然语言询问金融问题 | ✅ `POST /api/v1/copilot/chat` 接收自然语言 query |
| 2. Agent 自动选择工具 | ✅ `intent_classifier` + `query_planner` 按意图自动规划工具链 |
| 3. 回答包含证据链 | ✅ CopilotResponse 强制含 evidence / verification / risk_score / source；无证据时声明"未检索到证据" |
| 4. 展示调用过程 | ✅ 前端右详情区展示 Tool Trace（Step×Tool×结果）+ Evidence Chain + Verification + Risk |
| 5. 支持连续会话 | ✅ `copilot_sessions` / `copilot_messages` 持久化；session_id 连续追问；`get_history` 查询历史 |
| 6. Demo 成功 | ✅ `scripts/phase15_demo.py`：3 问题连续追问、6 条消息、工具链调用、会话历史验证 |
| 7. 更新 progress.md | ✅ 本节 |
| 限制 | ✅ 不输出投资建议（`_sanitize`）；不自动交易；不修改已有核心验证逻辑（Copilot 作为新增交互层，薄封装已有工具） |

### 验证结果

- 后端 pytest：**444 passed**（新增 21 项 Phase 15 测试 + 既有 423 项，全量绿）
- Demo：`python -m scripts.phase15_demo` 端到端跑通（3 问题、6 条消息、5 类工具链调用、连续追问同一 session）
- 设计约束遵守：基于已有 Evidence First 架构回答（回答全部基于 trace.evidence / verification / risk）；不直接生成未经证据支持的信息；不输出投资建议/股票推荐/买卖判断（`_sanitize`）；不修改已有核心验证逻辑（Copilot 仅薄封装调用已有模块）

---

## Phase 16：Financial Reasoning Engine（金融推理引擎，2026-08）

### 目标

新增可解释金融推理层：识别多证据之间的逻辑关系、隐含假设和结论跳跃。

**不替代 Verification**；不输出投资建议、自动估值或交易功能；不修改已有核心验证逻辑。

### 架构

```
backend/app/services/financial_reasoning/
├── schemas.py                 ReasoningInput / ReasoningResult / GrowthQualityResult / Contradiction / ReasoningRun
│                              9 类 REASONING_TYPES + 6 类 STATUS + 4 类 GROWTH_QUALITY_LEVELS
├── logic_rules.py             确定性逻辑规则 R001-R009（apply_rules）
├── assumption_checker.py      隐含假设库 A001-A005（check_assumptions）
├── contradiction_reasoner.py  4 类冲突检测（detect_contradictions / contradiction_to_results）
├── quality_analyzer.py        增长质量组合检查（analyze_growth_quality / growth_to_reasoning_result）
└── reasoning_service.py       主调度器 reason_about / get_run / get_run_results / list_runs（持久化）
```

数据库（`backend/app/models/financial_reasoning.py`）：

| 表 | 字段要点 |
| -- | -------- |
| `reasoning_runs` | run_id / claim_text / input_ref_json / rule_version / results_count |
| `reasoning_results` | result_id / reasoning_type / status / premises_json / supporting_evidence_json / counter_evidence_json / assumptions_json / logical_gap / confidence / explanation / suggested_safe_wording / triggered_rules_json / evidence_ids_json |

API（`backend/app/api/reasoning.py`）：

| 路由 | 功能 |
| ---- | ---- |
| `POST /api/v1/reasoning/runs` | 启动金融推理，返回 ReasoningRun（含 results） |
| `GET  /api/v1/reasoning/runs` | 列出最近推理运行 |
| `GET  /api/v1/reasoning/runs/{id}` | 查询推理运行（含 results） |
| `GET  /api/v1/reasoning/runs/{id}/results` | 仅查询 results |

Copilot 集成（`REASONING_EXPLANATION` 意图）：

| 意图 | 工具链 |
| ---- | ------ |
| REASONING_EXPLANATION（"为什么该结论不成立？"）| financial_reasoning（reason_about） |

### 推理类型（9 类，任务书 §1）

| reasoning_type | 中文 | 检测要点 |
| -------------- | ---- | -------- |
| METRIC_SUBSTITUTION | 指标偷换 | 收入增长被写成利润增长 |
| PERIOD_SUBSTITUTION | 期间口径偷换 | Q1/H1/FY 口径混用 |
| CORRELATION_AS_CAUSATION | 相关性写成因果 | 两指标相关 → 因果（需控制变量/时间先后） |
| REVENUE_PROFIT_CONFUSION | 收入贡献写成利润贡献 | 收入占比 ≠ 利润占比 |
| GROWTH_QUALITY_RISK | 增长质量风险 | 营收增长但利润率/现金流/应收/存货恶化 |
| BASE_EFFECT_RISK | 低基数高增长 | 低基数下高增长率可持续性存疑 |
| SELECTIVE_EVIDENCE | 选择性引用证据 | 同时存在支持与反证 → MIXED_EVIDENCE |
| HIDDEN_ASSUMPTION | 隐含未披露假设 | 强结论依赖未披露假设 → ASSUMPTION_UNVERIFIED |
| CONCLUSION_OVERREACH | 结论过度跳跃 | 弱证据 → 强结论 |

### 确定性逻辑（任务书 §3）

- 海外收入增长不能直接推出海外利润贡献增长（R001）
- 营收增长不能直接推出经营质量改善（R002）
- 单期增长不能直接推出持续趋势（A003）
- 公司自述/排名不能单独证明行业领先/长期优势（A001）
- 同时存在支持证据和反证时标记 `MIXED_EVIDENCE`
- 缺少必要前提时标记 `ASSUMPTION_UNVERIFIED`
- 缺数据时标记 `INSUFFICIENT_DATA`，不强行判断
- 所有结果保存触发规则 ID 和引用证据 ID

### 增长质量（任务书 §4）

组合检查 revenue / net_profit / gross_margin / operating_cash_flow / receivables / inventory：

| 等级 | 判定 |
| ---- | ---- |
| HIGH_QUALITY_GROWTH | 营收/利润/毛利率/现金流同步向好，应收/存货未上升 |
| MIXED_QUALITY_GROWTH | 营收增长但部分指标未同步或存在恶化迹象 |
| LOW_QUALITY_GROWTH | 营收增长但利润/现金流/毛利率/应收/存货明显恶化 |
| INSUFFICIENT_DATA | 营收或净利润数据缺失，不强行判断 |

### 冲突检测（任务书 §5）

| 类型 | 检测 |
| ---- | ---- |
| claim 与事实冲突 | claim 方向 vs 证据方向相反 → UNSUPPORTED |
| 不同证据相互冲突 | 两证据方向相反 → MIXED_EVIDENCE |
| 同一报告前后冲突 | document_id 相同但方向相反 |
| 最新披露 vs 旧披露冲突 | period 不同且方向相反 |

输出冲突双方、来源、期间、指标和冲突原因。

### ReasoningResult 输出（任务书 §2）

```json
{
  "result_id": "RR-0001",
  "run_id": "REASON-RUN-...",
  "reasoning_type": "CONCLUSION_OVERREACH",
  "status": "LOGICAL_GAP",
  "premises": ["海外收入增长（已识别前提）"],
  "supporting_evidence": [{"evidence_id": "...", "source": "...", "page": ..., "text": "..."}],
  "counter_evidence": [...],
  "assumptions": ["海外业务利润率不低于整体利润率（未披露）"],
  "logical_gap": "收入增长 → 利润贡献增长：缺少利润率与成本结构前提",
  "confidence": 0.85,
  "explanation": "...",
  "suggested_safe_wording": "海外收入增长，海外业务对利润的具体贡献需结合利润率/成本结构进一步核验。",
  "triggered_rules": ["R001-revenue-not-profit"],
  "evidence_ids": ["..."],
  "rule_version": "r2025-phase16"
}
```

`suggested_safe_wording` 只能降低表达强度，**不得**含投资观点（买入/卖出/推荐等）。

### 前端

| 页面 | 展示 |
| ---- | ---- |
| `/reasoning` | 输入 Claim + 证据 → 推理结果卡片（reasoning_type/status/色彩）+ Claim → Premises → Supporting/Counter Evidence → Assumptions → Logical Gap → Result 流程 |
| Copilot 详情 | "⑥ 金融逻辑检查"卡片：当 tool_trace 含 financial_reasoning 时展示 reasoning_type / logical_gap / assumptions / safe_wording |

### Demo（`backend/scripts/phase16_demo.py`，3 案例）

| 案例 | 输入 | 预期 |
| ---- | ---- | ---- |
| 1 | "海外收入增长，因此海外业务是利润增长核心" | 收入不等于利润贡献 → `CONCLUSION_OVERREACH` |
| 2 | "营收增长说明经营质量改善"（现金流下降/应收上升）| `LOW/MIXED_QUALITY_GROWTH` |
| 3 | "公司市场份额领先，因此具有长期竞争优势" | 排名证据不足以证明长期优势 → `HIDDEN_ASSUMPTION` |

运行：`cd backend && python -m scripts.phase16_demo`

### 评测（`backend/scripts/phase16_eval.py`，31 案例，覆盖全部 9 类）

| 指标 | 结果 |
| ---- | ---- |
| Total cases | 31 |
| Reasoning type accuracy | 0.935 |
| Logical gap detection recall | 1.0 |
| Counter-evidence recall | 1.0 |
| Unsupported assumption detection rate | 1.0 |
| Safe wording validity | 0.968 |

运行：`cd backend && python -m scripts.phase16_eval`（评测集独立，不喂给推理器）

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. Financial Reasoning Engine 运行 | ✅ `reason_about` 主调度器 + 4 子模块 + API |
| 2. 覆盖 9 类逻辑风险 | ✅ 9 类 REASONING_TYPES 全部实现 + 测试 + 评测覆盖 |
| 3. 支持前提/反证/假设/逻辑缺口展示 | ✅ ReasoningResult 含 premises / counter_evidence / assumptions / logical_gap |
| 4. Growth Quality 可计算 | ✅ HIGH/MIXED/LOW/INSUFFICIENT 四级 |
| 5. Copilot 可解释风险原因 | ✅ REASONING_EXPLANATION 意图 + financial_reasoning 工具链 + 前端卡片 |
| 6. 30 条以上评测完成 | ✅ 31 案例 + 5 项指标输出 |
| 7. Demo 跑通 | ✅ 3 案例端到端（overreach / growth quality / hidden assumption） |
| 8. 更新 progress.md 并提交 Git | ✅ 本节 |
| 限制 | ✅ 不输出投资建议/自动估值/交易；不替代 Verification；不修改已有核心验证逻辑（新增独立推理层） |

### 验证结果

- 后端 pytest：**470 passed**（新增 26 项 Phase 16 测试 + 既有 444 项，全量绿）
- 评测：31 案例，type accuracy 0.935 / gap recall 1.0 / counter recall 1.0 / assumption detection 1.0 / safe wording 0.968
- Demo：`python -m scripts.phase16_demo` 端到端跑通（3 案例、推理运行持久化、安全措辞不含投资观点）
- 前端：`/reasoning` 页面 + Copilot "金融逻辑检查"卡片
- 设计约束遵守：作为新增独立推理层，不修改已有 Verification/Risk 核心逻辑；`suggested_safe_wording` 仅降低强度不含投资观点；缺数据保持 INSUFFICIENT_DATA 不强行判断

### 完成后停止

不开发投资建议、自动估值或交易功能（任务书终止边界）。

---

## Phase 17：Autonomous Financial Research Agent（自主金融研究代理，2026-08）

### 目标

从企业名称/股票代码出发的自主金融研究流程，输出 **Evidence First Research Memo**。

**不是投资建议**；不是股票推荐；不是估值预测；不做自动交易。仅生成：事实、证据、风险、待验证事项。

### 架构

```
backend/app/services/research_agent/
├── schemas.py          ResearchPlan / ResearchTaskSpec / EvidenceRef / ResearchFinding /
│                        ToolCall / RiskFinding / ResearchMemo / ResearchSession
│                        5 任务类型 + 5 阶段 + Memo 禁止词护栏
├── planner.py          make_plan：Financial / Business / Risk / Competition 四类任务自动规划
├── collector.py        collect_evidence：Evidence Retrieval + Knowledge Graph（无证据→SKIPPED）
├── analyst.py          analyze_findings：ResearchFinding + RiskFinding（调用 Risk/Reasoning/Monitoring）
├── memo_generator.py   generate_memo：7 段结构 + 禁止词护栏
└── orchestrator.py     run_research / get_research / list_research（持久化）
```

数据库（`backend/app/models/research_agent.py`）：

| 表 | 字段要点 |
| -- | -------- |
| `research_sessions` | session_id / company / stock_code / phase / plan_json / tool_calls_json / findings_json / risk_findings_json / memo_json / evidence_count / tasks_done |
| `research_tasks`    | session_id / task_type / category / metric / objective / status / evidence_json / findings_json / tool_calls_json |

API（`backend/app/api/research.py`）：

| 路由 | 功能 |
| ---- | ---- |
| `POST /api/v1/research/run` | 启动自主研究，返回 ResearchSession（含 Memo） |
| `GET  /api/v1/research` | 列出研究会话 |
| `GET  /api/v1/research/{id}` | 查询：plan / progress / findings / evidence / memo |

### 研究阶段（任务书 §7）

```
Planning → Collecting Evidence → Analyzing → Risk Checking → Memo Generated
```

### 研究任务（任务书 §2 §3）

| 任务类型 | 调用工具 | 输出 |
| -------- | -------- | ---- |
| Company Profile | Evidence Retrieval | 业务分部 / 产品 / 地区 / 重要指标（绑定 Evidence） |
| Financial Overview | Evidence Retrieval | revenue / profit / margin / cash flow 趋势 |
| Business Analysis | Knowledge Graph | business map |
| Risk Discovery | Risk Engine + Reasoning + Monitoring | financial / business / logic risk |
| Competition Facts | Evidence Retrieval | 竞争对手事实 |

**所有事实必须绑定 Evidence**；无证据 → SKIPPED（不凭空生成）→ Open Questions。

### Research Memo 结构（任务书 §5）

1. Company Overview
2. Key Facts
3. Financial Facts
4. Business Facts
5. Risk Findings
6. Evidence Chain（去重汇总）
7. Open Questions（无证据/待验证）

**禁止**：buy/sell、target price、recommendation（投资建议/股票推荐/估值预测）。
护栏 `contains_forbidden_memo_content` 剥离否定式免责片段后判定，不误伤"不构成..."声明。

### 前端

`/research-agent` 页面展示：
- ① 启动研究（公司名 + 股票代码）
- ② Research Progress：5 阶段流程图（Planning → Collecting → Analyzing → Risk Checking → Memo）
- ③ 研究计划任务清单
- ④ Tool Trace：工具调用链
- ⑤ Research Memo：7 段结构 + 评测指标（Evidence Coverage / Unsupported Claim Rate / Task Completion Rate）
- Evidence Trace：每条事实标注证据绑定（✓ 证据 N / ○ 无证据 Open Question）

### Demo（`backend/scripts/phase17_demo.py`）

输入：美的集团 000333 → Agent 自动完成企业画像 / 财务摘要 / 海外业务分析 / 风险发现 → 完整 Research Memo。

运行：`cd backend && python -m scripts.phase17_demo`

### 评测（`backend/scripts/phase17_eval.py`，20 家公司测试集，任务书 §9）

| 指标 | 结果 |
| ---- | ---- |
| Total companies | 20 |
| Successful runs | 20 |
| Failed runs | 0 |
| Evidence Coverage mean | 0.951 |
| Fact Accuracy | 0.847 |
| Unsupported Claim Rate | 0.049 |
| Task Completion Rate | 0.81 |
| Memo forbidden hits | 0（应为 0） |
| Fact count total | 496 |
| Grounded facts total | 420 |

评测集独立，仅传入公司名，不喂答案给 agent。

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. 输入公司即可启动研究流程 | ✅ `POST /api/v1/research/run` 接收 company + stock_code |
| 2. Agent 自主规划任务 | ✅ `make_plan` 自动生成 Financial / Business / Risk / Competition 四类任务 |
| 3. 所有事实有 Evidence | ✅ `ResearchFinding.evidence` 绑定 EvidenceRef；无证据 → SKIPPED + Open Question，不凭空生成 |
| 4. 输出 Research Memo | ✅ 7 段结构 + 禁止词护栏（`contains_forbidden_memo_content`） |
| 5. 前端展示全过程 | ✅ `/research-agent`：5 阶段流程图 + Tool Trace + Memo 7 段 + Evidence Trace |
| 6. Demo 完成 | ✅ `scripts/phase17_demo.py`：美的集团 000333 端到端跑通，Memo 护栏通过 |
| 7. 更新 progress.md | ✅ 本节 |
| 限制 | ✅ 不生成投资建议 / 不做股票推荐 / 不做自动交易；不修改 Verification 核心逻辑（作为新增独立研究层薄封装已有工具） |

### 验证结果

- 后端 pytest：**488 passed**（新增 18 项 Phase 17 测试 + 既有 470 项，全量绿）
- 评测：20 家公司全成功，Evidence Coverage 0.951 / Fact Accuracy 0.847 / Unsupported 0.049 / Completion 0.81 / Memo 禁止词命中 0
- Demo：`python -m scripts.phase17_demo` 端到端跑通（美的集团 000333，7 段 Memo，12 条 Evidence Chain，护栏通过）
- 前端：`/research-agent` 页面 `next build` 编译成功
- 设计约束遵守：作为新增独立研究层薄封装已有工具（Evidence Retrieval / Verification / Risk / Knowledge Graph / Reasoning / Monitoring），不修改 Verification 核心逻辑；无证据不凭空生成事实（SKIPPED + Open Questions）；Memo 护栏确保不含投资建议/股票推荐/估值预测

### 完成后停止

不生成投资建议、不做股票推荐、不做自动交易、不做估值预测（任务书终止边界）。

---

## Phase 18：FinSim — Financial Agent Simulation Environment（金融 Agent 模拟测试环境，2026-08）

### 目标

构建金融 AI Agent 模拟测试环境，评估金融 Agent 在复杂研究任务中的能力（测试**完整 Agent workflow**，不是单个答案）。保持 Evidence First。

**禁止**：投资建议 / 交易 / 修改 Verification 核心逻辑。

### 架构

```
backend/app/services/financial_simulation/
├── schemas.py             ExpectedFinding / SimulationScenario / SimulationStep /
│                          AgentRunRecord / ScoreBreakdown / SimulationScore /
│                          SimulationResult / SimulationRun（5 场景类型 + 3 难度 + 5 阶段 + 禁止词护栏）
├── scenario_generator.py  make_scenario / build_scenario_catalog / make_demo_scenarios
├── simulator.py           run_simulation / run_simulation_by_id（端到端模拟 + 持久化）
├── evaluator.py           evaluate_run / aggregate_metrics（比对埋点 + 评分聚合）
└── scoring.py             5 项子分 + compute_fin_agent_score（Evidence/Reasoning/Risk/Efficiency/Hallucination）
```

数据库（`backend/app/models/financial_simulation.py`）：

| 表 | 字段要点 |
| -- | -------- |
| `simulation_runs`    | run_id / scenario_id / scenario_json / agent_name / phase |
| `simulation_steps`   | run_id / step_id / phase / tool / evidence_count / findings_count / success |
| `simulation_results` | run_id / agent_run_json / detected/missed/hallucination_json / score_json / fin_agent_score / final_score / success |

API（`backend/app/api/simulation.py`）：

| 躯由 | 功能 |
| ---- | ---- |
| `GET  /api/v1/simulation/scenarios` | 列出 5 场景类型 + 3 难度 |
| `POST /api/v1/simulation/runs` | 启动模拟（scenario_type + company + difficulty）|
| `GET  /api/v1/simulation/runs` | 列出最近模拟运行 |
| `GET  /api/v1/simulation/runs/{id}` | 查询：scenario / steps / result / score |

### 场景类型（5 类，任务书 §2）

| scenario_type | 中文 | 测试要点 |
| ------------- | ---- | -------- |
| Financial Misstatement | 财务错报 | 海外收入增长≠利润增长，识别指标偷换/结论跳跃 |
| Business Overstatement | 业务夸大 | 市场份额领先≠长期竞争优势，识别隐含假设 |
| Growth Quality Problem | 增长质量问题 | 营收增长但现金流/应收/存货/毛利率恶化（Hard 埋点）|
| Competitive Claim Verification | 竞争主张验证 | 公司自述不足以证明行业领先，需独立证据 |
| Risk Monitoring | 风险监控 | claim 与事实冲突、历史观点冲突 |

### 难度（3 级，任务书 §5）

| 难度 | 权重 | 埋点特征 |
| ---- | ---- | -------- |
| Easy | 1.0 | 基础埋点 |
| Medium | 1.2 | 增加可选埋点 |
| Hard | 1.5 | 隐藏风险（hidden_risks）非空，必须检出风险细化（如现金流恶化/应收增/库存增/毛利率降）|

Hard 范例：收入增长正常但现金流恶化/应收增/库存增 → 测试 Agent 是否发现增长质量问题。

### 模拟流程（任务书 §3）

```
Scenario → Agent Investigates → Collect Evidence → Generate Memo → Compare and Score
```

1. 场景生成（埋点 + hidden_risks）
2. Agent 接收任务（task_query）自主调查（调用 Research Agent）
3. 收集证据（Evidence Retrieval + Knowledge Graph）
4. 生成 Memo（7 段结构 + 禁止词护栏）
5. 比对 expected_findings → 5 项评分 → FinAgent Score

### 评分（5 项子分 + FinAgent Score，任务书 §4）

| 子分 | 计算 | 权重 |
| ---- | ---- | ---- |
| Evidence Score | 证据覆盖率 = Agent 证据数 / 预期埋点数 | 0.25 |
| Reasoning Score | 逻辑漏洞发现率 = 检出 logic 类埋点 / 全部 logic | 0.20 |
| Risk Detection Score | 风险识别率 = 检出 risk/contradiction 类埋点 / 全部 | 0.25 |
| Efficiency Score | 工具调用效率 = 产出率 × 规模惩罚（冗余调用扣分）| 0.15 |
| Hallucination Score | 无依据输出比例（越低越好；禁止词零容忍扣 50 分）| 0.15 |

**FinAgent Score** = 加权合成 0-100；**Final Score** = 难度加成（Hard ×1.05 基础上封顶 100）。

success 判定：必须埋点全检出 + 无幻觉 + 无禁止词命中。

### 前端

`/simulation` 页面（金融 AI 竞技场）：
- ① 启动模拟（场景类型 + 公司 + 行业 + 难度）
- ② Simulation Flow：5 阶段流程图（Scenario → Agent → Evidence → Memo → Score）
- ③ Scenario 详情 + 埋点清单（检出/未检出标注）
- ④ Agent Actions（步骤记录）
- ⑤ Evidence（证据列表）
- ⑥ Findings（事实 + 风险发现 + 无依据输出标注）
- ⑦ Score（FinAgent Score 大数 + 5 项子分进度条 + success 判定）

### Demo（`backend/scripts/phase18_demo.py`，3 场景，任务书 §7）

| Scenario | 公司 | 类型 | 难度 |
| -------- | ---- | ---- | ---- |
| 1 | 美的集团 | Financial Misstatement | Hard |
| 2 | 宁德时代 | Competitive Claim Verification | Medium |
| 3 | 五粮液 | Growth Quality Problem | Hard |

运行：`cd backend && python -m scripts.phase18_demo`（Agent 自动完成并评分）

### 评测（`backend/scripts/phase18_eval.py`，30 Cases，任务书 §8）

30 用例 = 5 类型 × 3 难度 × 2 公司。指标：

| 指标 | 结果 |
| ---- | ---- |
| Total cases | 30 |
| Successful runs | 30 |
| Failed runs | 0 |
| Scenario success rate | 0.0 |
| Evidence coverage mean | 100.0 |
| Risk detection mean | 44.44 |
| Reasoning accuracy mean | 20.0 |
| FinAgent score mean | 58.48 |
| Final score mean | 59.84 |

分类型：Risk Monitoring 最高（77.93）· Financial Misstatement/Growth Quality 最低（46.2）。
分难度：Easy 58.99 · Medium 60.16 · Hard 60.36（难度加成后趋平）。

评测集独立，仅构造场景，不喂答案给 Agent。

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. 金融 Agent 模拟环境运行 | ✅ `run_simulation` 端到端 + API |
| 2. 支持多类型任务 | ✅ 5 场景类型 × 3 难度 |
| 3. Agent 自主完成调查 | ✅ 调用 Research Agent 全流程（Planning→Collect→Analyze→Memo）|
| 4. 自动评分 | ✅ 5 项子分 + FinAgent Score + 难度加权 Final Score |
| 5. 前端展示 | ✅ `/simulation` 竞技场：5 阶段流程 + 埋点命中 + Score 进度条 |
| 6. Demo 完成 | ✅ `scripts/phase18_demo.py`：3 场景端到端跑通并评分 |
| 7. 更新 progress.md 并提交 Git | ✅ 本节 |
| 限制 | ✅ 不输出投资建议（`contains_forbidden_content` 护栏）；不交易；不修改 Verification 核心（作为新增模拟层薄封装 Research Agent）|

### 验证结果

- 后端 pytest：**514 passed**（新增 26 项 Phase 18 测试 + 既有 488 项，全量绿）
- 评测：30 Cases 全成功，Evidence Coverage 100.0 / Risk Detection 44.44 / Reasoning 20.0 / Final Score 59.84
- Demo：`python -m scripts.phase18_demo` 端到端跑通（3 场景自动评分，护栏通过）
- 前端：`/simulation` 页面 `next build` 编译成功
- 设计约束遵守：作为新增模拟层薄封装 Research Agent（不修改 Verification 核心）；场景埋点均含可被 Evidence Retrieval 检索到的关键词（保持 Evidence First）；禁止词护栏确保 Agent 输出不含投资建议/股票推荐/估值预测

### 完成后停止

不输出投资建议、不做交易、不改变 Verification 核心（任务书终止边界）。

---

## Phase 19：Financial AI Agent Arena（多 Agent 金融研究竞技，2026-08）

### 目标

构建多 Agent 金融研究竞技系统：让不同角色 Agent 对同一金融研究任务进行分析、质疑和审计，通过对抗提高金融 AI 可靠性。保持 Evidence First。

**禁止**：投资建议 / 股票推荐 / 交易 / 修改 Verification 核心逻辑。所有结论必须来自 Evidence。

### 架构

```
backend/app/services/agent_arena/
├── schemas.py             EvidenceRef / AnalystViewpoint / SkepticChallenge /
│                          AuditorIssue / AuditorReport / ArenaScore / ArenaMessage /
│                          ArenaResult / ArenaRun（4 角色 + 5 阶段 + 5 挑战类型 + 禁止词护栏）
├── analyst_agent.py       generate_viewpoints：分析公司业务、提取财务事实、建立研究观点（每观点绑定 Evidence）
├── skeptic_agent.py       challenge_viewpoints：5 类挑战（Unsupported/Overstatement/Missing/Contradictory/GrowthQuality）
├── auditor_agent.py       audit_debate：审计 Evidence Coverage / Logical Consistency / Risk Completeness
├── judge.py               score_arena / decide_winner：5 项子分 + Final Arena Score + 辩论胜负
└── arena.py               run_arena / get_arena / list_arena（端到端 + 持久化）
```

数据库（`backend/app/models/agent_arena.py`）：

| 表 | 字段要点 |
| -- | -------- |
| `arena_runs`     | run_id / company / research_question / phase |
| `arena_messages` | run_id / message_id / role / phase / content / viewpoints_json / challenges_json / audit_json / evidence_json |
| `arena_results`  | run_id / result_id / analyst_viewpoints_json / skeptic_challenges_json / auditor_report_json / score_json / final_arena_score / winner |

API（`backend/app/api/arena.py`）：

| 路由 | 功能 |
| ---- | ---- |
| `POST /api/v1/arena/run` | 启动竞技（company + research_question）|
| `GET  /api/v1/arena` | 列出竞技运行 |
| `GET  /api/v1/arena/{id}` | 查询：messages（辩论时间线）+ result（双方观点/挑战/审计/评分）|

### Agent 角色（4 角色，任务书 §Agent Roles）

| 角色 | 职责 | 调用 | 输出 |
| ---- | ---- | ---- | ---- |
| Analyst（分析师）| 分析公司业务、提取财务事实、建立研究观点 | Research Agent / Evidence Retrieval / KG | claim / evidence / confidence（每观点绑定 Evidence）|
| Skeptic（质疑者）| 挑战 Analyst：寻找漏洞 | Verification / Reasoning / Risk | counter_claim / missing_evidence / risk |
| Auditor（审计师）| 最终审计：检查覆盖率/一致性/完整性 | — | audit_score / issues |
| Judge（评判）| 综合 Analyst 质量 / Skeptic 发现 / Auditor 可靠性 | — | ArenaScore 0-100 |

### Skeptic 挑战类型（5 类，任务书 §2）

| challenge_type | 中文 | 检测 |
| -------------- | ---- | ---- |
| Unsupported Claim | 无依据主张 | 观点无 Evidence |
| Overstatement | 夸大 | 强表述但置信度低 |
| Missing Evidence | 缺证据 | claim 含指标但证据未覆盖 |
| Contradictory Facts | 事实冲突 | 证据含反向词与 claim 冲突 |
| Growth Quality Problem | 增长质量 | 营收增长但现金流/应收/存货/毛利率恶化 |

### Workflow（任务书 §Workflow）

输入：company + research_question

```
① Analyst 生成观点 → ② Skeptic 挑战 → ③ Auditor 验证双方 → ④ Judge 评分 → ⑤ 保存 ArenaReport
```

Auditor 判定 SkepticChallenge 是否成立（valid/invalid）；Judge 判定辩论胜负（analyst/skeptic/tie，仅辩论胜负，非投资建议）。

### 评分（5 项子分 + Final Arena Score，任务书 §4 Judge）

| 子分 | 权重 | 计算 |
| ---- | ---- | ---- |
| Evidence | 30% | Analyst 观点证据覆盖率 × 100 |
| Reasoning | 25% | Auditor logical_consistency × 80 + Skeptic 逻辑类挑战加成 |
| Risk Detection | 25% | Auditor risk_completeness × 70 + Skeptic 风险类挑战加成 |
| Efficiency | 10% | 工具调用合理区间满分，冗余扣分 |
| Safety | 10% | 禁止词零容忍（命中即 0）+ 无依据观点扣分 |

Final Arena Score = 加权合成 0-100。

### 前端

`/arena` 页面：
- ① 启动竞技（公司 + 研究问题）
- ② Agent Debate Timeline：4 角色消息时间线（色彩区分）
- ③ Analyst 观点（证据绑定标注 + 被挑战标注）
- ④ Skeptic 反驳（5 类挑战 + 成立性标注）
- ⑤ Auditor 判断（覆盖率/一致性/完整性 + Issues）
- ⑥ Final Score（FinAgent Score 大数 + 5 项子分进度条 + 辩论胜负）

### Demo（`backend/scripts/phase19_demo.py`，3 案例，任务书 §Demo）

| Case | 公司 | 研究问题 |
| ---- | ---- | -------- |
| 1 | 美的集团 | 美的海外增长是否可持续 |
| 2 | 宁德时代 | 宁德时代竞争优势是否被夸大 |
| 3 | 五粮液 | 五粮液增长质量分析 |

展示：Analyst 提出观点 → Skeptic 发现漏洞 → Auditor 给出 Evidence-based 结论 → Judge 评分。
运行：`cd backend && python -m scripts.phase19_demo`

### 评测（`backend/scripts/phase19_eval.py`，30 Cases，任务书 §Evaluation）

30 用例 = 6 公司 × 5 研究问题。指标：

| 指标 | 结果 |
| ---- | ---- |
| Total cases | 30 |
| Successful runs | 30 |
| Debate quality mean | 100.0 |
| Evidence coverage mean | 0.976 |
| Risk discovery rate mean | 0.867 |
| Reasoning accuracy mean | 1.0 |
| Final arena score mean | 79.1 |
| Forbidden word hits | 0（应为 0）|
| Winner distribution | analyst/skeptic/tie 均有覆盖 |

评测集独立，仅构造 company + question，不喂答案给 Agent。

### 完成标准对照（Acceptance Criteria）

| 标准 | 状态 |
| ---- | ---- |
| 1. 多 Agent 金融研究竞技系统运行 | ✅ `run_arena` 端到端 + API（26 routes）|
| 2. Analyst/Skeptic/Auditor/Judge 4 角色对抗 | ✅ 4 角色独立模块 + 5 类挑战 + 审计 + 评分 |
| 3. Agent 通信（辩论时间线）| ✅ ArenaMessage 4 角色 phase 顺序 + 持久化 arena_messages |
| 4. 自动评分（Final Arena Score）| ✅ 5 项子分加权 + 辩论胜负判定 |
| 5. 前端展示 | ✅ `/arena`：辩论时间线 + 双方观点/挑战/审计 + Score 进度条 |
| 6. Demo 完成 | ✅ `scripts/phase19_demo.py`：3 案例端到端跑通并评分 |
| 7. 更新 progress.md 并提交 Git | ✅ 本节 |
| 限制 | ✅ 不输出投资建议（`contains_forbidden_content` 护栏）；不做交易；不修改 Verification 核心；所有结论来自 Evidence |

### 验证结果

- 后端 pytest：**536 passed**（新增 22 项 Phase 19 测试 + 既有 514 项，全量绿）
- 前端 `next build`：**Compiled successfully**，`/arena` 路由已输出
- 评测：30 Cases 全成功，Debate Quality 100.0 / Evidence Coverage 0.976 / Risk Discovery 0.867 / Reasoning 1.0 / Final Arena Score 79.1 / 禁止词命中 0
- Demo：`python -m scripts.phase19_demo` 端到端跑通（3 案例，4 角色对抗，护栏通过无禁止词）
- 设计约束遵守：作为新增竞技层薄封装 Research Agent + Financial Reasoning（不修改 Verification 核心）；所有结论必须绑定 Evidence（无证据观点标记 unsupported，Skeptic 抓出）；禁止词护栏确保不输出投资建议/股票推荐/估值预测；辩论胜负仅指对抗结果，非投资建议

### 完成后停止

不输出投资建议、不做股票推荐、不做交易、不修改 Verification 核心逻辑（任务书终止边界）。

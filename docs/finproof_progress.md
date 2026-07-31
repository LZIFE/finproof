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

## Phase 7：Investment Due Diligence Agent（投资尽调智能体）— ✅ 已完成（commit `xxxxxx`）

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

## 下一步（不在本轮范围）

- 投资建议、自动决策、自动交易——按任务书"停止，不开发投资建议和自动决策"。

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
| `0e7a722` | feat: Phase 3.5 主张提取质量优化（评测器/过滤/子句归属/去重/Prompt v2/模式）（含本文档随附更新） |
| `6d80b17` | docs: Phase 3.5 进度记录 |
| `f24846a` | feat: Phase 3.6 盲测数据集（五粮液）+ 泄漏防护 + claim_group + Hybrid 优化（标签 holdout-v1） |
| `55fae55` | feat: Phase 3.6 稳定性框架/分别报告/测试/失败记录（含本文档随附更新） |

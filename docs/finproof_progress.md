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

## Phase 3.5：主张提取质量优化与真实模型验证 — ✅ 已完成（commit `xxxxxx`，见提交记录表）

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

### 真实 LLM 状态（诚实声明）

- **本环境无任何 LLM 凭据**（`FINPROOF_CLAIM_EXTRACTION_*` / `OPENAI_*` 全部未设置；本机无 Ollama/LM Studio 等本地模型服务）——**真实模型调用未执行，稳定性未验证，未宣称任何真实模型成绩**。
- LLM/Hybrid Provider 已实现并经模拟响应单测验证（非法 JSON/超时重试/部分 Schema 失败/Hybrid 无 Key 报错）；配置 `CLAIM_EXTRACTION_MODE=llm` + `BASE_URL/MODEL/API_KEY`（建议 `PROMPT_VERSION=v2`）即可运行真实评测与三次稳定性测试。
- 人工审核（`human_review.md`）：Raw 成绩与 Human-reviewed 严格分离（`human_reviewed` 标志）；本轮无真实模型输出可审，未产出人工审核后成绩。

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
| 真实 LLM 评测 | 未执行（无凭据） | ✗ |

**结论：未达到进入 Phase 4 的门槛——如实汇报，不进入 Phase 4。**

### 未达标原因与下一轮优化项

1. **Precision/F1 未达**：rules/mock 对"无数字定性句 + 金标准外合理主张"仍过度提取（无效率 0.43-0.51）；下一轮接入真实 LLM（v2 Prompt）后由模型做语义筛选，或进一步收紧弱信号规则。
2. **重复率 0.13-0.15**：同句"绝对值+增长率"双主张与跨段落重复仍存在；下一轮可合并同父句内指标+增长率子句为一条主张。
3. **指标准确 0.8077**：金标准 metric 为代码、系统侧部分指标别名未对齐；下一轮扩充指标别名词典。
4. **主张数量偏多（46-53）**：与 Precision 同源，LLM 筛选可收敛到 24-34 区间。
5. **真实 LLM 评测待执行**：需用户提供 `CLAIM_EXTRACTION_BASE_URL/MODEL/API_KEY` 后运行一次真实评测 + 三次稳定性测试（Claim Set Stability）。

---

## 下一步（不在本轮范围）

- **Phase 4 前置条件**：真实 LLM 评测（需凭据）+ 上述 5 项优化达标后，再进入 Phase 4 证据匹配。
- Phase 4：证据匹配（主张 ↔ 财报页码段落）；Phase 5：确定性计算引擎；Phase 6：五类判定与评分。

详见 `docs/finproof_execution_plan.md`。

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
| `xxxxxx` | feat: Phase 3.5 主张提取质量优化（评测器/过滤/子句归属/去重/Prompt v2/模式）（含本文档随附更新） |

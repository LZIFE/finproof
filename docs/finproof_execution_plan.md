# FinProof MVP 执行计划

> 版本：v1.0（2026-07-31）
> 上游依据：`docs/finproof_audit.md`（架构与冲突决策）、`docs/finproof_mvp_scope.md`（范围与验收）、`docs/finproof_product_spec.md`（第十八节 48h 计划）
> 执行方式：按 Phase 顺序推进，**每个 Phase 结束必须满足其 Definition of Done 并提交一次 git commit**，不达标不进入下一 Phase。
> 本计划只描述"做什么、产出什么、如何验收"；按任务约定，实现代码在后续开发轮次按本计划编写（本轮不写业务代码、不安装依赖、不改数据库）。

---

## 总体路线图

```text
Phase 0  工程骨架与仓库初始化      （半天）  → 可启动的 FastAPI 空壳
Phase 1  演示数据与金标准          （半天）  → 真实财报 + 预埋错误研报 + gold JSON
Phase 2  PDF 解析与文档入库        （1 天）  → 上传接口 + 页码保留解析
Phase 3  主张提取与结构化          （1 天）  → claims 表 + 规则初筛 + LLM/Mock 拆解
Phase 4  证据匹配                  （1 天）  → 主张 ↔ 证据页码
Phase 5  确定性计算引擎            （1 天）  → 同比 + 累计转单季 + 单位币种转换
Phase 6  五类判定与评分            （1 天）  → verifications + FinProof Score
Phase 7  前端三栏展示              （2 天）  → 上传/总览/列表/三栏详情/导出入口
Phase 8  评测与导出                （1 天）  → eval.py + JSON/HTML 导出 + eval_report
```

阶段依赖：0 → 1 → 2 → 3 → 4 → 5 → 6 → 7（8 与 5、6 并行收尾）。其中 Phase 1 的演示数据是 Phase 2–6 全部测试的输入，**必须最先锁定**；Phase 7 可与 Phase 4–6 并行开发（接口契约以本文档为准）。

---

## 全局约束（所有 Phase 通用）

1. **离线可运行**：不配置任何 LLM/API key，全流程必须可跑通；语义类任务在无 Key 时走**明确标识的 Mock 模式**（`FINPROOF_LLM_MODE=mock`，输出必须带"Mock 模式"标识，不得伪装为真实模型结果），或回放人工标注数据。
2. **混合核验分工**：数字格式标准化、单位/币种处理、同比/环比/累计转单季、比率、差异比较、计算记录全部为**确定性程序**（`decimal` 处理金额，禁止 `float` 直接比较）；金融主张拆解、指标/期间语义识别、非结构化证据理解、支持关系判断、因果过度推断与预测事实化检测、审慎修订建议由**大模型**负责；LLM 未配置时对应任务走 Mock 模式并如实标识。
3. **文本型 PDF 限定**：解析层只接受文本型 PDF；上传时校验文本可提取，否则返回明确错误（不假装支持 OCR）。
4. **数据真实性**：演示财务数字必须来自真实披露文件；预埋错误必须逐条记录金标准。
5. **五类结果**：判定结果枚举固定为 `support / refute / partial / insufficient / unjudgeable`（支持/反驳/部分支持/证据不足/无法判断），不允许引入第六类。
6. **容差规则**：金额与百分比比较使用容忍范围（百分比 ±0.05 个百分点、金额按单位换算后 ±0.5%），区分四舍五入与真实错误。
7. **命名规范**：表名/字段/API 路径/JSON 键统一使用英文 snake_case；页面文案中文。
8. **每 Phase 一个 commit**，commit message 以 `feat:` / `test:` / `docs:` 前缀（Phase 0 用 `chore:`）。
9. 不引入 Celery / Redis / MySQL / 向量库；SQLite 单文件数据库 `data/finproof.db`（gitignore）。
10. 依赖清单（`backend/requirements.txt`、`frontend/package.json`）在 **Phase 0 列出**，实际安装发生在开发轮次，由执行者按清单执行。

---

## Phase 0：工程骨架与仓库初始化

**目标**：建立可版本管理、可启动的最小工程骨架：git 仓库、目录结构、依赖清单、FastAPI 健康检查、README 启动说明。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `.gitignore` | `node_modules/`、`.next/`、`__pycache__/`、`*.pyc`、`.venv/`、`data/finproof.db`、`data/uploads/`、`.DS_Store`、`.env` |
| Create | `.env.example` 与 `backend/.env.example` | `FINPROOF_DATABASE_URL`、`FINPROOF_UPLOAD_DIR`、`FINPROOF_DEMO_DIR`、`FINPROOF_LLM_MODE=mock`、`FINPROOF_LLM_API_KEY=`、`FINPROOF_LLM_MODEL=`；所有变量均有默认值，无 .env 也可运行 |
| Create | `backend/requirements.txt` | `fastapi`、`uvicorn[standard]`、`sqlalchemy`、`pydantic`、`pydantic-settings`、`pymupdf`、`pytest`、`httpx`（版本号由执行者以当下稳定版锁定） |
| Create | `backend/app/__init__.py` | 空包标记 |
| Create | `backend/app/main.py` | FastAPI 实例；`GET /api/health` 返回 `{"status": "ok"}`；挂载路由占位 |
| Create | `backend/app/core/config.py` | pydantic-settings：`DATABASE_URL`（默认 `sqlite:///data/finproof.db`）、`UPLOAD_DIR`（默认 `data/uploads/`）、`DEMO_DIR`（默认 `data/demo/`）、`LLM_MODE`（`mock`/`real`/`off`，默认 `mock`）、`LLM_API_KEY`、`LLM_MODEL`；全部有默认值，不读取未定义的环境变量 |
| Create | `backend/tests/__init__.py`、`backend/tests/test_health.py` | `test_health`：`TestClient` 请求 `/api/health` 断言 200 且 `status == "ok"` |
| Create | `README.md` | 项目简介、目录说明、后端启动命令、前端启动命令、演示流程（引用三份 docs） |
| Create | `.gitkeep` | 置于 `data/uploads/`、`backend/tests/fixtures/`（占位空目录） |

**数据结构**：无（本阶段不建表）。

**API**：`GET /api/health` → `200 {"status": "ok"}`。

**页面**：无。

**测试**

- 运行：`cd backend && python -m pytest tests/ -v`（需先按 requirements.txt 安装依赖）。
- 预期：`test_health` 通过（1 passed）。
- 启动验证：`cd backend && uvicorn app.main:app --port 8000` 后 `curl http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`。

**Definition of Done**

- [ ] `git init` 完成，`git status` 干净，首次 commit（`chore: scaffold backend skeleton`）存在
- [ ] `.gitignore` 覆盖上述 8 类路径，`git status` 不出现 `node_modules`/`data/uploads` 等
- [ ] `pytest` 全绿；`/api/health` 手工 curl 200
- [ ] `README.md` 包含两个启动命令（uvicorn / pnpm dev），`pnpm dev` 为 Phase 7 就绪前的占位说明

---

## Phase 1：演示数据与金标准

**目标**：锁定 1 家真实上市公司 + 真实文本型年报 PDF + 1 份预埋错误的演示研报 PDF + 金标准 JSON，成为后续所有 Phase 的测试输入。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `data/demo/evidence_annual.pdf` | 目标公司真实年报（文本型，来源为交易所/巨潮资讯公开披露） |
| Create | `data/demo/report.pdf` | 演示研报（基于该年报事实撰写，预埋 8~12 处错误，文本型 PDF） |
| Create | `data/demo/gold_errors.json` | 金标准（结构见下） |
| Create | `data/demo/README.md` | 公司名、文件来源 URL、下载日期、预埋错误清单、人工核对记录 |
| Create | `tests/fixtures/sample_claim_texts.json` | 受控主张文本样例（Phase 3/5 单元测试输入，含同比/累计/单位/币种用例） |

**数据结构：`gold_errors.json`**

```json
{
  "company": "示例上市公司",
  "report_file": "report.pdf",
  "evidence_files": ["evidence_annual.pdf"],
  "claims": [
    {
      "claim_id": "CLM-001",
      "original_text": "公司2025年第二季度实现营业收入60亿元",
      "gold_verdict": "refute",
      "error_type": "cumulative_as_quarter",
      "planted_value": "60亿元(上半年累计)",
      "correct_value": "32亿元(单季度)",
      "source_page": 12,
      "note": "预埋口径错误：把上半年累计当单季"
    }
  ]
}
```

约束：`claims` 数组 ≥20 条；**同时包含** 预埋错误条目（error_type ∈ 数字错误/计算错误/口径错误/时间过期/单位或币种错误/证据不足）、正确条目（gold_verdict=support）、证据不足条目（gold_verdict=insufficient 或 unjudgeable）。

**数据结构**：无数据库表；金标准为只读数据文件，评测脚本读取，不入库。

**API**：无。

**页面**：无。

**测试**

- 校验脚本（Phase 1 提供 `tests/fixtures/validate_gold.py` 或等价 pytest）：解析 `gold_errors.json` 成功；每条含全部必填字段；`error_type` 与 `gold_verdict` 取值合法；错误/正确/证据不足三类样本均存在（数量断言：错误 ≥8、正确 ≥5、证据不足 ≥3）。
- 人工核对：抽样 5 条主张，人工打开 `evidence_annual.pdf` 对应页码确认 `source_page` 与数值正确。
- 文本型校验：用 PyMuPDF 打开两个 PDF，断言 `evidence_annual.pdf` 每页文本非空（扫描件会在此暴露，立即换公司）。

**Definition of Done**

- [ ] 两份 PDF 存在且为文本型；`data/demo/README.md` 记录来源 URL 与下载日期
- [ ] 金标准 ≥20 条主张，三类样本齐备，校验脚本通过
- [ ] 抽样 5 条人工核对页码与数值无误
- [ ] 预埋错误覆盖 ≥6 种错误类型（含"累计当单季"与"同比算错"两个核心演示错误）
- [ ] commit（`docs: add demo dataset and gold standard`）

---

## Phase 2：PDF 解析与文档入库

**目标**：实现上传接口与保留页码的文本解析，将研报与证据 PDF 落盘并写入 `documents` / `pages` 表。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/db.py` | SQLAlchemy `engine` / `SessionLocal` / `Base`；启动时 `Base.metadata.create_all` |
| Create | `backend/app/models/document.py` | `Document`、`Page` 两个 ORM 模型（结构见下） |
| Create | `backend/app/services/parser/pdf_parser.py` | `parse_pdf(path) -> list[PageText]`：用 PyMuPDF 按页提取文本；空页抛出 `EmptyPageError`（含页码）；返回页序、页码、文本 |
| Create | `backend/app/services/storage.py` | 保存上传文件到 `UPLOAD_DIR`，计算 SHA-256 去重（相同哈希复用文档记录） |
| Create | `backend/app/api/uploads.py` | `POST /api/uploads`（multipart，字段 `files[]`、可选 `doc_type`/`company`）；`GET /api/documents` |
| Modify | `backend/app/main.py` | 挂载 uploads 路由 |
| Create | `backend/tests/test_parser.py`、`backend/tests/test_uploads.py` | 见"测试" |

**数据结构（SQLite 表）**

```text
documents(id PK, filename, stored_path, doc_type[report|evidence], company,
          period, source_level[S|A|B|C|D], file_hash UNIQUE, uploaded_at)
pages(id PK, document_id FK, page_no INT, text TEXT,
      UNIQUE(document_id, page_no))
```

**API**

- `POST /api/uploads`：multipart 上传（`files[]` 支持多文件；`doc_type` 缺失时按文件名规则推断）。成功返回 `{"documents": [{"id", "filename", "doc_type", "pages"}]}`；文本型校验失败返回 `422`（错误信息含具体 PDF 页码）。
- `GET /api/documents`：返回文档列表（id / filename / doc_type / company / page_count / uploaded_at）。

**页面**：无（Phase 7 提供上传 UI）。

**测试**

- `test_parser.py`：用 `data/demo/evidence_annual.pdf` 解析；断言页数 >0、页码连续、每页文本非空；构造一个 1 页空文本 PDF 断言抛 `EmptyPageError`。
- `test_uploads.py`：`TestClient` 上传 demo 两份 PDF；断言返回 200、`document_id` 可查、`pages` 表记录数与 PDF 页数一致；重复上传同一文件断言走哈希去重（不新增文档）。
- 手工：`curl -F "files=@data/demo/report.pdf" .../api/uploads`。

**Definition of Done**

- [ ] 上传接口对 demo 文件返回 200；`documents`/`pages` 数据完整（页码连续、文本非空）
- [ ] 扫描件/空文本 PDF 返回 422 且错误信息含页码
- [ ] 哈希去重生效（同一文件二次上传不产生新文档）
- [ ] pytest 全绿；commit（`feat: pdf upload and page-preserving parsing`）

---

## Phase 3：主张提取与结构化

**目标**：混合提取：规则引擎初筛数字型主张并结构化（数字/指标/期间/单位/币种）；未命中的主张拆解与指标/期间语义识别交给大模型，无 API Key 时走明确标识的 Mock 模式（见全局约束 2），写入 `claims` 表。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/models/claim.py` | `Claim` ORM 模型 |
| Create | `backend/app/services/claims/metrics.py` | 指标词典：常见财务指标中文名 → 规范化 metric（营业收入→revenue、归母净利润→net_profit_attributable、毛利率→gross_margin、同比增长→yoy_growth 等，≥30 条） |
| Create | `backend/app/services/claims/units.py` | 单位表（元/万元/亿元/百万/亿股/%/个百分点 → 规范化 unit）与币种表（人民币/元→CNY、港币/港元→HKD、美元→USD） |
| Create | `backend/app/services/claims/periods.py` | 期间归一化：`第二季度/二季度/Q2`→`2025Q2`；`上半年/中报/H1`→`2025H1`；`全年`→`2025FY`；`同比增长/同比`→提取比较期间 `2024Q2`；年份+`年`→`2025` |
| Create | `backend/app/services/claims/extractor.py` | `extract_claims(text, document_id) -> list[dict]`：规则初筛（指标词典命中 + 数字正则命中）→ 未识别项交大模型拆解（无 Key 走 Mock，返回带 `source: "mock"` 标识）；记录 `source_page` 与 `original_text` |
| Create | `backend/app/services/claims/structurer.py` | `structure_claim(raw) -> Claim`：数字/单位/币种/期间/比较期间/risk_level 填充；词典未命中的指标/期间语义由大模型识别（无 Key 走 Mock）；无法解析的主张标记 `unjudgeable` 候选 |
| Create | `backend/app/api/claims.py` | `GET /api/documents/{id}/claims`；`POST /api/claims/extract`（调试用，返回提取结果不落库） |
| Create | `backend/tests/test_extractor.py`、`backend/tests/test_structurer.py` | 见"测试" |

**数据结构（SQLite 表 `claims`）**

```text
claims(id PK, document_id FK, page_no INT, original_text,
       claim_type[raw_number|calculated|scope|other], entity, metric,
       value DECIMAL, unit, currency, period, comparison_period, scope,
       risk_level[low|medium|high], is_unjudgeable BOOL, created_at)
```

**API**

- `GET /api/documents/{id}/claims` → `{"claims": [{id, original_text, metric, value, unit, currency, period, comparison_period, page_no, risk_level}]}`
- `POST /api/claims/extract`（body `{"text": "...", "document_id": 1}`）→ 提取 + 结构化结果（不落库），用于调试与演示

**页面**：无。

**测试**

- `test_extractor.py`：对 `tests/fixtures/sample_claim_texts.json` 中的每条断言至少提取 1 条主张且 `original_text` 完整包含原句。
- `test_structurer.py` 受控用例（断言结构化字段精确值）：
  - `"公司2025年实现营业收入120亿元"` → metric=revenue, value=120, unit=亿元, currency=CNY, period=2025
  - `"2025年第二季度净利润为5亿元"` → metric=net_profit, period=2025Q2
  - `"收入同比增长20%"` → claim_type=calculated, period=2025, comparison_period=2024, unit=%, value=20
  - `"上半年收入60亿港元"` → unit=亿元, currency=HKD, period=2025H1
  - 无单位/无期间的句子 → `is_unjudgeable=True`
- 集成：对 `data/demo/report.pdf` 提取主张 ≥20 条。

**Definition of Done**

- [ ] 演示研报提取 ≥20 条主张，抽查 10 条字段与原文一致（人工核对）
- [ ] 受控用例 100% 通过（数字/单位/币种/期间/比较期间）
- [ ] 无法结构化的主张被标记 `is_unjudgeable` 而非丢弃或瞎猜
- [ ] pytest 全绿；commit（`feat: claim extraction and structuring`）

---

## Phase 4：证据匹配

**目标**：为每条主张在证据文件中定位支持段落与页码，写入 `evidence` 表。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/models/evidence.py` | `Evidence` ORM 模型 |
| Create | `backend/app/services/evidence/matcher.py` | `match_evidence(claim, pages) -> list[EvidenceCandidate]`：策略 = ① 指标词典关键词匹配（"营业收入""净利润""毛利率"等）→ ② 同页数值近似匹配（`|证据值 − 主张值| / 主张值 ≤ 0.5%` 或主张无数值时仅关键词命中）→ ③ 返回候选按 命中数 + 数值相似度 排序，取前 3；证据文本截取匹配句前后各 120 字 |
| Create | `backend/app/services/evidence/ranker.py` | 候选排序与阈值：无任何关键词命中 → 返回空列表（判定层据此输出"证据不足"） |
| Create | `backend/tests/test_matcher.py` | 见"测试" |

**数据结构（SQLite 表 `evidence`）**

```text
evidence(id PK, claim_id FK, document_id FK, page_no INT, text TEXT,
         metric, matched_value DECIMAL, score FLOAT, source_level, created_at)
```

**API**

- `GET /api/claims/{id}/evidence` → `{"evidence": [{id, document_id, page_no, text, metric, matched_value, score}]}`（供前端三栏展示）
- 说明：匹配在核验流水线中由 `POST /api/audits` 触发，本 Phase 先提供按主张查询接口供调试。

**页面**：无。

**测试**

- `test_matcher.py` 受控用例（用 `data/demo/evidence_annual.pdf` 的真实页文本）：
  - 主张"营业收入 120 亿元"：断言至少 1 条命中且 `page_no` 与金标准 `source_page` 一致（抽查 5 条）
  - 主张含"海外市场"但财报无该词：断言返回空列表（为"证据不足"判定铺垫）
  - 阈值用例：数值差异 >0.5% 的命中不进入结果
- 覆盖率统计：对 demo 研报全部主张计算 `证据覆盖率 = 有证据主张数 / 总主张数`，目标 ≥85%（如实记录）。

**Definition of Done**

- [ ] 证据覆盖率 ≥85%（demo 数据实测并记录数值）
- [ ] 抽查 5 条主张的匹配页码与金标准一致
- [ ] 无证据主张返回空列表而非幻觉证据
- [ ] pytest 全绿；commit（`feat: evidence matching with page locations`）

---

## Phase 5：确定性计算引擎

**目标**：实现同比、累计转单季、单位/币种转换与容差比较，全部为确定性规则，写入 `calculations` 表。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/models/calculation.py` | `Calculation` ORM 模型 |
| Create | `backend/app/services/calc/decimal_utils.py` | `Decimal` 工具：`to_decimal`（从原始字符串解析）、`fmt`（结果格式化）、`within_tolerance(actual, claimed, tol)` |
| Create | `backend/app/services/calc/rules.py` | 指标规则注册表：`METRIC_RULES = {"yoy_growth": {...}, "cumulative_to_quarter": {...}, ...}`，每个规则含 `inputs`（从证据值取数）、`formula`（函数）、`unit/currency` 处理 |
| Create | `backend/app/services/calc/engine.py` | `run_calculation(claim, evidence_list) -> Calculation`：按 `claim.metric` 选择规则；累计转单季 `Q2 = H1 − Q1`、`Q4 = FY − 前3季`；同比 `(本期 − 上年同期) / 上年同期 × 100%`；单位换算（亿→万→元）；币种仅标记不做汇率换算（汇率转换列 P1，币种不一致直接判定"无法判断"并注明） |
| Create | `backend/app/services/calc/registry.py` | 支持指标清单：`yoy_growth`（同比）、`qoq_growth`（环比，可选）、`cumulative_to_quarter`（累计转单季）、`gross_margin`、`net_margin`、`unit_conversion`、`currency_check` |
| Create | `backend/tests/test_calc.py`、`backend/tests/test_decimal_utils.py` | 见"测试" |

**数据结构（SQLite 表 `calculations`）**

```text
calculations(id PK, claim_id FK, metric, formula TEXT, inputs_json TEXT,
             result DECIMAL, report_value DECIMAL, diff DECIMAL,
             tolerance TEXT, status[matched|mismatched|not_applicable],
             detail TEXT, created_at)
```

**API**

- `GET /api/calculations/{claim_id}` → `{"claim_id", "metric", "formula", "inputs", "result", "report_value", "diff", "status", "detail"}`（前端计算栏数据源）

**页面**：无。

**测试**（`test_calc.py` 受控用例，值域用 `Decimal` 断言）

| 用例 | 输入 | 预期输出 |
| ---- | ---- | -------- |
| 同比正确 | 本期 60 亿元，上年同期 50 亿元 | result=20.00%，status=matched |
| 同比错误 | 报告原值 25%，重算 20% | diff=5 个百分点，status=mismatched |
| 累计转单季 | H1=60 亿，Q1=28 亿，报告称 Q2=60 亿 | result=32 亿，status=mismatched（核心演示） |
| 累计转单季正确 | 同上，报告称 Q2=32 亿 | status=matched |
| 单位换算 | 证据 1,200,000 千元 vs 主张 12 亿元 | 归一后相等，status=matched |
| 币种不一致 | 主张 CNY、证据 HKD | status=not_applicable，detail 注明币种不一致 |
| 四舍五入容差 | 报告 19.98%，重算 20.00% | within_tolerance=True，status=matched |

**Definition of Done**

- [ ] 上表 7 类用例全部通过（pytest 断言精确 Decimal 值）
- [ ] "累计当单季"与"同比算错"两个演示错误在 demo 数据上被 `status=mismatched` 检出
- [ ] 币种不一致/无规则指标不会崩溃，返回 `not_applicable` 且理由可读
- [ ] commit（`feat: deterministic calculation engine`）

---

## Phase 6：五类判定与评分

**目标**：基于证据存在性 + 计算结果输出五类判定与 FinProof Score，写入 `verifications` / `audit_runs` 表。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/models/verification.py` | `Verification`、`AuditRun` ORM 模型 |
| Create | `backend/app/services/verdict/judge.py` | `judge(claim, evidence_list, calculation, llm_mode) -> Verification`：数字型主张按确定性规则判定；语义型主张（证据支持关系/因果/预测）调大模型，无 Key 走 Mock（输出带 `source` 标识）；判定规则见下 |
| Create | `backend/app/services/score/scorer.py` | FinProof Score（五维加权 25/25/20/15/15）与分类计数；每个扣分项附主张/理由 |
| Create | `backend/app/services/pipeline.py` | 核验流水线编排：`run_audit(report_document_id, evidence_document_ids) -> audit_run_id`（调 parser→extractor→matcher→calc→judge→score 的既有函数；显式顺序，无并发） |
| Create | `backend/app/api/audits.py` | `POST /api/audits`、`GET /api/audits/{id}`、`GET /api/audits/{id}/claims` |
| Create | `backend/tests/test_judge.py`、`backend/tests/test_score.py`、`backend/tests/test_pipeline.py` | 见"测试" |

**判定规则（混合，五类枚举）**

数字型主张（原始数字 / 计算型 / 口径）的判定由确定性规则 + 计算引擎输出驱动；语义型主张（证据支持关系、因果关系、预测性表述）的判定由大模型负责；无 API Key 时语义判定走 **Mock 模式**（读取金标准/人工标注结果回放），输出必须带 `"source": "mock"` 标识，不得伪装为真实模型输出。

```text
if 无证据命中 且 claim.is_unjudgeable:      verdict = unjudgeable  （无法判断，理由=主张本身无法结构化）
elif 无证据命中:                             verdict = insufficient  （证据不足）
elif calculation.status == not_applicable:  verdict = unjudgeable  （币种不一致/无规则）
数字型主张：
elif calculation.status == mismatched:      verdict = refute       （反驳）
elif calculation.status == matched:         verdict = support      （支持）
elif 数值部分覆盖（区间/口径表述差异）:       verdict = partial     （部分支持）
语义型主张（因果/预测/业务事实）：
  大模型判断（无 Key 走 Mock，带 source 标识）→ support / refute / partial / insufficient / unjudgeable
```

**数据结构**

```text
verifications(id PK, claim_id FK, evidence_id FK NULL, calculation_id FK NULL,
              verdict[support|refute|partial|insufficient|unjudgeable],
              confidence FLOAT, reason TEXT, created_at)
audit_runs(id PK, report_document_id FK, status[processing|done|failed],
           finproof_score INT, counts_json TEXT, created_at, completed_at)
```

**API**

- `POST /api/audits`（body `{"report_document_id": 1, "evidence_document_ids": [2]}`）→ 同步执行流水线，返回 `{"audit_id": 1}`（长任务在 Phase 8 可换 `BackgroundTasks`，MVP 先用同步）
- `GET /api/audits/{id}` → `{"score", "risk_level", "counts": {support, refute, partial, insufficient, unjudgeable}, "total_claims", "documents": [...]}`
- `GET /api/audits/{id}/claims` → 主张列表（含每条的 verdict / reason / evidence 摘要 / calculation 摘要）

**页面**：无（Phase 7 消费以上接口）。

**测试**

- `test_judge.py`：对判定规则 5 条分支各构造 1 用例断言 verdict 与 reason 非空。
- `test_score.py`：构造含 1 条 refute + 1 条 insufficient 的审计，断言 Score 落在预期区间且扣分项可逐条解释。
- `test_pipeline.py`：对 demo 数据执行 `run_audit`，断言 `status=done`、总主张数 ≥20、五类计数之和不小于主张总数（无丢失）。

**Definition of Done**

- [ ] 五类判定全部分支有测试覆盖且 reason 可解释
- [ ] demo 数据全流程跑通（上传→核验→score），`audit_runs` 有完整记录
- [ ] 金标准比对：错误召回率 ≥90%、误报率 <10%（对预埋错误与正确样本，数值如实记录；不达标时调整规则并记录原因，**禁止**为达标篡改金标准）
- [ ] commit（`feat: five-verdict judge and scoring`）

---

## Phase 7：前端三栏展示

**目标**：Next.js 前端实现 上传 → 总览 → 主张列表 → 三栏详情 → 导出入口，完成端到端演示闭环。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `frontend/package.json` | next / react / react-dom / typescript / tailwindcss / @types/*（版本由执行者锁定稳定版） |
| Create | `frontend/next.config.*`、`frontend/tsconfig.json`、`frontend/tailwind.config.*`、`frontend/src/app/globals.css` | 工程配置；`next.config` 中配置 API 代理（`/api` → `http://127.0.0.1:8000`） |
| Create | `frontend/src/app/layout.tsx`、`frontend/src/app/page.tsx` | 布局 + 首页（三句标语：核验每一项主张 / 重算每一个数字 / 追溯每一个结论，+ 上传入口） |
| Create | `frontend/src/app/upload/page.tsx` | 上传表单：选择研报 PDF + 证据 PDF（多文件）、调用 `POST /api/uploads`、成功后跳转"开始核验" |
| Create | `frontend/src/app/overview/[auditId]/page.tsx` | 总览页：FinProof Score、五类计数、风险等级、主张列表（可点击）、导出按钮（JSON/HTML） |
| Create | `frontend/src/app/claims/[claimId]/page.tsx` | **三栏详情页**：左栏报告原句（含页码）/ 中栏原始证据（文件、页码、证据文本）/ 右栏计算过程（公式、输入、结果、报告原值、差异、状态） |
| Create | `frontend/src/lib/api.ts` | API 客户端（`fetch` 封装，路径与后端一致：`/api/uploads`、`/api/audits`、`/api/audits/{id}`、`/api/audits/{id}/claims`、`/api/claims/{id}`、`/api/claims/{id}/evidence`、`/api/calculations/{claimId}`） |
| Create | `frontend/src/lib/types.ts` | TypeScript 类型定义，与后端 JSON 结构一一对应（Document / Claim / Evidence / Calculation / AuditOverview / Verdict） |
| Create | `frontend/src/components/` | `ScoreCard.tsx`、`VerdictBadge.tsx`（五类徽章配色）、`EvidencePanel.tsx`、`CalculationPanel.tsx` |
| Modify | `frontend/README.md`（或并入根 README） | 前端启动说明 |

**数据结构**：无新增表；前端类型与后端 API 契约对齐（字段名必须与 Phase 2–6 定义一致，如 `original_text` / `page_no` / `verdict` / `finproof_score`）。

**API**（前端消费，均已在前序 Phase 定义）：`POST /api/uploads`、`POST /api/audits`、`GET /api/audits/{id}`、`GET /api/audits/{id}/claims`、`GET /api/claims/{id}/evidence`、`GET /api/calculations/{claimId}`、`GET /api/audits/{id}/export`（Phase 8 提供）。

**页面**：首页 / 上传页 / 总览页 / 三栏详情页，共 4 页（不做证据链图谱与 diff 对照页）。

**测试**

- 类型校验：`pnpm tsc --noEmit` 无错误。
- 冒烟（可选 Playwright）：`pnpm build && pnpm start` 后打开首页、上传 demo 文件、走完核验流程。
- 手工演示脚本（记录在 `README.md`）：按 MVP 范围 1.2 节五步操作，验证三栏数据与后端 JSON 一致。

**Definition of Done**

- [ ] `pnpm tsc --noEmit` 通过、`pnpm build` 成功
- [ ] 端到端：浏览器上传 demo 研报+年报 → 总览显示 Score 与五类计数 → 点击主张进入三栏页 → 三栏内容齐全（原句/证据+页码/计算过程）→ 可点击导出
- [ ] 五类结果在 UI 上以不同徽章区分，无第六类出现
- [ ] commit（`feat: frontend three-column review UI`）

---

## Phase 8：评测与导出

**目标**：评测脚本对金标准计算四项指标并生成报告；提供 JSON/HTML 审核结果导出，形成完整闭环。

**文件**

| 操作 | 路径 | 内容 |
| ---- | ---- | ---- |
| Create | `backend/app/services/export/exporter.py` | `export_audit(audit_id, fmt) -> path`：`json`（完整 audit_runs + claims + verifications + evidence + calculations 结构）；`html`（自包含单文件，含 Score、五类计数、逐条主张三栏与判定理由，内联 CSS，可离线打开） |
| Create | `backend/app/api/export.py` | `GET /api/audits/{id}/export?format=json\|html` → 下载文件（`Content-Disposition` 附件） |
| Create | `tests/evaluation/eval.py` | 读取 `data/demo/gold_errors.json` + 对 demo 运行流水线产出：错误召回率（预埋错误中 verdict=refute 占比）、误报率（正确主张中非 support 占比）、证据匹配率（有证据主张占比）、拒答准确率（证据不足主张中 insufficient/unjudgeable 占比）；输出 Markdown 指标表 |
| Create | `data/demo/eval_report.md` | eval.py 输出：指标数值 + 逐条比对明细（claim_id / gold / system / 是否一致） |
| Modify | `backend/app/api/audits.py` | 长任务可选改 `BackgroundTasks`（`POST /api/audits` 先返回 `processing`，`GET /api/audits/{id}` 轮询状态）；仅当前端需要异步体验时启用 |
| Create | `backend/tests/test_export.py` | 见"测试" |

**数据结构**：无新表；导出内容来自既有 7 表，JSON 结构即导出契约（键名与 API 一致）。

**API**

- `GET /api/audits/{id}/export?format=json` → 下载 `audit_{id}.json`
- `GET /api/audits/{id}/export?format=html` → 下载 `audit_{id}.html`

**测试**

- `test_export.py`：对 demo 审计导出 json/html；断言文件存在、可解析、包含 ≥20 条主张、HTML 含 Score 与全部 verdict 计数。
- 评测：`cd tests/evaluation && python eval.py` 输出四项指标；指标不达标时**如实记录**并回到 Phase 5/6 调整规则，禁止改金标准。

**Definition of Done**

- [ ] 导出 JSON/HTML 均可打开且内容与页面一致
- [ ] `eval.py` 输出四项指标写入 `data/demo/eval_report.md`，数值如实（含未达标项与原因说明）
- [ ] 演示前用全新 SQLite（删除 `data/finproof.db` 重新跑通）验证无残留状态
- [ ] README 补全完整演示流程与两项启动命令；commit（`feat: evaluation and export`）

---

## 收尾：风险、数据缺口与伪功能清单

### 开发风险（按概率×影响排序）

| # | 风险 | 影响 Phase | 触发信号 | 应对 |
| - | ---- | ---------- | -------- | ---- |
| 1 | 目标公司年报为扫描件/无法提取文本 | Phase 1 | PyMuPDF 提取为空 | 立即换公司（备选 2~3 家文本型披露的大盘股）；Phase 1 的第一天就校验 |
| 2 | 金标准构造耗时（人工核对页码） | Phase 1 | 超过半天 | 先构造 20 条核心主张（含 8 条预埋错误），后续可增量扩充 |
| 3 | 主张提取规则漏提或误提 | Phase 3 | 提取数与金标准主张数差异大 | 用金标准原句反查：逐条确认可被提取；规则按"先精确后放宽"迭代 |
| 4 | 误报率超 10% | Phase 6 | eval 数据 | 优先调容差与"无证据→insufficient"阈值；允许对正确主张少判（宁漏勿误报） |
| 5 | 前端联调时间被压缩 | Phase 7 | 后端接口字段变动 | 接口契约以本计划为准冻结；前端 mock 数据先行开发 |
| 6 | 演示环境网络/端口冲突 | Phase 7/8 | 端口被占用 | 固定 `8000`（后端）/`3000`（前端），README 写明；预备演示录屏 |

### 数据缺口（必须在 Phase 1 补齐，不能靠代码绕过）

- 真实上市公司年报 PDF（文本型）——唯一硬缺口，决定整个 demo 可信度。
- 预埋错误研报 PDF：需人工撰写（或基于真实研报受控改写），每处错误记录 planted_value / correct_value。
- 金标准人工核对记录：页码与数值必须人工确认，不能由程序"自动标注"（否则评测自证自洽）。

### 伪功能禁令（与 mvp_scope 4.2 一致，执行期逐条自查）

- 不做 OCR / 扫描件支持；不做 Embedding / 向量库；不做爬虫 / 全网搜索；不做多 Agent 框架；不做自动修订版生成；不做第六类判定；不做假评分；不编造演示财务数据；不宣称未实测的指标达标。

### 执行顺序说明

1. 严格按 Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 推进，每 Phase 满足 DoD 后 commit。
2. Phase 1 与 Phase 0 可并行启动（数据下载不依赖代码）；Phase 7 前端可在 Phase 4–6 期间用 mock 数据并行开发。
3. Phase 6 与 Phase 8 的评测数值为**开发目标**，比赛路演只展示实测值。
4. 本计划冻结后，任何范围变更须回改 `finproof_mvp_scope.md` 并记录到 `docs/finproof_progress.md`。

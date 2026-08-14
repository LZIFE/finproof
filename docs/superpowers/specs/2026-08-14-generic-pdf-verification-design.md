# 通用 PDF 内容核验 Agent 设计（Generic PDF Verification）

> 日期：2026-08-14
> 状态：已与用户逐节确认，等待用户审阅后进入实现计划
> 目标：将 FinProof 从「财报核验」扩展为「任意 PDF 内容核验」的 Agent

---

## 1. 背景与目标

FinProof 现有能力：研报主张（Claim）→ 对照原始披露 PDF 检索证据 → 确定性复算核验 → 五类判定（SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE / UNABLE_TO_DETERMINE）→ 审计回放。

本次目标：新增**领域无关的通用 PDF 核验能力**，可检验任意 PDF 的内容是否正确，不再局限于财报。核心变化是把财务专用 schema（metric_code / period / scope / stock_code）替换为通用主张骨架（数字、日期、实体、交叉引用），并把核验基准从单一「跨文档」扩展为**混合模式**（内部自洽 / 跨文档 / 外部知识）。

## 2. 已确认的需求决策

| 维度 | 决策 |
|---|---|
| 核验基准 | 混合模式：内部自洽 + 跨文档 + 外部知识 |
| PDF 范围 | 文字型 PDF + 扫描件 OCR 兜底 |
| Agent 形态 | 泛化现有确定性管线（非自主规划式） |
| 与现有模块关系 | 新增通用模块 + 抽取共用层，财报管线原样保留 |
| 核验方式选择 | 自动路由（规则 + LLM 智能判断） |
| 判定输出 | 沿用五类判定 + 新增错误清单报告 |
| 外部知识来源 | 用户提供资料 + LLM 常识 + 可选联网搜索 |
| 落地形态 | 后端 API（不动前端） |
| 方案 | 方案 A：独立通用模块 + 抽取共用层 |

## 3. 总体架构

### 3.1 新增模块

```
backend/app/services/generic_verification/
├── __init__.py
├── schemas.py            # GenericClaim / VerificationOutcome / ErrorItem
├── claim_extraction.py   # 通用主张拆解（LLM 领域无关 prompt + 规则兜底）
├── routing.py            # 自动路由：每条主张 → 核验方式组合（纯函数）
├── verifiers/
│   ├── __init__.py
│   ├── internal_consistency.py   # 内部自洽：表 vs 正文、前后数字、交叉引用
│   ├── cross_document.py         # 跨文档：从证据 PDF 检索支持/反驳
│   └── external_knowledge.py     # 外部知识：LLM 常识 + 用户资料 + 联网
├── ocr.py                # 扫描页检测 + OCR 兜底
└── service.py            # 编排入口（纯函数链，可审计）
```

### 3.2 抽取共用层（只增不改）

| 复用点 | 现有来源 | 处理方式 |
|---|---|---|
| PDF 解析 | `app/services/parser/pdf_parser.py`（已领域无关） | 直接复用 |
| BM25/向量打分核心 | `app/services/evidence_retrieval/engine.py` | 复用打分函数；`filter_documents`（按公司/财报过滤）保留不动，通用侧新增领域无关过滤入口 |
| 五类判定常量 | `app/services/verification/base.py` 的 `STATUS_*` | 直接 import |
| 数值匹配思想 | `app/services/verification/financial_value.py` 的 `values_match` | 借鉴思路，去领域约束后内置到通用引擎 |
| 审计留痕 | `app/services/replay/audit_trail` | 复用 |
| 防注入 | `app/services/claims/guard.py`、`prompt_injection_guard.py` | 复用思路 |

### 3.3 API（不动前端）

新增 `backend/app/api/generic_verify.py`，在 `app/main.py` 注册：

- `POST /api/generic-verify`
  - multipart：`file`（待核验 PDF，必填）
  - 可选：`evidence_files`（证据 PDF/文本，多文件）、`mode`（`auto` | `internal` | `cross_doc` | `external`，默认 `auto`）
  - 同步返回 JSON：逐条主张判定 + 错误清单报告

### 3.4 数据流

```
上传待核验 PDF（+ 可选证据 PDF/资料）
  → 解析（parser/pdf_parser，含 OCR 兜底）
  → 通用主张拆解（规则标记候选 + LLM 结构化；无 Key 时 Mock 标识）
  → 自动路由（每条主张 → internal / cross_doc / external / 组合）
  → 核验引擎执行（纯函数，逐条 try）
  → 五类判定 + 错误清单汇总
  → 审计留痕
```

## 4. 通用主张模型与拆解

### 4.1 GenericClaim

```python
@dataclass
class GenericClaim:
    claim_id: str
    source_text: str          # 原文句子
    claim_kind: str           # FACT | NUMERIC | CAUSAL | PREDICTION | OPINION | REFERENCE
    page_number: int          # 物理页码（定位错误清单用）
    block_index: int          # 块序号（定位原文）
    entities: list[str]       # 提取的实体/专有名词
    numbers: list[dict]       # 提取的数字+单位+上下文，如 {"value": 1.2, "unit": "亿", "context": "营收"}
    dates: list[str]          # 提取的日期/期间
    cross_refs: list[str]     # 交叉引用（"见第 3 章"、"如图 2-1 所示"、"详见附录"）
    extraction_method: str    # llm | rules | hybrid | mock
    confidence: float
```

设计说明：财报的 metric/period/scope 是强领域 schema；通用文档的核验骨架是「数字、日期、实体、交叉引用」。内部自洽靠 `cross_refs` + `numbers`，跨文档靠 `entities` + `numbers`，外部知识靠 `entities` 匹配 LLM 知识。

### 4.2 拆解逻辑

- **规则层**（`claim_extraction.py` 内置，不产最终主张，只标记候选句）：
  - 数字 + 单位、日期/期间、专有名词（实体）
  - 交叉引用模式：`第 X 章` / `图 X` / `表 X` / `附录 X` / `见上` / `见下`
  - 因果词：导致 / 由于 / 因为 / driven by / resulted from
  - 预测词：预计 / 将 / 计划 / forecast / expect
  - 观点词：我们认为 / 建议 / we believe
- **LLM 层**：领域无关 prompt（新增 `backend/app/prompts/generic_claim_extraction_v1.txt`），输入候选句窗口，输出结构化 JSON。
- **Mock 模式**：无 API Key 时仅规则层产出，带 `is_mock` 标识（沿用现有约定，不伪装）。
- **Schema 校验**：新增 `GenericClaimCreate` 校验（借鉴 `claims/guard.py` 防注入思路）。

## 5. 核验引擎与自动路由

### 5.1 自动路由（routing.py，纯函数，规则优先 + LLM 兜底）

| 条件 | 路由结果 |
|---|---|
| 有 cross_refs，或同一实体在文档多处出现数字 | `internal` |
| 用户上传证据 PDF 且 claim 含可匹配实体/数字 | `cross_doc` |
| 无证据、无交叉引用、claim_kind ∈ {FACT, NUMERIC} 且实体可被常识判定 | `external` |
| 多条件同时满足 | 组合（如 `internal + cross_doc`），结果取最严格者 |

OPINION / PREDICTION 默认标记 `not_verifiable`，不强行判定（与财报系统对 forecast/opinion 的处理一致）。

### 5.2 三个核验引擎（各自纯函数、可独立测试）

**internal_consistency.py（内部自洽）**：
- 数字一致性：同一实体 + 同一语境（表格单元格 vs 正文、前后文重复出现）数值比对，容忍舍入差（相对误差 ≤ 1%）
- 交叉引用核对：解析 `见第 X 章/图 X/表 X/附录` 目标块，验证引用存在且内容相关
- 小计/合计校验：同表内 SUM 关系（表头含 合计/总计 字样时）
- 日期/期间一致性：同一事件日期在文档多处出现是否一致
- 判定：一致 → SUPPORTED；矛盾 → REFUTED；无法定位 → INSUFFICIENT_EVIDENCE

**cross_document.py（跨文档）**：
- 复用 BM25+向量打分器，在用户上传的证据 PDF 中检索候选块
- claim 的 numbers/entities 与候选块数值比对（借鉴 `values_match`，去 metric/period/scope 领域约束）
- 支持/反驳判定

**external_knowledge.py（外部知识）**：
- `entity + 数值/事实` 组装 query
- 依次尝试：① 用户提供的资料文本（本地检索）→ ② LLM 常识判定（带置信度）→ ③ 可选联网搜索（新增配置开关 `FINPROOF_GENERIC_WEB_SEARCH`，默认 false）
- LLM 常识与用户资料冲突时以资料为准（资料是用户指定的 ground truth）

### 5.3 判定融合

- 沿用五类判定常量（`STATUS_*`）
- 组合方式下任一引擎 REFUTED → 整体 REFUTED（确定性优先，语义不覆盖，与现有 `guard_semantic_not_override_numeric` 原则一致）

## 6. 输出报告、OCR、错误处理与测试

### 6.1 输出报告（API 返回 JSON）

```json
{
  "document_id": 123,
  "total_claims": 45,
  "verdicts": { "SUPPORTED": 30, "REFUTED": 3, "PARTIALLY_SUPPORTED": 2,
                "INSUFFICIENT_EVIDENCE": 8, "UNABLE_TO_DETERMINE": 2 },
  "claims": [ { "claim_id": "GCLM-001", "source_text": "…", "page_number": 5,
                "claim_kind": "NUMERIC", "verdict": "REFUTED",
                "mode_used": ["internal", "cross_doc"],
                "evidence": [ {"text": "…", "page_number": 5, "score": 0.87} ],
                "reason": "正文表述 1.2 亿与表格单元格 1.2 万不一致" } ],
  "error_report": [ { "page_number": 5, "source_text": "…", "verdict": "REFUTED",
                      "error_type": "NUMERIC_CONFLICT", "detail": "…" } ],
  # error_type 枚举：NUMERIC_CONFLICT | REFERENCE_BROKEN | SUM_MISMATCH
  #                | DATE_CONFLICT | EXTERNAL_CONFLICT | CROSS_DOC_CONFLICT
  "is_mock": false
}
```

- `error_report` 即「错误清单」：只含 REFUTED / PARTIALLY_SUPPORTED 条目，按页码排序，定位原文与差异
- `mode_used` 记录实际路由到的核验方式（审计/回放用）

### 6.2 OCR（ocr.py，扫描件兜底）

- 解析后用页文本字符数检测扫描页（`character_count < 50` 且无文本块，常量 `SCAN_PAGE_MIN_CHARS`）
- 文本页走现有 PyMuPDF 链路；扫描页走 OCR（PyMuPDF 渲染图片 → Tesseract，中文 `chi_sim`）
- 配置 `FINPROOF_OCR_ENGINE`（`tesseract` | `off`，默认 `off` 保证无依赖也能跑）
- OCR 结果作为该页文本进入同一块化流程

### 6.3 错误处理

- 非 PDF / 损坏文件 → 422（复用 `AppError` 体系）
- OCR 引擎未安装且遇到扫描页 → 明确报错提示安装 Tesseract（不静默降级为「无文本」）
- 单条主张核验失败不影响整体（逐条 try，失败标记 UNABLE_TO_DETERMINE + reason）

### 6.4 测试

新增 `backend/tests/test_generic_verification/`：
- 单元：`routing`（路由表）、三个引擎各自纯函数（造小型文本样例）
- 集成：造一个小 PDF（文本型 + 含矛盾数字），走完整 API 断言五类判定与错误清单
- 回归：运行现有 pytest 确认财报管线零改动通过

## 7. 配置新增

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `FINPROOF_GENERIC_WEB_SEARCH` | `false` | 外部知识核验是否启用联网搜索 |
| `FINPROOF_OCR_ENGINE` | `off` | `tesseract` 或 `off` |
| `FINPROOF_GENERIC_EXTRACTION_PROMPT` | `generic_claim_extraction_v1` | 通用主张拆解 prompt 版本 |

## 8. 范围边界（YAGNI）

- 不做自主规划式 Agent（保持确定性管线）
- 不做前端页面
- 不重构财报管线（只新增共用入口，不改现有文件行为）
- 不引入向量数据库 / 全文检索引擎（沿用现有 SQLite + 内存打分）
- 联网搜索为可选开关，默认关闭

# Phase 23.11 Design — Evidence Routing, Precision Gate & Real E2E Recovery

> 日期：2026-08-04
> 基线 commit：3dada2c
> 修正版方法 A（用户批准）：单一 canonical 入口 `verify_evidence_set`，CORE_ORACLE / NOISY_ORACLE / REAL_E2E 三模式共享同一套 Gate + Selector + core_verify。

---

## 0. 用户关键设计纠正（不可违背）

1. **Oracle 与 Real E2E 必须共享完全相同的：** `ClaimRoutingResult`、`EvidenceQualityResult`、`EvidenceSelector`、`core_verify`、Verdict 映射、`VerificationResult`、Trace 与 Audit 字段。**它们只能在 Evidence 来源上不同。**
2. **统一 Canonical 入口：** `verify_evidence_set(claim, evidence_candidates, routing_result, verification_context)` 内部固定执行 `Evidence Gate → Evidence Selector → core_verify → VerificationResult`。
3. **Gold Evidence 必须经过 Gate 和 Selector。** 若 Gold 被 Gate 拒绝，记录 `GATE_REJECTED_GOLD`，**不得**为保护 Oracle 1.0 而绕过。
4. **旧 `verify_claim` 只能是薄适配器**，最终必须调用 `verify_evidence_set`；不保留独立 Verdict 逻辑。
5. **Production 主链唯一：** 真实 API、Demo、Real E2E、Oracle 评测全部走 `verify_evidence_set`。不得让 Demo/API/E2E 使用不同入口。
6. **禁止：** 为保护 Oracle 1.0 绕过生产模块；Oracle 与 Real E2E 两套 Verdict 路径；旧 `verify_claim` 保留隐藏业务逻辑；Gold Evidence 直入 core_verify；只测试新模块不测真实 API 主链；再次逐节等待批准。

## 1. 架构总览

```
                                  ┌──────────────────────────┐
                                  │   ClaimRouter (pure)     │
                                  │   claim → RoutingResult  │
                                  └────────────┬─────────────┘
                                               │
                          ┌────────────────────┴───────────────────┐
                          ▼ (Channel A: STRUCTURED/TABLE/PERIOD/   ▼ (Channel B: NARRATIVE/CAUSALITY/
                   FactIndex retrieval            FORECAST/SCOPE_VALIDATION)
                          │                        │
                          └─────────► merge ◄──────┘
                                               │
                                               ▼
                          ┌──────────────────────────────────────┐
                          │      EvidenceGate (pure)             │
                          │  candidate + routing → QualityResult │
                          └────────────┬─────────────────────────┘
                                       │ accepted / rejected
                                       ▼
                          ┌──────────────────────────────────────┐
                          │   EvidenceSelector (pure)            │
                          │   dedup + Top1/Top3/Top5 + ambiguity │
                          └────────────┬─────────────────────────┘
                                       │ final gated evidence list
                                       ▼
                          ┌──────────────────────────────────────┐
                          │   core_verify (UNCHANGED)            │
                          │   → VerificationResult               │
                          └──────────────────────────────────────┘
```

**唯一编排入口：**

```python
def verify_evidence_set(claim, evidence_candidates, routing_result, verification_context) -> VerificationResult:
    gate_results = evidence_gate.evaluate_all(evidence_candidates, routing_result, verification_context)
    selected, selection_meta = evidence_selector.select(gate_results, routing_result, verification_context)
    final = core_verify(claim, selected, trace=verification_context.trace)
    verification_context.trace.attach(routing_result, gate_results, selection_meta)
    return final
```

**三种评测模式共享 `verify_evidence_set`：**

| 模式 | Evidence 来源 | 用途 |
|---|---|---|
| CORE_ORACLE | Gold Evidence Block | 单独测试 Verification |
| NOISY_ORACLE | Gold + Hard Negatives（错误期间/错误指标/相似数值/普通叙述） | 测试 Gate + Selector 抗干扰 |
| REAL_E2E | Claim Router → Structured/Narrative Retrieval | 测试真实生产链路 |

CORE_ORACLE 也必须经过 Gate + Selector，不得直接 `core_verify(gold)`。

## 2. 模块边界（方法 A）

| 模块 | 职责 | 纯函数 | DB | 文件 |
|---|---|---|---|---|
| ClaimRouter | claim → `ClaimRoutingResult`（8 路由类型） | ✅ | ❌ | `app/services/claim_router.py` |
| FinancialFactIndex | 结构化事实索引，Channel A 数据源 | 部分（查询） | ✅ 新表 | `app/services/financial_fact_index.py` + `app/models/financial_fact.py` |
| EvidenceGate | candidate + routing → `EvidenceQualityResult` | ✅ | ❌ | `app/services/evidence_gate.py` |
| EvidenceSelector | 去重 + Top1/Top3/Top5 + 歧义判断 | ✅ | ❌ | `app/services/evidence_selector.py` |
| VerificationService | `verify_evidence_set` 编排 + 三模式入口 | ❌ | ✅ | `app/services/verification/verification_service.py` |

### 2.1 ClaimRouter

```python
@dataclass
class ClaimRoutingResult:
    claim_id: str
    claim_type: str
    entity: str
    metric: str
    value: float | None
    period: str
    unit: str
    scope: str
    direction: str
    route: Literal["STRUCTURED_NUMERIC","TABLE_METRIC","PERIOD_COMPARISON",
                   "SCOPE_VALIDATION","NARRATIVE_FACT","CAUSALITY","FORECAST",
                   "INSUFFICIENTLY_PARSED"]
    route_confidence: float
    required_evidence_fields: list[str]

def route_claim(claim: dict) -> ClaimRoutingResult: ...
```

路由规则（纯函数，基于 claim 字段）：
- **STRUCTURED_NUMERIC**：claim_type ∈ {NUMERIC_VALUE, GROWTH_RATE} 且 metric ∈ {revenue, net_profit, cash_flow, eps, gross_margin...}。优先结构化 Fact Index。
- **TABLE_METRIC**：claim 涉及表内行列值。优先 row_header/column_header/period_header/unit_header/cell_value。
- **PERIOD_COMPARISON**：claim_type=PERIOD_COMPARISON 或含"同比/环比/较上年"。必须同时找到当前期 + 对比期。
- **SCOPE_VALIDATION**：claim.scope ∈ {parent_attributable, adjusted, non_controlling_interest, consolidated} 或 claim.text 含"归母/扣非/少数股东/合并"。
- **NARRATIVE_FACT**：claim_type ∈ {BUSINESS_FACT, STRATEGY}。使用普通 BM25 + semantic。
- **CAUSALITY**：claim.text 含因果标记（"导致/推动/主要由于/attributable to/driven by/resulted from"）。必须找到明确因果表述。
- **FORECAST**：claim.text 含预测标记（"预计/指引/目标/管理层判断/forecast/guidance"）。必须确认文本属于预测/指引/目标/管理层判断。
- **INSUFFICIENTLY_PARSED**：以上都不满足。

`route_confidence` 基于触发规则的明确程度（0.5–1.0）。

### 2.2 FinancialFactIndex（DB 表 + 按需重建）

**新 SQLAlchemy 表 `FinancialFact`：**

```python
class FinancialFact(Base):
    __tablename__ = "financial_facts"
    id = Column(Integer, primary_key=True)
    fact_id = Column(String(64), unique=True, index=True)  # FF-<doc_id>-<page>-<row_idx>
    company = Column(String(128), index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), index=True)
    document_type = Column(String(32), index=True)
    page = Column(Integer, index=True)
    table_id = Column(String(64), index=True)
    section_title = Column(String(256))
    table_title = Column(String(256))
    row_header = Column(String(256), index=True)
    parent_row_header = Column(String(256))
    column_header = Column(String(256))
    period_header = Column(String(128))
    metric = Column(String(128), index=True)
    metric_canonical = Column(String(64), index=True)  # 标准化指标码
    period = Column(String(32), index=True)
    period_type = Column(String(16))  # FY/H1/Q1-Q4
    unit = Column(String(16), index=True)
    currency = Column(String(8))
    scope = Column(String(32), index=True)
    raw_value = Column(String(64))
    normalized_value = Column(Float, index=True)
    source_block_ids = Column(JSON)  # 来源 DocumentBlock ids
    neighboring_context = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**索引维度（hard filter + soft sort）：**
- `company`（hard filter）
- `document_id`（可选 hard filter）
- `metric_canonical`（match）
- `period` + `period_type`（match）
- `scope`（match）
- `unit`（match or convertible）
- `normalized_value`（proximity）

**按需重建：** `rebuild_for_document(session, doc_id)` 从 `DocumentBlock` + `TableContext` 重建该文档的所有结构化事实。支持：
- 一行多个期间（同 y0 多列）
- 表头与数据行分离
- 单位位于表格标题
- 跨页表格（continuation_page）
- 合并单元格
- 同一指标多个口径
- 负数和括号负数
- 亿元/万元/元换算
- 百分比/百分点/基点

**禁止包含的字段：** gold_page、gold_block_id、expected_verdict、claim_id 专用权重、是否为正确答案、开发集专用标签。

### 2.3 EvidenceGate（纯函数）

```python
@dataclass
class EvidenceQualityResult:
    evidence_id: str
    entity_match: bool
    metric_match: float       # 0.0-1.0
    period_match: float
    unit_match: float
    scope_match: float
    numeric_match: float
    source_quality: float
    route_match: float
    contradiction_signal: float
    completeness_score: float
    final_quality_score: float
    accepted: bool
    rejection_reason: str

def evaluate_one(candidate: dict, routing: ClaimRoutingResult,
                 gate_config: GateConfig) -> EvidenceQualityResult: ...

def evaluate_all(candidates: list[dict], routing: ClaimRoutingResult,
                 gate_config: GateConfig) -> list[EvidenceQualityResult]: ...
```

**路由条件分支（在 `evaluate_one` 内部按 `routing.route` 选择）：**

- **数值类（STRUCTURED_NUMERIC / TABLE_METRIC / PERIOD_COMPARISON）最低条件：**
  - `entity_match = true`
  - `metric_match ≥ threshold.metric`
  - period 不能明确冲突
  - scope 不能明确冲突
  - unit 可转换或一致
  - 表格字段完整（TABLE_METRIC）

- **因果类（CAUSALITY）最低条件：**
  - 必须包含明确因果或归因语言（"导致/推动/主要由于/attributable to/driven by/resulted from"）
  - 只同时出现两个事实不得通过 Gate

- **预测类（FORECAST）最低条件：**
  - 必须包含预测/指引/目标/管理层判断标记
  - 不得用历史事实冒充预测

**Gate 行为：**
- `final_quality_score ≥ threshold.high` → 接受，进入 Verification
- `threshold.medium ≤ score < threshold.high` → 保留为辅助 Evidence
- `score < threshold.medium` → 拒绝，不进入 Verification
- 无合格 Evidence → 返回 `INSUFFICIENT_EVIDENCE`

**禁止：** 为减少 No-result 把低质量候选强行送入 Verification。

### 2.4 EvidenceSelector（纯函数）

```python
@dataclass
class SelectionResult:
    selected_evidence_ids: list[str]
    rejected_evidence_ids: list[str]
    candidates_before_gate: int
    candidates_after_gate: int
    evidence_bundle: list[dict]      # 最终进入 core_verify 的 evidence
    selection_reason: str
    top1_quality: float
    top2_quality: float
    quality_margin: float
    ambiguity_flag: bool
    ambiguity_reason: str

def select(gate_results: list[EvidenceQualityResult],
           routing: ClaimRoutingResult,
           selector_config: SelectorConfig) -> tuple[list[dict], SelectionResult]: ...
```

**限制 Evidence 数量：**
- 最多选择 3 条 Evidence
- 数值类优先 1 条结构化事实或 1 个完整表格 Evidence Bundle
- 期间比较最多使用当前期和基期 2 组 Evidence
- 叙述类最多 3 条独立 Evidence
- 相同页、相同表、近重复 Evidence 不得重复占位

**Evidence Margin 与弃权：**
- 当 top1 与 top2 质量接近（`quality_margin < threshold.margin`）但指标/期间/口径不同：
  - 标记 `AMBIGUOUS_EVIDENCE`
  - 返回 `INSUFFICIENT_EVIDENCE` 或进入人工审核
- 增加 `top1_quality` / `top2_quality` / `quality_margin` / `ambiguity_reason`

**Top-K 策略：** Selector 支持 `strategy ∈ {Top1, Top3, Top5}` 配置，用于三组对比实验。

### 2.5 VerificationService 统一编排

**新增唯一 canonical 入口：**

```python
def verify_evidence_set(claim, evidence_candidates, routing_result,
                        verification_context) -> VerificationResult:
    gate_results = evidence_gate.evaluate_all(evidence_candidates, routing_result,
                                              verification_context.gate_config)
    selected, selection_meta = evidence_selector.select(gate_results, routing_result,
                                                       verification_context.selector_config)
    final = core_verify(claim, selected, trace=verification_context.trace)
    verification_context.trace.attach(routing_result, gate_results, selection_meta)
    return final
```

**三模式入口（全部调用 `verify_evidence_set`）：**

```python
def verify_core_oracle(claim, gold_evidence_block, routing, ctx) -> VerificationResult:
    # Evidence 来源 = Gold Evidence Block
    return verify_evidence_set(claim, [gold_evidence_block], routing, ctx)

def verify_noisy_oracle(claim, gold_plus_negatives, routing, ctx) -> VerificationResult:
    # Evidence 来源 = Gold + Hard Negatives
    return verify_evidence_set(claim, gold_plus_negatives, routing, ctx)

def verify_real_e2e(claim, routing, ctx) -> VerificationResult:
    # Evidence 来源 = Claim Router → Structured/Narrative Retrieval
    candidates = retrieve_via_channels(claim, routing, ctx)
    return verify_evidence_set(claim, candidates, routing, ctx)
```

**旧 `verify_claim` 改造为薄适配器：**

```python
def verify_claim(session, claim, top_k=8) -> VerificationResult:
    # 薄适配器：构造默认 verification_context，调用 verify_evidence_set
    routing = route_claim(claim)
    candidates = retrieve_for_claim(session, claim, top_k=top_k)
    ctx = VerificationContext(...)
    return verify_evidence_set(claim, candidates, routing, ctx)
```

旧 `verify_claim` 不保留任何独立 Verdict 判断、不绕开 Gate/Selector、不维护第二套 Verification Engine。旧 API 调用方迁移完成后标记 deprecated。

**Production 主链（API/Demo/E2E 统一）：**

```python
def verify_claim_production(claim, ...) -> VerificationResult:
    routing = route_claim(claim)
    candidates = retrieve_via_channels(claim, routing, ...)
    ctx = VerificationContext(...)
    return verify_evidence_set(claim, candidates, routing, ctx)
```

真实 API、Demo、Real E2E 全部调用 `verify_claim_production`。Demo 和评测脚本使用同一 Production 入口。

## 3. 双检索通道

### 3.1 Channel A — Structured Fact Retrieval

用于：STRUCTURED_NUMERIC / TABLE_METRIC / PERIOD_COMPARISON / SCOPE_VALIDATION

候选匹配顺序：
1. company（hard filter）
2. metric_canonical（match）
3. period + period_type（match）
4. scope（match）
5. unit（match or convertible）
6. normalized_value（proximity）
7. table context（neighboring_rows/columns）

数据源：`FinancialFact` 表。

### 3.2 Channel B — Narrative Evidence Retrieval

用于：NARRATIVE_FACT / CAUSALITY / FORECAST

使用：
- BM25（复用现有 `retrieve_for_claim` engine）
- semantic search（text similarity）
- section metadata
- entity filter
- document type
- narrative reranker（复用 Stage B 但仅叙述特征）

**禁止：** 将所有 Claim 都交给同一套 Table-aware Reranker。

**Channel 分发逻辑（在 `retrieve_via_channels` 内）：**

```python
def retrieve_via_channels(claim, routing, ctx) -> list[dict]:
    structured_routes = {"STRUCTURED_NUMERIC", "TABLE_METRIC", "PERIOD_COMPARISON", "SCOPE_VALIDATION"}
    narrative_routes = {"NARRATIVE_FACT", "CAUSALITY", "FORECAST"}
    candidates = []
    if routing.route in structured_routes:
        candidates += fact_index_retrieval(claim, routing, ctx)
        candidates += narrative_retrieval(claim, ctx)  # 补充叙述
    elif routing.route in narrative_routes:
        candidates += narrative_retrieval(claim, ctx)
        candidates += fact_index_retrieval(claim, routing, ctx)  # 补充结构化
    else:  # INSUFFICIENTLY_PARSED
        candidates += narrative_retrieval(claim, ctx)
    return dedup(candidates)
```

## 4. Evidence Precision Gate

见 §2.3。补充 Gate 配置：

```python
@dataclass
class GateConfig:
    # 数值类
    metric_match_threshold: float = 0.6
    period_conflict_strict: bool = True
    scope_conflict_strict: bool = True
    unit_convertible: bool = True
    # 因果类
    causal_language_required: bool = True
    causal_markers: list[str] = field(default_factory=lambda: [
        "导致", "推动", "主要由于", "attributable to", "driven by", "resulted from"
    ])
    # 预测类
    forecast_markers: list[str] = field(default_factory=lambda: [
        "预计", "指引", "目标", "管理层判断", "forecast", "guidance"
    ])
    # 质量阈值
    high_quality_threshold: float = 0.7
    medium_quality_threshold: float = 0.4
    # 路由匹配
    route_match_weight: float = 0.2
```

## 5. Evidence Margin 与弃权

见 §2.4。补充：

**建议阈值通过 Development 公司留一法确定，不能按 claim 单独调整。**

同时报告：
- coverage
- selective_accuracy
- abstention accuracy

**不得通过全部弃权虚假提升准确率。**

最低覆盖率：`coverage ≥ 0.65`

目标：
- `selective_accuracy ≥ 0.80`
- `abstention accuracy ≥ 0.75`

## 6. 重新分析 Phase 23.10 退化

**产物：** `backend/artifacts/e2e/phase23_11_regression_diff.json`

**脚本：** `backend/scripts/phase23_11_regression_diff.py`

对 Phase 23.9 与 Phase 23.10 结果做逐 Claim diff。每条包含：

```json
{
  "claim_id": "CLM-001",
  "phase23_9_verdict": "SUPPORTED",
  "phase23_10_verdict": "INSUFFICIENT_EVIDENCE",
  "gold_verdict": "SUPPORTED",
  "phase23_9_evidence": [...],
  "phase23_10_evidence": [...],
  "ranking_change": "gold rank 1 → rank 7",
  "evidence_noise_added": ["noise_block_A", "noise_block_B"],
  "failure_reason": "Top5 引入错误期间噪声，Verification 选择噪声证据",
  "phase23_11_expected_fix": "PERIOD_COMPARISON 路由 + Gate 拒绝错误期间"
}
```

必须明确：
- 哪些 Claim 从正确变错误
- 哪些噪声 Evidence 导致错误
- 哪些 Top5 候选不应进入 Verification
- 多 Evidence 聚合在哪一步失败

优先恢复所有 Phase 23.9 正确、Phase 23.10 错误的案例。

## 7. 真实 E2E 错误分解

重新定义并互斥分类（每条错误只能有一个 `primary_root_cause`，可记录 `secondary_causes`）：

- `RETRIEVAL_NO_CANDIDATE`
- `RETRIEVAL_GOLD_NOT_TOPK`
- `EVIDENCE_GATE_REJECTED_GOLD`
- `EVIDENCE_GATE_ACCEPTED_NOISE`
- `VERIFICATION_WRONG_WITH_CORRECT_EVIDENCE`
- `AGGREGATION_ERROR`
- `AMBIGUOUS_CORRECT_ABSTENTION`
- `BOTH_RETRIEVAL_AND_VERIFICATION`

**禁止：** 将所有错误简单归为 `retrieval_failure`。

## 8. 公司留一调参

只使用两折 Development Cross-validation：

| Fold | 调参公司 | 验证公司 |
|---|---|---|
| A | 五粮液 | 美的集团 |
| B | 美的集团 | 五粮液 |

可调参数仅包括：
- Evidence Gate 阈值（`metric_match_threshold` / `high_quality_threshold` / `medium_quality_threshold`）
- quality margin（`quality_margin` threshold）
- Structured/Narrative 通道权重
- Top1/Top3 选择
- ambiguity 阈值

**禁止：**
- claim-specific 参数
- company-specific 参数
- Gold Page 特征
- block_id 特征
- 验证集反复调参

每折必须保存冻结参数和首次验证结果。

## 9. 评测指标

### 9.1 Structured Retrieval（Channel A）

输出：
- Fact Hit@1
- Fact Hit@3
- Page Hit@1/3
- Correct Metric Rate
- Correct Period Rate
- Correct Scope Rate

**产物：** `backend/artifacts/retrieval/phase23_11_structured_metrics.json`

### 9.2 Narrative Retrieval（Channel B）

输出：
- Page Hit@1/3/5
- Block Hit@1/3/5
- Recall@5
- MRR

**产物：** `backend/artifacts/retrieval/phase23_11_narrative_metrics.json`

### 9.3 Evidence Gate

输出：
- precision
- recall
- accepted_noise_rate
- rejected_gold_rate
- average_selected_evidence_count
- ambiguity_rate

**产物：** `backend/artifacts/evidence_gate/phase23_11_gate_metrics.json`

### 9.4 CORE_ORACLE

输出：
- Accuracy
- Macro-F1
- Gold Gate Acceptance Rate
- Gold Selection Rate

### 9.5 NOISY_ORACLE

输出：
- Accuracy
- Macro-F1
- Gate Precision
- Gate Recall
- Accepted Noise Rate
- Gold Top1/Top3 Rate

### 9.6 REAL_E2E

输出：
- Accuracy
- Macro-F1
- per-class F1
- coverage
- selective_accuracy
- abstention accuracy
- FPR
- FNR
- primary failure distribution
- Retrieval Failure
- Gate Failure
- Verification Failure
- Aggregation Failure

**产物：** `backend/artifacts/e2e/phase23_11_development_e2e.json`

### 9.7 目标

| 指标 | 目标 | 理想 |
|---|---|---|
| Page Hit@5 | ≥ 0.75 | ≥ 0.80 |
| Block Hit@5 | ≥ 0.65 | — |
| Evidence Gate precision | ≥ 0.80 | — |
| accepted_noise_rate | ≤ 0.15 | — |
| rejected_gold_rate | ≤ 0.15 | — |
| Real E2E Accuracy | ≥ 0.70 | — |
| Real E2E Macro-F1 | ≥ 0.60 | ≥ 0.65 |
| selective_accuracy | ≥ 0.80 | — |
| coverage | ≥ 0.65 | — |
| verification 错误 | ≤ 3 | — |

未达到理想目标时不得声称完全 READY。

## 10. 评测完整性

所有组必须使用相同 43 条 Development Claims。

比较：
1. Phase 23.9 原始结果
2. Phase 23.10 原始结果
3. Phase 23.11 Top1 策略
4. Phase 23.11 Top3 策略
5. Phase 23.11 Gate 策略

**不得缩小样本。**

每组必须输出相同：
- Accuracy
- Macro-F1
- coverage
- abstention
- retrieval failures
- verification failures

## 11. 测试要求

新增测试（`backend/tests/test_phase23_11_*.py`）：
- claim router 测试
- structured fact index 测试
- narrative route 测试
- evidence gate 测试
- wrong-period rejection 测试
- wrong-scope rejection 测试
- causal evidence gate 测试
- ambiguity margin 测试
- top1/top3 对比测试
- noise evidence rejection 测试
- phase23.10 regression recovery 测试
- real API → router → retrieval → gate → verification 集成测试

**必须新增的集成测试（用户明确要求）：**
1. CORE_ORACLE 与 REAL_E2E 最终都调用同一 `verify_evidence_set`
2. CORE_ORACLE 不能绕过 Evidence Gate
3. Gold Evidence 被 Gate 错误拒绝时 Oracle 必须失败
4. NOISY_ORACLE 中错误期间 Evidence 必须被拒绝
5. NOISY_ORACLE 中正确 Gold Evidence 必须被选择
6. Real API 调用 Claim Router
7. Real API 调用 Evidence Gate
8. Real API 调用 Evidence Selector
9. Real API 最终调用 core_verify
10. 旧 `verify_claim` 不得包含独立 Verdict 逻辑
11. Demo 和评测脚本使用同一 Production 入口
12. Trace 能够显示每一步的输入输出和最终决策来源

完成后执行：
- pytest 全量连续 5 次
- frontend build 连续 3 次
- Development E2E 连续 2 次一致
- Oracle 连续 2 次保持一致
- Metamorphic 测试重新执行

## 12. 产物

### 创建

- `docs/phase23_11_evidence_routing_and_gate.md`
- `backend/scripts/phase23_11_acceptance.py`
- `backend/scripts/phase23_11_regression_diff.py`
- `backend/scripts/phase23_11_evidence_gate_eval.py`
- `backend/artifacts/phase23_11_acceptance.json`
- `backend/artifacts/e2e/phase23_11_regression_diff.json`
- `backend/artifacts/e2e/phase23_11_development_e2e.json`
- `backend/artifacts/retrieval/phase23_11_structured_metrics.json`
- `backend/artifacts/retrieval/phase23_11_narrative_metrics.json`
- `backend/artifacts/evidence_gate/phase23_11_gate_metrics.json`
- `backend/artifacts/cross_validation/phase23_11_leave_one_company_out.json`

### 新增代码

- `backend/app/services/claim_router.py`
- `backend/app/services/financial_fact_index.py`
- `backend/app/services/evidence_gate.py`
- `backend/app/services/evidence_selector.py`
- `backend/app/models/financial_fact.py`

### 更新

- `backend/app/services/verification/verification_service.py`（新增 `verify_evidence_set` + 三模式入口 + Production 入口；旧 `verify_claim` 改为薄适配器）
- `backend/app/services/evidence_retrieval/service.py`（Channel 分发钩子）
- `docs/phase23_10_table_aware_retrieval.md`（标注 Phase 23.11 修复的退化）
- `docs/finproof_progress.md`
- `README`

## 13. 完成标准

只有满足以下条件才能标记 `Development Engine Competition-Usable`：

1. Claim Router 进入真实主链
2. Structured 与 Narrative Retrieval 真实分流
3. Evidence Gate 进入 Verification 之前
4. 不再把全部 Top5 直接交给 Verification
5. Phase 23.10 退化案例完成逐 Claim 解释
6. Phase 23.9 正确但 Phase 23.10 错误的案例至少恢复 80%
7. Evidence Gate precision ≥ 0.80
8. accepted_noise_rate ≤ 0.15
9. Real E2E Accuracy ≥ 0.70
10. Real E2E Macro-F1 ≥ 0.60
11. selective_accuracy ≥ 0.80
12. coverage ≥ 0.65
13. verification 错误 ≤ 3
14. Oracle Accuracy 保持 ≥ 0.90
15. Oracle Macro-F1 保持 ≥ 0.85
16. Metamorphic 测试继续达标
17. pytest 连续 5 次通过
18. frontend build 连续 3 次成功
19. E2E 连续 2 次一致
20. 创建新 Git commit

若真实 E2E 仍低于 0.60：
- 不得继续新增检索特征
- 不得标记 Competition-Usable
- 必须选择一个更窄的比赛演示范围
- 只展示系统真正稳定支持的 Claim 类型
- 明确标注不支持的 Claim 类型

Blind Holdout 在补充两家全新公司 PDF 和待审计报告前继续标记 BLOCKED。

## 14. 最终汇报必须明确回答

1. Oracle 和 Real E2E 是否调用同一 `verify_evidence_set` — **是**
2. Gold Evidence 是否经过 Gate 和 Selector — **是，Gold 直入 core_verify 被禁止**
3. 旧 `verify_claim` 还剩哪些逻辑 — **只剩薄适配器：构造默认 context → 调用 `verify_evidence_set`，无独立 Verdict 判断**
4. Demo、API 和评测脚本是否使用同一 Production 入口 — **是，全部调用 `verify_claim_production`**
5. CORE_ORACLE、NOISY_ORACLE、REAL_E2E 三组指标 — **见 §9.4/9.5/9.6，实施后在 acceptance.json 输出**
6. 是否出现 Oracle 下降但生产路径更真实的情况 — **如实记录；若 Gold 被 Gate 拒绝则 Oracle 必须失败（`GATE_REJECTED_GOLD`），不绕过**
7. 新 commit — **实施完成后创建**

完成后停止，不开发 Phase 24。

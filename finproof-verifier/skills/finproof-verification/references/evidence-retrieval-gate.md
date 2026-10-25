# 证据检索与证据门（evidence retrieval & gate）

> 来源：`backend/app/services/evidence_retrieval/`（engine / hybrid_retrieval / reranker / evidence_gate 相关：evidence_selector / evidence_gate / evidence_aggregation / canonical_evidence / financial_fact_index / financial_summary_evidence）。

## 一、混合检索（Hybrid Retrieval）

证据检索层融合多路召回，再统一重排：

- **BM25**（关键词，指标词 + 数值）→ 精确命中财报原文块。
- **向量检索（Embedding）** → 语义近邻（无 Embedding 服务时降级为关键词+指标精确匹配，如实说明）。
- **规则召回** → 公司 + metric_code + period 联合检索，指标词典精确匹配。
- **财务指标索引（financial_fact_index）** → 从披露中重建结构化财务事实，供数值类主张直接比对。

检索入口 `retrieve_for_claim`：输入结构化主张，输出带页码的证据候选块（top-N，提交版默认 Top3 / Gate）。

## 二、证据门（Evidence Gate）与严格口径归因

- **strict scope 归因**（`evidence_gate._effective_scope`）：从 `metric_code` 推断 intrinsic scope（归母/扣非），Gate 与核心校验器使用同一 scope 语义，避免在验证前误拒正确证据。
- **主表利润证据严格恢复**（`financial_summary_evidence.py`）：对 `net_profit_attributable` / `deducted_net_profit` 两类 metric，按 company+period+metric+value+单位换算+披露舍入严格重建汇总表验证窗口，排除扣非混淆、要求当前值匹配；仅在 `metric_code` 命中时启用，非通用权重重排。
- **rerank 后处理**：对上述两类严格匹配的汇总行置于候选头部，不污染无关 metric。

## 三、证据选择 / 聚合（selector / aggregation）

- `evidence_selector`：从候选块中挑选最相关证据，记录来源文件与页码。
- `evidence_aggregation` + `canonical_evidence`：多证据归一、冲突标记（跨文件矛盾检测）。
- `evidence_window_reconstruction` / `table_context`：还原表格上下文，处理单元格拆分导致的整词不连续（如宁德一季报净利润关键词提取瑕疵）。

## 四、核心经验：检索召回是绝对瓶颈

- Phase 23.37 错误归因：**Retrieval failure 占 81%**（17/21）；Verification failure 仅 14%（3 条）；Gold mismatch 5%（1 条）。
- 16/21 错误 case 既无 gold block 也无正确 fact 进入 top10 —— **正确证据未进候选池是主导失败原因**。
- 提交版（Phase 23.11 Gate）剩余 11 个失败 case 中，绝大多数也是 →`INSUFFICIENT_EVIDENCE`（检索缺口），少数 False SUPPORTED / gold 边界。
- **改进纪律（禁止项）**：不得修改 gold、不得硬编码 case、不得绕过 Gate、不得调整 reranker weight（均已验证无效）。正确方向是 Retrieval Expansion：扩展 fact 覆盖、公司+metric+period 联合检索、query decomposition。

## 给专家的提示

- 当某主张被判"证据不足"时，先怀疑**检索召回**而非主张本身错；建议用户补充更相关的原始披露文件或检查指标/期间口径是否写清。
- 归母/扣非净利润类主张须显式区分 scope，否则易误拒正确证据。

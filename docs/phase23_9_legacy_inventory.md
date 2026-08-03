# Phase 23.9 重复实现分类清单（Legacy Inventory）

## 主链切换事实

Phase 23.9 起真实 Verification 主链唯一 PRIMARY 路径：

```
verify_claim → _select_verifier → core_pipeline.core_verify → VerificationResult
```

`verification_service._select_verifier` 已不再路由到旧验证器（numeric/period/growth/semantic/evidence_checker），
而是统一调用 `core_pipeline.core_verify`，后者整合四个 Phase 23.8 新模块：
`FinancialValue` / `PeriodContext` / `metric_scope` / `verdict_decision`，并内嵌 Integration Trace。

## 分类清单

### PRIMARY（生产主链唯一允许路径）

| 模块 | 文件 | 用途 |
| --- | --- | --- |
| core_pipeline | app/services/verification/core_pipeline.py | 主链入口，整合所有新模块 |
| FinancialValue | app/services/verification/financial_value.py | 数值抽取/换算/匹配（Financial Value） |
| PeriodContext | app/services/verification/period_context.py | 期间解析/兼容/单季推导 |
| metric_scope | app/services/verification/metric_scope.py | 指标归一化/口径解析/查询扩展 |
| verdict_decision | app/services/verification/verdict_decision.py | 8 步 Verdict 决策 + Semantic 守卫 |
| verification_service | app/services/verification/verification_service.py | verify_claim / fetch_evidence / _select_verifier（薄壳层，调用 core_pipeline） |

### LEGACY_USED（保留但仅供检索/诊断脚本使用，禁止生产核验入口调用）

| 模块 | 文件 | 仍被调用的合法范围 |
| --- | --- | --- |
| evidence_retrieval.engine | app/services/evidence_retrieval/engine.py | 检索评分（iter_numbers/values_compatible/_block_value_hits/score_block）—— 检索阶段仍服务，与核验是两个阶段 |
| numeric_verifier | app/services/verification/numeric_verifier.py | 仅 scripts/phase23_5/6/7/8 历史诊断脚本 + tests/test_verification.py |
| period_verifier | app/services/verification/period_verifier.py | 同上 |
| growth_verifier | app/services/verification/growth_verifier.py | 同上 |
| semantic_verifier | app/services/verification/semantic_verifier.py | 同上 |
| evidence_checker | app/services/verification/evidence_checker.py | 同上 |

### LEGACY_UNUSED

无。所有旧验证器仍被历史诊断脚本或单元测试调用，已统一标记 `[DEPRECATED]`，未在生产核验入口（copilot/agent/demo/risk）残留调用。

### TEST_ONLY

| 模块 | 测试文件 |
| --- | --- |
| financial_value | tests/test_financial_value.py |
| period_context | tests/test_period_context.py |
| metric_scope | tests/test_metric_scope.py |
| verdict_decision | tests/test_verdict_decision.py |
| 旧验证器集合 | tests/test_verification.py |

> 注：四个新模块虽在 TEST_ONLY 列内被单元测试调用，但它们同时通过 `core_pipeline.core_verify` 被 PRIMARY 主链调用——
> 已由 `backend/artifacts/integration/phase23_9_verification_call_graph.json` 与 `phase23_9_43claim_trace.json` 证明
> （trace 中 `financial_value_called / period_context_called / metric_scope_called / verdict_decision_called` 全 true）。

## 禁止规则

1. 禁止保留两个冲突的 verifier 并依赖调用顺序碰运气——主链仅 core_pipeline 一条路径。
2. 旧验证器（numeric/period/growth/semantic/evidence_checker）已在模块 docstring 加 `[DEPRECATED]` 标记，
   禁止生产入口（copilot / agent / demo_mode / risk / autonomous_agent）直接 import。
3. `evidence_retrieval.engine` 的数字正则（iter_numbers 等）服务检索评分，**不是核验路径**——
   核验阶段数值抽取必须使用 `FinancialValue.extract_financial_values`，由 core_pipeline 调用。
4. 历史诊断脚本（phase23_5/6/7/8）保留对 `verify_exact_value` 的调用以复现历史基线，
   新脚本（phase23_9_*）必须走 `core_verify` / `verify_claim`。

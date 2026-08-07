# Phase 23.37 Case Trace Report（Evidence Path Attribution）

> 生成时间：2026-08-07 UTC
> Trace：Retriever(Top50) → Top10 → Top5 → Gate → Selector → financial_fact → Decision → Final Verdict
> 基于：case_trace_data.json（43 claims，verify_claim_production top_k=5 路径）

---

## 1. 总览

| 指标 | 数值 |
|---|---|
| Total claims | 43 |
| Correct | 19（44.2%） |
| Wrong | 24（55.8%） |

> 注：本 trace 用 verify_claim_production(top_k=5)，acc=0.4419 与 E2E 官方指标（development_e2e top_k=10, acc=0.5116）不同——**评估路径差异本身是发现之一**（下文 Task 4 讨论）。

## 2. 24 个错误 case 完整 trace

图例：g[f] = gold_block[进Top50/进Top10/进Top5]；f[f] = 正确 financial_fact[进Top50/进Top10/进Top5]；dec = 最终 decision 来源

| claim | gold | pred | gold_block[50/10/5] | fact[50/10/5] | dec | 关键 trace |
|---|---|---|---|---|---|---|
| CLM-002 | REFUTED | SUPPORTED | Y/Y/Y | Y/Y/Y | FACT | 正确 fact 进 top5，fact decision 判 SUPPORTED 错（复合 claim） |
| CLM-005 | SUPPORTED | REFUTED | n/n/n | Y/n/n | BLOCK | fact 仅进 top50 未进 top10，block 判错 |
| CLM-006 | REFUTED | INSUFFICIENT | n/n/n | Y/Y/Y | BLOCK | fact 进 top5 但 block 路径未消费，INSUFFICIENT |
| CLM-007 | SUPPORTED | REFUTED | n/n/n | Y/Y/Y | BLOCK | fact 进 top5 但 block 误判 REFUTED（Q1 period） |
| CLM-009 | REFUTED | INSUFFICIENT | n/n/n | Y/Y/n | NO_EVIDENCE | fact 进 top10 未进 top5，无证据 |
| CLM-010 | REFUTED | INSUFFICIENT | n/n/n | n/n/n | NO_EVIDENCE | 正确 fact 不在候选（季度类 index 未覆盖） |
| CLM-011 | SUPPORTED | INSUFFICIENT | n/n/n | n/n/n | BLOCK | 正确 fact 不在候选（Q1 数据） |
| CLM-012 | SUPPORTED | REFUTED | Y/Y/n | n/n/n | FACT | gold block 进 top10，fact 无，fact decision 误 REFUTED |
| CLM-013 | SUPPORTED | REFUTED | n/n/n | n/n/n | BLOCK | 正确证据不在候选，block 误判 |
| CLM-014 | SUPPORTED | REFUTED | Y/n/n | n/n/n | FACT | gold 仅进 top50，fact 无，fact decision 误 REFUTED |
| CLM-015 | REFUTED | INSUFFICIENT | n/n/n | Y/Y/Y | BLOCK | fact 进 top5 但 block 未消费 |
| CLM-019 | SUPPORTED | INSUFFICIENT | n/n/n | n/n/n | SEMANTIC | 正确证据不在候选（business_fact） |
| CLM-022 | INSUFFICIENT | SUPPORTED | n/n/n | n/n/n | BLOCK | 无正确证据，block 误判 SUPPORTED |
| CLM-024 | PARTIAL | REFUTED | n/n/n | Y/Y/Y | FACT | fact 进 top5，fact decision 误 REFUTED |
| CLM-025 | UNABLE | REFUTED | n/n/n | n/n/n | BLOCK | 无正确证据，block 误判 |
| CLM-026 | SUPPORTED | INSUFFICIENT | n/n/n | n/n/n | BLOCK | 正确证据不在候选（H1 扣非） |
| CLM-H02 | SUPPORTED | REFUTED | n/n/n | n/n/n | FACT | 无正确 fact，fact decision 误 REFUTED |
| CLM-H04 | SUPPORTED | REFUTED | n/n/n | n/n/n | FACT | 同上 |
| CLM-H05 | REFUTED | INSUFFICIENT | n/n/n | n/n/n | BLOCK | 正确 fact 不在候选（yoy_ocf） |
| CLM-H08 | SUPPORTED | REFUTED | n/n/n | n/n/n | FACT | 无正确 fact，fact decision 误 REFUTED |
| CLM-H10 | REFUTED | INSUFFICIENT | n/n/n | n/n/n | SEMANTIC | 正确证据不在候选（publication_date） |
| CLM-H11 | SUPPORTED | INSUFFICIENT | n/n/n | n/n/n | BLOCK | 正确证据不在候选（扣非） |
| CLM-H12 | SUPPORTED | PARTIAL | n/n/n | n/n/n | SEMANTIC | 正确证据不在候选（listing_info） |
| CLM-H17 | INSUFFICIENT | SUPPORTED | n/n/n | n/n/n | BLOCK | 无正确证据，block 误判 SUPPORTED |

## 3. Decision 来源分布（24 错误）

| decision 来源 | 数量 |
|---|---|
| FACT | 8（CLM-002/012/014/024/H02/H04/H08 + H08） |
| BLOCK | 12 |
| NO_EVIDENCE | 2 |
| SEMANTIC | 2 |

## 4. 数据

`data/gold_review/phase23_11_6_2/case_trace_data.json`

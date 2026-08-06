# Phase 23.11.8-B Gold Import 报告

> 生成时间：2026-08-06T04:07:10.455466+00:00

## Imported

| Evidence ID | claim_id | decision | selected_block_ids | gold_confirm_status |
| --- | --- | --- | --- | --- |
| EVD-001 | CLM-001 | MATCH_SINGLE_BLOCK | [189] | CONFIRMED |
| EVD-003 | CLM-003 | MATCH_SINGLE_BLOCK | [190] | CONFIRMED |

## Hash

| 文件 | before | after |
| --- | --- | --- |
| data/demo/annotations/gold_evidence.json | 8982c202f1d243ee... | 未修改（保留旧版） |
| data/holdout/annotations/gold_evidence.json | 6ff154e7845350c6... | 未修改（保留旧版） |
| data/annotations/gold_evidence_v3.json | - | 97016dac8488d8492574245f670ac130c19d11fc12317db55b5da863f685f036 |

## Imported IDs

- ['EVD-001', 'EVD-003']

## 前置检查（全部通过）

- human_confirmed=true：EVD-001/EVD-003 ✅
- confirmed_by 存在（user）✅
- decision 合法（MATCH_SINGLE_BLOCK）✅
- block 存在（189/190 在 document_blocks）✅
- block 属于 candidate group（189∈EVD-001-g1, 190∈EVD-003-g1）✅
- 无 pending conflict（EVD-001/EVD-003 不在 claim_gold_conflicts）✅

## 说明

- 新版本写入 `data/annotations/gold_evidence_v3.json`（23.11.8-B-v3），**不覆盖**旧版 demo/holdout gold。
- 仅追加 `confirmed_block_ids` / `gold_confirm_status` / `confirmed_at` 元数据，未改动 evidence_text / verdict。
- EVD-002/EVD-004/EVD-H04 BLOCKED，EVD-010 REJECTED，未导入。

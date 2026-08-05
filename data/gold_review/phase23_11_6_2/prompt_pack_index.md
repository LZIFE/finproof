# Phase 23.11.6.2 Prompt Pack 浏览索引

> 生成时间：2026-08-05T09:08:19.971719+00:00
> 总条数：32

## 浏览顺序

| 序号 | Evidence ID | Claim ID | Prompt 文件 | Candidate Bundle 数量 | 人工确认状态 |
| --- | --- | --- | --- | --- | --- |
| 001 | EVD-001 | CLM-001 | `prompt_pack/001_EVD-001.md` | 5 | 未审核 |
| 002 | EVD-002 | CLM-002 | `prompt_pack/002_EVD-002.md` | 5 | 未审核 |
| 003 | EVD-003 | CLM-003 | `prompt_pack/003_EVD-003.md` | 5 | 未审核 |
| 004 | EVD-004 | CLM-004 | `prompt_pack/004_EVD-004.md` | 5 | 未审核 |
| 005 | EVD-005 | CLM-005 | `prompt_pack/005_EVD-005.md` | 5 | 未审核 |
| 006 | EVD-006 | CLM-005 | `prompt_pack/006_EVD-006.md` | 5 | 未审核 |
| 007 | EVD-007 | CLM-006 | `prompt_pack/007_EVD-007.md` | 5 | 未审核 |
| 008 | EVD-008 | CLM-006 | `prompt_pack/008_EVD-008.md` | 5 | 未审核 |
| 009 | EVD-009 | CLM-007 | `prompt_pack/009_EVD-009.md` | 5 | 未审核 |
| 010 | EVD-013 | CLM-009 | `prompt_pack/010_EVD-013.md` | 5 | 未审核 |
| 011 | EVD-015 | CLM-010 | `prompt_pack/011_EVD-015.md` | 5 | 未审核 |
| 012 | EVD-016 | CLM-011 | `prompt_pack/012_EVD-016.md` | 5 | 未审核 |
| 013 | EVD-017 | CLM-012 | `prompt_pack/013_EVD-017.md` | 5 | 未审核 |
| 014 | EVD-019 | CLM-014 | `prompt_pack/014_EVD-019.md` | 5 | 未审核 |
| 015 | EVD-021 | CLM-015 | `prompt_pack/015_EVD-021.md` | 5 | 未审核 |
| 016 | EVD-022 | CLM-016 | `prompt_pack/016_EVD-022.md` | 5 | 未审核 |
| 017 | EVD-023 | CLM-017 | `prompt_pack/017_EVD-023.md` | 5 | 未审核 |
| 018 | EVD-024 | CLM-018 | `prompt_pack/018_EVD-024.md` | 5 | 未审核 |
| 019 | EVD-027 | CLM-024 | `prompt_pack/019_EVD-027.md` | 5 | 未审核 |
| 020 | EVD-H01 | CLM-H01 | `prompt_pack/020_EVD-H01.md` | 5 | 未审核 |
| 021 | EVD-H02 | CLM-H02 | `prompt_pack/021_EVD-H02.md` | 5 | 未审核 |
| 022 | EVD-H03 | CLM-H03 | `prompt_pack/022_EVD-H03.md` | 5 | 未审核 |
| 023 | EVD-H04 | CLM-H04 | `prompt_pack/023_EVD-H04.md` | 5 | 未审核 |
| 024 | EVD-H05 | CLM-H05 | `prompt_pack/024_EVD-H05.md` | 5 | 未审核 |
| 025 | EVD-H06 | CLM-H06 | `prompt_pack/025_EVD-H06.md` | 5 | 未审核 |
| 026 | EVD-H07 | CLM-H07 | `prompt_pack/026_EVD-H07.md` | 5 | 未审核 |
| 027 | EVD-H08 | CLM-H08 | `prompt_pack/027_EVD-H08.md` | 5 | 未审核 |
| 028 | EVD-H09 | CLM-H09 | `prompt_pack/028_EVD-H09.md` | 5 | 未审核 |
| 029 | EVD-H10 | CLM-H10 | `prompt_pack/029_EVD-H10.md` | 5 | 未审核 |
| 030 | EVD-H11 | CLM-H11 | `prompt_pack/030_EVD-H11.md` | 5 | 未审核 |
| 031 | EVD-H12 | CLM-H12 | `prompt_pack/031_EVD-H12.md` | 5 | 未审核 |
| 032 | EVD-H16 | CLM-H16 | `prompt_pack/032_EVD-H16.md` | 5 | 未审核 |

## 优先顺序说明

1. Priority Cohort（优先队列）—— 若存在标记，优先审核
2. 候选唯一且文本完整 —— 可快速判定 MATCH_SINGLE_BLOCK
3. 多 Block 候选 —— 需要 MATCH_MULTIPLE_BLOCKS 判定
4. NONE / UNSURE 高风险项 —— 需要重点复核
5. NOT_FOUND 恢复项 —— 单独审核

## 操作流程

1. 用任意 Markdown 阅读器打开下方对应 `.md` 文件
2. 复制整个文件内容粘贴给 ChatGPT
3. 把 ChatGPT 返回的 JSON 写入 `ai_review_results.jsonl`
4. 用 `backend/scripts/phase23_11_6_2_collect_ai_reviews.py` 校验并收集

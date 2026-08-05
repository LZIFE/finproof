# Phase 23.11.6.2.1 Prompt Pack 浏览索引

> 生成时间：2026-08-05T15:36:44.027692+00:00
> 总文件数：42（32 Evidence Alignment + 10 Source Recovery/Paraphrase）
> Bundle 去重后总数：159（原 160，移除 1 个 EVD-022 重复）

## 状态分类说明

| 状态 | 含义 |
| --- | --- |
| `READY_FOR_EVIDENCE_ALIGNMENT` | 候选正文齐全，可做 Evidence Alignment 盲审 |
| `READY_FOR_PARAPHRASE_REVIEW` | Gold 可能是改写/摘要，做改写审核，不得自动进 Gold |
| `SOURCE_RECOVERY_REQUIRED` | 主 PDF 未找到 Gold 关键数字，做来源恢复，不得强行选 Block |
| `PROMPT_INTEGRITY_FAILED` | Prompt 完整性校验失败，需修复 |

## 审核顺序

1. EVD-001 / EVD-002（首批导出，已复制到 export_for_user/）
2. Priority Cohort 其他项目
3. 普通 Evidence Alignment（READY_FOR_EVIDENCE_ALIGNMENT）
4. Paraphrase Review（READY_FOR_PARAPHRASE_REVIEW）
5. Source Recovery（SOURCE_RECOVERY_REQUIRED）

## 1. 首批导出（已复制到 export_for_user/）

| 序号 | Evidence ID | Prompt 文件 | export 路径 |
| --- | --- | --- | --- |
| 001 | EVD-001 | `prompt_pack/001_EVD-001.md` | `export_for_user/001_EVD-001.md` |
| 002 | EVD-002 | `prompt_pack/002_EVD-002.md` | `export_for_user/002_EVD-002.md` |

下一份建议审核文件：`prompt_pack/003_EVD-003.md`

## 2. READY_FOR_EVIDENCE_ALIGNMENT
### READY_FOR_EVIDENCE_ALIGNMENT（32 条）

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
| 016 | EVD-022 | CLM-016 | `prompt_pack/016_EVD-022.md` | 4 | 未审核 |
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

## 3. READY_FOR_PARAPHRASE_REVIEW
### READY_FOR_PARAPHRASE_REVIEW（6 条）

| 序号 | Evidence ID | Claim ID | Prompt 文件 | Candidate Bundle 数量 | 人工确认状态 |
| --- | --- | --- | --- | --- | --- |
| 034 | EVD-011 | CLM-008 | `prompt_pack/034_EVD-011.md` | 5 | 未审核 |
| 037 | EVD-018 | CLM-013 | `prompt_pack/037_EVD-018.md` | 0 | 未审核 |
| 038 | EVD-020 | CLM-015 | `prompt_pack/038_EVD-020.md` | 5 | 未审核 |
| 039 | EVD-025 | CLM-019 | `prompt_pack/039_EVD-025.md` | 0 | 未审核 |
| 040 | EVD-026 | CLM-020 | `prompt_pack/040_EVD-026.md` | 5 | 未审核 |
| 041 | EVD-028 | CLM-024 | `prompt_pack/041_EVD-028.md` | 5 | 未审核 |

## 4. SOURCE_RECOVERY_REQUIRED
### SOURCE_RECOVERY_REQUIRED（4 条）

| 序号 | Evidence ID | Claim ID | Prompt 文件 | Candidate Bundle 数量 | 人工确认状态 |
| --- | --- | --- | --- | --- | --- |
| 033 | EVD-010 | CLM-008 | `prompt_pack/033_EVD-010.md` | 0 | 未审核 |
| 035 | EVD-012 | CLM-009 | `prompt_pack/035_EVD-012.md` | 0 | 未审核 |
| 036 | EVD-014 | CLM-010 | `prompt_pack/036_EVD-014.md` | 0 | 未审核 |
| 042 | EVD-029 | CLM-026 | `prompt_pack/042_EVD-029.md` | 0 | 未审核 |

## 5. PROMPT_INTEGRITY_FAILED
### PROMPT_INTEGRITY_FAILED（无）

## 操作流程

1. 用任意 Markdown 阅读器打开对应 `.md` 文件
2. 复制整个文件内容粘贴给 ChatGPT
3. 把 ChatGPT 返回的 JSON 写入 `ai_review_results.jsonl`
4. 用 `backend/scripts/phase23_11_6_2_collect_ai_reviews.py` 校验并收集
5. AI 结果状态为 `AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION`，**不能直接导入 Gold**

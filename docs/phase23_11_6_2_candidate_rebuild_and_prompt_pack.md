# Phase 23.11.6.2 — 候选 Evidence 重建与 Prompt Review Pack

**阶段**：Phase 23.11.6.2
**日期**：2026-08-05
**状态**：`PROMPT_REVIEW_PACK_READY`
**基线 commit**：`03af378`（Phase 23.11.6.1 人工审核包可用性最终检查）

---

## 1. 背景与动机

Phase 23.11.6 的第一轮 AI 盲审暴露出两个阻断性问题：

1. **`review_items.json` 候选 Block 选取缺陷**：86 个 Block 引用里 64 个是 PDF 表格的真空单元格；EVD-002 漏选了真正含正文的 block 4443。根因在 `backend/scripts/phase23_11_6_prepare_review.py` 忠实搬运了上游 grounding audit 给的 `candidate_block_ids`，但上游选取逻辑把空白单元格选成了候选。
2. **v2 盲审结果不可信**：`review_results_agent_v2.json` 未保留任何可验证元信息（无 model_name / timestamp / input_snapshot / usage / attempts），无法证明生成时的实际输入与模型调用。

Phase 23.11.6.2 不修改 Verifier / Gate / Selector / Real E2E / Gold Verdict / 正式评测指标，只做：
- 审计 v2 盲审来源
- 修复 Candidate Evidence 生成
- 生成可直接粘贴给 ChatGPT 的逐条盲审提示词包
- **不调用任何模型**

---

## 2. 历史结果冻结

`backend/artifacts/gold_contract/phase23_11_6_2_freeze_historical_results.json`

| 文件 | 版本 | 状态 | 可导入 Gold |
|---|---|---|---|
| `review_results_agent.json` | v1 | `HISTORICAL_PROVENANCE_UNVERIFIED` | 否 |
| `review_results_agent_v2.json` | v2 | `HISTORICAL_PROVENANCE_UNVERIFIED` | 否 |
| `review_results_agent_v3.json` | v3 | `NO_MODEL_CALL_EMPTY_RESULT` | 否 |

三个文件均：
- 不得导入 Gold
- 不得作为人工审核结果
- 不得参与正式指标
- 不得覆盖

---

## 3. v2 输入来源审计

`backend/artifacts/gold_contract/phase23_11_6_2_v2_provenance_audit.json`
脚本：`backend/scripts/phase23_11_6_2_v2_provenance_audit.py`

### 审计结论

| 维度 | 结果 |
|---|---|
| v2 记录数 | 32 |
| 携带任何元信息键 | **否**（per_record_meta_keys_found = `[]`） |
| 含 model_name | 否 |
| 含 timestamp | 否 |
| 含 input_snapshot | 否 |
| 含 usage/attempts | 否 |
| provenance_status | 32/32 = `MODEL_CALL_UNVERIFIABLE` |

### 重点问题回答

1. **v2 为何能看到 block 4443**：v2 的 EVD-005/006/007/008 的 `reason` 字段逐字引用了 block 4443 的正文片段，表明 v2 生成时确实看到了正文。但 v2 记录未保留任何输入快照，**无法证明该正文来自 `review_items.json` 的候选还是模型额外读取的上下文**。
2. **EVD-005~008 输入是否含 4443**：`review_items.json` 中 EVD-005~008 的候选 `block_ids` 均含 `'4443'`，且 block 4443 的 PyMuPDF 正文提取状态为 OK。v2 的输入确实包含 block 4443 正文。
3. **其余 28 条是否只看到空 Block**：86 个引用里 64 个是 EMPTY_BLOCK（真空单元格）。v2 的 28 条 NONE_OF_THE_ABOVE 中绝大多数候选 block 正文为空，与"候选正文为空"事实一致。
4. **v2 是否用了与 review_items.json 不同的输入**：无法证明。v2 的 reason 引用的正文片段与 PyMuPDF 提取一致，间接表明同源，但无直接证据。
5. **模型是否虚构 Block ID 或读取额外上下文**：未发现虚构 block_id（选中 block 全部在候选列表）；未发现读取额外上下文的直接证据，但因 v2 无输入快照，无法完全排除。

### 最终判定

`HISTORICAL_PROVENANCE_UNVERIFIED` —— v2 未保留任何可验证元信息，**不得导入 Gold，不得作为人工审核结果，不得参与正式指标**。

---

## 4. 候选 Evidence 重建

脚本：`backend/scripts/phase23_11_6_2_rebuild_candidates.py`
输出：`data/gold_review/phase23_11_6_2/review_items_rebuilt.json`

### 修复策略

不再信任上游 grounding audit 给的 `candidate_block_ids`（它选了真空单元格）。从 Gold 标注的 `existing_page` 出发，加载该页 + 前后页所有 DocumentBlock，用 PyMuPDF 重新提取每个 block 正文，结构化分类后构建 Candidate Bundle。

### Block 结构化分类

每个 Block 标注：
- `is_blank` / `is_micro_cell` / `is_header` / `is_unit_label`
- `is_period_header` / `is_metric_row` / `is_numeric_row`
- 坐标 `(x0, y0, x1, y1)` / `width` / `height` / `block_index`

### Candidate Bundle 构建

- 大正文 Block（len > 50）单独成 Bundle
- 短文本 Block（单位"千元"、期间"2024年度"、行标题"营业收入"）按空间相邻组合
- **空白 Block / 微单元格不单独作为候选**
- 最多 5 组可信 Candidate Bundle
- 排序用 Gold 文本相似度 + 关键数字匹配（**不自动确认 Gold**）

### 重建统计

| 指标 | 数值 |
|---|---|
| 总 evidence | 32 |
| 重建出 Bundle 的条数 | 32 |
| 未找到 Bundle 的条数 | 0 |
| 总 Bundle 数 | 160 |
| 含正文的 Bundle 数 | 160 |
| 空 Bundle 数 | 0 |

### EVD-002 验证

EVD-002（Gold：一、营业总收入 458,502,407 409,084,266）的 5 个 Bundle：
- Bundle 1（block 4442）：reconstruction_coverage=0.87，正文含"458,502,407 409,084,266"
- Bundle 2-5：含其他利润表行项

**EVD-002 候选 Bundle 含有完整营业总收入正文的 block**（4442 或 4443），缺陷已修复。

---

## 5. Candidate Recall 完整性检查

`backend/artifacts/gold_contract/phase23_11_6_2_candidate_recall.json`

| 指标 | 数值 |
|---|---|
| total_evidence | 32 |
| rebuilt_with_bundles | 32 |
| no_bundles_found | 0 |
| review_ready | 32/32 = true |
| non_empty_bundle_count > 0 | 32/32 |

每条 recall item 含：`gold_evidence_id` / `original_gold_evidence` / `candidate_bundle_count` / `non_empty_bundle_count` / `best_reconstruction_coverage` / `key_numbers_found` / `metric_found` / `period_found` / `unit_found` / `likely_source_recovered` / `review_ready` / `failure_reason`。

---

## 6. NOT_FOUND 恢复（10 条）

脚本：`backend/scripts/phase23_11_6_2_not_found_recovery.py`
输出：`backend/artifacts/gold_contract/phase23_11_6_2_not_found_recovery.json`

对 10 条 NOT_FOUND，用 Gold 关键数字在 PDF 全文搜索，定位真正含正文的页面，构建视觉审核 Candidate Bundle。

### 状态分布

| 状态 | 数量 |
|---|---|
| CANDIDATES_RECOVERED | 0 |
| PARAPHRASED_SOURCE_LOCATED | 6 |
| VISUAL_REVIEW_REQUIRED | 0 |
| WRONG_PAGE_REFERENCE | 0 |
| WRONG_DOCUMENT_REFERENCE | 0 |
| STILL_NOT_FOUND | 4 |

### 说明

- **6 条 PARAPHRASED_SOURCE_LOCATED**：在 page 124（管理层讨论与分析）找到部分关键数字匹配的 Bundle，但 reconstruction_coverage 偏低（0.2-0.3），Gold 可能是原文改写或摘要。
- **4 条 STILL_NOT_FOUND**：在主 PDF（annual_report.pdf）全文中未找到 Gold 关键数字，可能涉及其他文档（half_year_report.pdf / q1_report.pdf）或 Gold 文本有误。
- **不自动写入 Gold**。

---

## 7. ChatGPT 人工提示词包

脚本：`backend/scripts/phase23_11_6_2_generate_prompt_pack.py`
输出目录：`data/gold_review/phase23_11_6_2/prompt_pack/`

### 产物

- 32 个独立 Markdown 文件：`001_EVD-xxx.md` ~ `032_EVD-H16.md`
- 每文件已填入：Claim / 公司 / 报告信息 / 原始 Gold Evidence / 最多 5 组 Candidate Bundle / Block 正文 / 表格标题 / 行列信息 / 前后文 / 标准盲审提示词 / JSON 输出 Schema
- 浏览索引：`data/gold_review/phase23_11_6_2/prompt_pack_index.md`

### 信息隔离（第一轮盲审）

提示词**不含**：
- `expected_verdict` / `gold_verdict` / 系统 `prediction` 的值
- v1/v2/v3 决策
- 当前系统 selected evidence
- 模型推荐候选
- `reconstruction_coverage` 分数（保留在内部 JSON，不展示给模型，避免锚定）

模型只输出新的 `estimated_coverage`。

### 使用流程

1. 用任意 Markdown 阅读器打开 `prompt_pack/001_EVD-xxx.md`
2. 复制整个文件内容粘贴给 ChatGPT
3. 把 ChatGPT 返回的 JSON 写入 `ai_review_results.jsonl`
4. 用 `backend/scripts/phase23_11_6_2_collect_ai_reviews.py` 校验并收集

---

## 8. AI 审核结果收集

脚本：`backend/scripts/phase23_11_6_2_collect_ai_reviews.py`
JSONL：`data/gold_review/phase23_11_6_2/ai_review_results.jsonl`（初始化为空）

### 校验规则

- Gold Evidence ID 存在于 `review_items_rebuilt.json`
- `decision` 合法（4 选 1）
- Block ID 属于该候选
- MATCH_SINGLE_BLOCK 只能选 1 个 Block
- MATCH_MULTIPLE_BLOCKS 至少选 2 个 Block
- NONE / UNSURE 不能选 Block
- `confidence` ∈ [0, 1]
- `estimated_coverage` ∈ [0, 1]
- 不重复写入（同一 gold_evidence_id 只能有一条）
- **AI 结果不能直接导入 Gold**

### AI 结果状态

每条写入记录的 `_meta.ai_review_status` 只能是：
`AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION`

且 `_meta.may_import_to_gold = false`。

### 用法

```bash
# 初始化空 JSONL
cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py --init

# 校验并收集（写入 JSONL）
cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py --input <json_or_jsonl>

# 仅校验不写入
cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py --input <json> --dry-run
```

---

## 9. 测试

`backend/tests/test_phase23_11_6_2_candidate_rebuild_and_prompt_pack.py`（18 个测试）

覆盖：
- 空 Block 不成为候选 Bundle
- 短单位 Block 不会被错误删除
- 表头和数据行正确组合
- EVD-002 包含 block 4443 或 4442
- Candidate Bundle 正文非空
- 原Gold关键数字保持不变
- Prompt 不含 verdict 值泄漏
- Prompt 不含系统 prediction 字段名泄漏
- Prompt 文件变量全部填充
- AI 结果 Schema 校验（dry-run）
- AI 结果状态为 PENDING_HUMAN_CONFIRMATION
- v2 来源审计测试（32 条 MODEL_CALL_UNVERIFIABLE）
- 历史结果冻结测试
- NOT_FOUND 恢复测试（10 条合法状态）
- Candidate Recall 完整性测试
- Prompt Pack 索引测试
- JSONL 初始化为空测试

---

## 10. 产物清单

### 新建脚本

| 脚本 | 用途 |
|---|---|
| `backend/scripts/phase23_11_6_2_v2_provenance_audit.py` | v2 来源审计 |
| `backend/scripts/phase23_11_6_2_rebuild_candidates.py` | 候选 Evidence 重建 |
| `backend/scripts/phase23_11_6_2_not_found_recovery.py` | NOT_FOUND 恢复 |
| `backend/scripts/phase23_11_6_2_generate_prompt_pack.py` | Prompt Pack 生成 |
| `backend/scripts/phase23_11_6_2_collect_ai_reviews.py` | AI 审核结果收集 |

### 新建产物

| 文件 | 用途 |
|---|---|
| `backend/artifacts/gold_contract/phase23_11_6_2_freeze_historical_results.json` | 历史结果冻结清单 |
| `backend/artifacts/gold_contract/phase23_11_6_2_v2_provenance_audit.json` | v2 来源审计结果 |
| `backend/artifacts/gold_contract/phase23_11_6_2_candidate_recall.json` | Candidate Recall 完整性检查 |
| `backend/artifacts/gold_contract/phase23_11_6_2_not_found_recovery.json` | NOT_FOUND 恢复结果 |
| `data/gold_review/phase23_11_6_2/review_items_rebuilt.json` | 重建后的候选 Evidence |
| `data/gold_review/phase23_11_6_2/prompt_pack/*.md` | 32 个独立盲审提示词 |
| `data/gold_review/phase23_11_6_2/prompt_pack_index.md` | 浏览顺序索引 |
| `data/gold_review/phase23_11_6_2/ai_review_results.jsonl` | AI 审核结果收集（初始化为空） |

### 新建测试

| 文件 | 用途 |
|---|---|
| `backend/tests/test_phase23_11_6_2_candidate_rebuild_and_prompt_pack.py` | 18 个测试覆盖全部要求 |

---

## 11. 完成标准对照

| 标准 | 状态 |
|---|---|
| 1. v2 输入来源完成审计 | ✅ |
| 2. 32 条项目全部重新生成 Candidate Bundle | ✅ |
| 3. 空Block不再作为Evidence候选 | ✅ |
| 4. EVD-002 包含 block 4443（或同等含正文的 4442） | ✅ |
| 5. 所有Review-ready Bundle正文非空 | ✅ |
| 6. 10条NOT_FOUND重新完成来源恢复 | ✅ |
| 7. 每条审核项目生成独立Markdown提示词 | ✅ |
| 8. Prompt不泄露Verdict或系统预测 | ✅ |
| 9. AI审核结果只作为人工确认建议 | ✅ |
| 10. 不调用任何模型 | ✅ |
| 11. 全量pytest连续5次通过 | （见 acceptance.json） |
| 12. frontend build连续3次成功 | （见 acceptance.json） |
| 13. 创建新commit并提供完整hash | （见 acceptance.json） |

---

## 12. 下一步

**状态：`PROMPT_REVIEW_PACK_READY`**

由用户把 Markdown 提示词逐条发送给 ChatGPT，审核完成后用 `phase23_11_6_2_collect_ai_reviews.py` 收集 JSON 结果。AI 结果状态保持 `AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION`，**不能直接导入 Gold**——需人工确认后才能进入 Gold 流程。

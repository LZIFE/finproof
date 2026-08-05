# 人工Gold审核快速上手（Phase 23.11.6）

> 目标：审核42条Gold Evidence并提交结果。预计耗时约2-4小时。

## 1. 打开盲审页面

用浏览器打开（双击即可，无需联网）：

```
data/gold_review/phase23_11_6/review.html
```

共 **32条** 待审核Evidence（每条一个卡片）。

## 2. 审核候选

每条卡片包含：
- Claim文本、公司、报告名
- 原Gold Evidence文本（黄色背景）
- 最多5组候选Block（绿色背景），每组含：页码、Block ID、候选原文、前后Block上下文

**操作**：对照"原Gold Evidence文本"，判断哪组候选Block真正对应它。

**四个选项**（在卡片底部手动记录）：
- `MATCH_SINGLE_BLOCK`：单个Block完全对应
- `MATCH_MULTIPLE_BLOCKS`：多个相邻Block共同对应
- `NONE_OF_THE_ABOVE`：候选都不对应
- `UNSURE`：无法确定

同时填写：
- `selected_block_ids`：你确认的Block ID列表（如 `1,2,3`）
- `evidence_complete`：`yes` 或 `no`
- `reviewer_note`：判断依据（一句话即可）

## 3. 保存审核结果

**推荐方式（使用交互式页面，无需手改JSON）：**

1. 在 review.html 中逐条审核，随时点「💾 保存进度」；
2. 全部完成后点「📤 导出JSON」，浏览器会下载 `review_results.json`；
3. **将下载的文件移动到**：
   ```
   data/gold_review/phase23_11_6/review_results.json
   ```
   （浏览器无法直接写回项目目录，必须手动移动）

**备选方式（手工编辑模板）：**

用文本编辑器打开模板：

```
data/gold_review/phase23_11_6/review_results.template.json
```

按模板结构，把每条的结果填入，另存为：

```
data/gold_review/phase23_11_6/review_results.json
```

**不要修改模板里非reviewer开头的字段。**

## 4. 审核NOT_FOUND页面

打开：

```
data/gold_review/phase23_11_6/not_found_review.html
```

共 **10条**。每条标注了原Gold文本和标注页码。请打开 `data/demo/source/` 或 `data/holdout/source/` 下对应PDF的该页核对。

**选项**：`FOUND_ON_PAGE` / `FOUND_ON_ADJACENT_PAGE` / `FOUND_IN_OTHER_DOCUMENT` / `GOLD_TEXT_IS_PARAPHRASED` / `GOLD_ANNOTATION_IS_WRONG` / `SOURCE_MISSING` / `UNSURE`

## 5. 审核Intentional Insufficient（3条）

**推荐方式（表单页面，无需手改JSON）：**

打开：

```
data/gold_review/phase23_11_6/insufficient_review.html
```

填写 `CLM-021`、`CLM-022`、`CLM-H17` 三条的：
- `reviewer_confirmed_insufficient`：`yes` 或 `no`
- `reviewer_rationale`：依据
- `reviewer_name` / `reviewed_at`

点「导出JSON」下载 `insufficient_results.json` 并移动到 `data/gold_review/phase23_11_6/`。

**备选方式（编辑JSON）：**

打开 `insufficient_review.json`，每条**只修改** `reviewer_` 开头的字段（其余字段不得修改）。

## 6. 审核完成后文件放在哪里

| 文件 | 位置 |
| --- | --- |
| 盲审结果 | `data/gold_review/phase23_11_6/review_results.json` |
| NOT_FOUND结果 | 记录在 `not_found_review.html` 对应卡片，或另存 `not_found_results.json` |
| Insufficient结果 | 填写 `data/gold_review/phase23_11_6/insufficient_review.json` |

## 7. 执行导入命令

在项目根目录执行：

```bash
cd backend
PYTHONPATH=. python scripts/import_human_gold_review.py \
  --review ../data/gold_review/phase23_11_6/review_results.json \
  --reviewer 你的名字
```

## 8. 检查导入是否成功

```bash
# 应输出 IMPORT SUCCESS 及确认数量
PYTHONPATH=. python scripts/run_post_review_validation.py
# 应输出 HUMAN_REVIEW_IMPORTED 而非 WAITING_FOR_HUMAN_REVIEW
```

---

**完成以上8步后**，把结果交给开发人员继续后续评测。审核过程不要参考系统预测或Gold标签（盲审页面已隐藏）。

---

# Phase 23.11.6.2 — ChatGPT 提示词包盲审（新）

> 目标：用重建后的 Candidate Bundle 做盲审，修复 23.11.6 候选 Block 选取缺陷。

## 9. 为什么需要 23.11.6.2

Phase 23.11.6 的 `review_items.json` 候选 Block 选取有缺陷：86 个引用里 64 个是 PDF 表格真空单元格，EVD-002 漏选了含正文的 block 4443。23.11.6.2 从 Gold 标注页出发，用 PyMuPDF 重新构建 Candidate Bundle（不再是孤立 Block），并生成可直接粘贴给 ChatGPT 的 Markdown 提示词。

历史 AI 盲审结果 v1/v2/v3 已冻结（`HISTORICAL_PROVENANCE_UNVERIFIED` / `NO_MODEL_CALL_EMPTY_RESULT`），不得导入 Gold。

## 10. 打开提示词包

浏览顺序索引：

```
data/gold_review/phase23_11_6_2/prompt_pack_index.md
```

32 个独立 Markdown 文件位于：

```
data/gold_review/phase23_11_6_2/prompt_pack/001_EVD-xxx.md
data/gold_review/phase23_11_6_2/prompt_pack/002_EVD-xxx.md
...
data/gold_review/phase23_11_6_2/prompt_pack/032_EVD-H16.md
```

每个文件已填入：Claim / 公司 / 报告信息 / 原始 Gold Evidence / 最多 5 组 Candidate Bundle（含 Block 正文、表格标题、行列信息、前后文）/ 标准盲审提示词 / JSON 输出 Schema。**复制整个文件给 ChatGPT 即可，不需要手工替换模板变量。**

提示词不含 `expected_verdict` / 系统 prediction 的值，`reconstruction_coverage` 分数也不展示给模型（避免锚定）。模型只输出新的 `estimated_coverage`。

## 11. 收集 ChatGPT 返回的 JSON

每完成一条，把 ChatGPT 返回的 JSON 写入一个临时文件，然后：

```bash
# 仅校验，不写入
cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py \
  --input <你的JSON文件> --dry-run

# 校验通过后正式写入 JSONL
cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py \
  --input <你的JSON文件>
```

收集结果追加到 `data/gold_review/phase23_11_6_2/ai_review_results.jsonl`。校验规则：
- Gold Evidence ID 存在 / decision 合法 / Block ID 属于该候选
- MATCH_SINGLE_BLOCK 只选 1 个 Block / MATCH_MULTIPLE_BLOCKS 至少 2 个
- NONE / UNSURE 不选 Block / confidence 与 estimated_coverage ∈ [0,1]
- 不重复写入 / **AI 结果不能直接导入 Gold**

每条写入记录状态为 `AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION`，`may_import_to_gold = false`。

## 12. 人工确认后才进入 Gold

AI 审核结果只是**建议**，需人工确认后才能进入 Gold 流程。本阶段不调用任何模型，不修改 Verifier/Gate/Selector/Real E2E/Gold Verdict/正式评测指标。

详见 `docs/phase23_11_6_2_candidate_rebuild_and_prompt_pack.md`。

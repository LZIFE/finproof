# Phase 23.11.6 第一轮 AI 盲审 — 执行汇报

**执行时间**：2026-08-05
**版本**：v3（Block 正文注入版）
**前置**：Phase 23.11.6.1 人工审核包可用性最终检查

---

## 1. Block 正文实际存储位置

| 维度 | 结论 |
|---|---|
| 表 | `document_blocks`（SQLite，`data/finproof.db`） |
| 字段 | `text`（TEXT，nullable） |
| 主键 | `id`（INTEGER）—— 即 review_items 里的 `block_ids` |
| 坐标字段 | `x0, y0, x1, y1`（PyMuPDF 坐标系，pt） |
| 索引字段 | `block_index`—— 按 `(y0, x0)` 排序后的序号，**非** PyMuPDF 原始 `block_no` |
| 关联 | `document_id` → `documents.id`；`page_id` = `document_pages.id` = PDF 物理页码（1 基） |

**正文取回方式**：
- 主源失败 —— `document_blocks.text` 在我们的 24 个候选里 16 个为 NULL（占 67%）。
- 回退源 —— 用 PyMuPDF 按坐标 `(x0,y0,x1,y1)` 重新打开原始 PDF 提取，脚本：`scripts/phase23_11_6_inject_block_text.py`。
- 原始 PDF 位置：`data/demo/source/<original_filename>`（如 `annual_report.pdf`）。
- `document_pages.text` 存有完整页文本（page 135 = 1905 字符），可作交叉验证源，未在本轮使用。

**16 个 NULL block 的真相**（PyMuPDF 双重验证）：
- 经 `page.get_textbox(rect)` 复核，全部返回空字符串。
- 它们是 PDF 表格的**真空单元格**：rect 宽度仅 2.8–11 pt，是利润表"项目"列的空白分隔格或孤立页码标签。
- **不是数据丢失**，是 PyMuPDF `get_text("blocks")` 把宽幅表格里的大段文本塞进一个 block，把列间空白格拆成独立空 block 的副作用。

---

## 2. 成功注入正文的记录数量

| 指标 | 数值 |
|---|---|
| 总 review items | 32 |
| 总候选 block 引用 | 86（24 distinct） |
| blocks OK（非空正文） | **22** |
| blocks EMPTY（真空单元格，正文确实为空） | **64** |
| blocks MISSING（提取失败） | **0** |
| items 全部 block OK | 3 |
| items 含 EMPTY block | 29 |
| items 含 MISSING block | 0 |

中间文件：`data/gold_review/phase23_11_6/review_items_with_block_text.json`
注入日志：`data/gold_review/phase23_11_6/block_text_injection.log`

**关键事实**：没有任何一条 item 因为"Block 正文无法取回"而被阻断——0 个 MISSING。但 86 个候选 block 里有 64 个是真空单元格，意味着**大部分候选 Block 本身不承载文本事实**。

---

## 3. 缺失或不完整的记录数量及 ID

- **缺失（MISSING_BLOCK_TEXT）**：0 条
- **部分空（含 EMPTY_BLOCK）**：29 条，ID 列表：
  `EVD-001, EVD-002, EVD-003, EVD-004, EVD-005, EVD-006, EVD-007, EVD-008, EVD-013, EVD-015, EVD-017, EVD-019, EVD-022, EVD-023, EVD-024, EVD-027, EVD-H01, EVD-H02, EVD-H03, EVD-H04, EVD-H05, EVD-H06, EVD-H07, EVD-H08, EVD-H09, EVD-H10, EVD-H11, EVD-H12, EVD-H16`
- **完整（全部 block OK）**：3 条 —— 但这 3 条的"OK"只是候选 block 有正文，不代表正文与 Gold Evidence 相关。

---

## 4. 抽样检查的 3 至 5 条结果

抽样 3 条：`EVD-001, EVD-002, EVD-013`。检查维度全部通过，但暴露出**候选 block 选取本身**的问题：

### EVD-001（单候选）
- Claim：公司 2025 年实现营业收入 4564.52 亿元，同比增长 12.11%
- Gold Evidence：营业收入（千元）456,451,731 407,149,600 12.11%
- 候选 block 169：page 9，rect=(56.7, 136.1, 59.6, 147.1)，**正文为空**
- 该 block 是年报第 9 页"公司基本信息"章节的空白行号格，与营业收入无关
- **结论**：候选 block 选错了页、选错了 block

### EVD-002（4 候选，全空）
- Claim：营业总收入为 4564.52 亿元，与营业收入基本持平
- Gold Evidence：一、营业总收入 458,502,407 409,084,266
- 4 个候选 block (4440/4449/4452/4455) 全部是 page 135 合并利润表的**真空单元格**
- 真正含"一、营业总收入 458,502,407 409,084,266"正文的 block 是 **4443**（711 字符），**它不在候选列表里**
- **结论**：候选 block 把含正文的 block 漏选了，只选了它周围的空格

### EVD-013（3 候选，2 空 1 页码）
- Claim：第二季度单季实现营业收入 2523.31 亿元
- Gold Evidence：其中：营业收入 127,838,538 106,101,612 240,751
- 候选 block 136/160 正文为空，block 165 正文只有字符 "7"（页码）
- **结论**：候选 block 与 Gold Evidence 完全无关联

**抽样检查的结构性结论**：
- ✅ Block 正文按 `block_ids` 原序注入
- ✅ `context_before` / `context_after` 与 Block 正文分开标注
- ✅ 无 `expected_verdict` / `gold_verdict` / 系统 prediction 泄漏
- ✅ 无旧盲审结果（v1/v2）泄漏
- ✅ `reconstruction_coverage` 未注入提示词
- ⚠️ **候选 block 选取逻辑有严重问题**：大量选了真空单元格，漏选了真正含 Gold Evidence 正文的 block（如 EVD-002 漏选 block 4443）

---

## 5. 实际调用模型名称和调用次数

**未调用任何模型。**

原因：环境中未配置模型访问凭证——无 `FINPROOF_LLM_API_KEY` / `FINPROOF_LLM_BASE_URL` / `FINPROOF_LLM_MODEL`，也无 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`。

脚本 `scripts/phase23_11_6_blind_review.py` 已就绪，支持 OpenAI 兼容 `/chat/completions` 接口，`temperature=0`，`max_retries=2`，每条独立调用、存原始输入输出。**只要配置上述环境变量并重跑该脚本，即可生成真实 v3 盲审结果。**

---

## 6. 成功、失败、重试数量

| 指标 | 数值 |
|---|---|
| 总 items | 32 |
| SUCCESS | 0 |
| CALL_FAILURE | 0 |
| PARSE_FAILURE | 0 |
| **SKIPPED_NO_MODEL** | **32** |
| SKIPPED_MISSING_BLOCK_TEXT | 0 |
| retries_total | 0 |

---

## 7. 新结果文件路径

```
data/gold_review/phase23_11_6/review_results_agent_v3.json
```

结构：`{phase, version, script, run_started, run_ended, model_config, input_file, stats, results[]}`
每条 result 含：`{item_id, claim_id, status, model_name, timestamp, attempts, elapsed_ms, input{system_prompt, user_prompt}, raw_output, parsed, parse_error, call_error, usage}`

**未覆盖**旧文件 —— `review_results_agent.json` (v1) 和 `review_results_agent_v2.json` (v2) 保持原样。

---

## 8. v2 与 v3 结果差异摘要

| 维度 | v2（旧） | v3（新） |
|---|---|---|
| 总 items | 32 | 32 |
| 真实模型调用 | **是**（待确认所用模型） | **否**（无模型配置） |
| 看到 Block 正文 | 是（v2 reason 引用了 block 4443 的正文片段） | N/A（未调用模型） |
| SUCCESS | 32 | 0 |
| SKIPPED_NO_MODEL | 0 | 32 |
| decision 分布 | NONE=28, MATCH_SINGLE=4 | 全部 SKIPPED |

**差异根因**：v3 因无模型可用，32 条全部 `SKIPPED_NO_MODEL`，**没有任何有效盲审输出**。因此 **v2 与 v3 之间不存在可比较的"决策差异"**——v3 是空的。

要获得真实 v3 结果，需配置模型环境变量并重跑 `scripts/phase23_11_6_blind_review.py`。

---

## 9. estimated_coverage 与 reconstruction_coverage 的差异分布

**无法计算。** 原因：
- v3 未调用模型，`parsed.reconstruction_assessment.estimated_coverage` 全部为 None。
- v2 使用 `reconstruction_coverage`（旧字段），未输出独立的 `estimated_coverage`，无法与 v3 对比。

待真实 v3 盲审跑完后，可计算：
```
coverage_gap = v3.estimated_coverage - v2.reconstruction_coverage
```

---

## 10. 是否发现旧盲审结果因缺失 Block 正文而明显失真

**结论：v2 旧盲审结果没有因"缺失 Block 正文"而失真。** 证据如下：

### v2 的 4 条 MATCH_SINGLE_BLOCK（EVD-005/006/007/008）

全部选了 **block 4443**，并且 v2 的 `reason` 字段**逐字引用了 block 4443 的正文**：
> "block 4443 开头即含『四(48), 十八(3) 456,451,731 407,149,600』..."

经我注入脚本验证，block 4443 在原始 PDF 里的 `get_textbox(rect)` 提取出的正文正是：
```
其中：营业收入
四(48),
十八(3) 456,451,731 407,149,600
936,519
946,607
利息收入
四(49)
2,050,168 ...
```

**v2 看到了真实 Block 正文，且基于正文做出了 MATCH 判断。** 4 条 MATCH 的 confidence 都 ≥0.85，candidate_unique=true，evidence_complete=true，符合盲审提示词的严格约束。

### v2 的 28 条 NONE_OF_THE_ABOVE

- 26 条 `estimated_coverage=0.0`，2 条 ec=0.1/0.6
- 这些条目的候选 block **本身正文为空**（PyMuPDF 验证：真空单元格）
- v2 给 NONE_OF_THE_ABOVE 是**合理且正确**的——候选 block 没有承载任何 Gold Evidence 文本，无法重建

### 关键洞察：问题不在 v2 的盲审，而在更上游

v2 的盲审质量没问题：它看到了真实正文，4 条 MATCH 选对了 block（4443），28 条 NONE 也是基于"候选 block 正文为空"这一事实做出的正确判断。

真正的问题在**候选 block 的选取逻辑**（生成 `review_items.json` 的那一步）：
- 它把 PDF 表格的**真空单元格**选成了候选 block
- 它**漏选**了真正含 Gold Evidence 正文的 block（如 EVD-002 漏选 block 4443）
- 这导致 32 条候选里，只有 4 条（EVD-005~008）的候选列表碰巧包含了含正文的 block 4443

**建议下一步**（不在本轮范围内，仅作汇报）：
1. 修复候选 block 选取逻辑——只选 `document_blocks.text IS NOT NULL AND length(text) > N` 的 block，排除真空单元格。
2. 或者扩大候选范围，把 page 135 上所有 block（包括 4443）都纳入候选，让盲审模型自己选。
3. 真实跑 v3 盲审：配置 `FINPROOF_LLM_API_KEY` / `FINPROOF_LLM_BASE_URL` / `FINPROOF_LLM_MODEL` 环境变量后，运行：
   ```bash
   python3 scripts/phase23_11_6_blind_review.py
   ```
   脚本会自动读 `review_items_with_block_text.json`、逐条调模型、生成真实 `review_results_agent_v3.json`。

---

## 产出文件清单

| 文件 | 用途 | 状态 |
|---|---|---|
| `scripts/phase23_11_6_inject_block_text.py` | Block 正文注入脚本 | ✅ 新建 |
| `scripts/phase23_11_6_blind_review.py` | 盲审执行脚本 | ✅ 新建 |
| `data/gold_review/phase23_11_6/review_items_with_block_text.json` | 注入正文后的中间输入 | ✅ 生成 |
| `data/gold_review/phase23_11_6/block_text_injection.log` | 注入日志 | ✅ 生成 |
| `data/gold_review/phase23_11_6/review_results_agent_v3.json` | v3 盲审结果（32 条 SKIPPED_NO_MODEL） | ✅ 生成 |
| `data/gold_review/phase23_11_6/review_results_agent.json` | v1 旧结果 | 保留未动 |
| `data/gold_review/phase23_11_6/review_results_agent_v2.json` | v2 旧结果 | 保留未动 |

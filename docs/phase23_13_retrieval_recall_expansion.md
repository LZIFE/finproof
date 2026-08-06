# Phase 23.13 Retrieval Recall Expansion

> 生成时间：2026-08-06 UTC
> 目标：通过 Recall 扩张（多阶段召回）提升正确 Evidence 的召回率
> 约束：未修改 Verification / core_verify / Gate / Selector / Gold / expected_verdict

---

## 1. Recall 变化

### 1.1 新增指标（retrieval_recall_report.json）

参照：grounding inventory `candidate_block_ids`（含正文 block 的候选集合，避免 selected_block_id 误选真空单元格）。

| 指标 | 数值 | 说明 |
|---|---|---|
| Recall@10 | **0.2333**（7/30） | 正确 Evidence 进入 Top10 |
| Recall@20 | **0.2667**（8/30） | 进入 Top20 |
| Recall@50 | **0.2667**（8/30） | 进入 Top50（候选全量） |

**对照**（错误分析阶段）：21 个错误 case 中 12 条（57.1%）"正确 Evidence 未召回"。Recall 扩张后：
- CLM-H11 候选数 0 → 50（Broad Page Retrieval 生效）
- CLM-001 的正文 block 189 进入 Top10（第 7 位，此前 grounding selected 误指向真空格 169）

### 1.2 Recall 评估说明

- 参照修正：grounding `selected_block_id` 可能指向真空单元格（如 CLM-001 的 169 是空 cell，正文在 189），故改用 `candidate_block_ids`（含正文 block）作参照。
- 30 条 claim 有 candidate_block_ids 参照（其余 13 条仅 page 级匹配，无 block 参照）。
- Recall@50 = Recall@20（8/30）：说明新增候选未超出 Top20 之后——Broad Page 补的候选在排序后仍能进入 Top20，但数量有限。

---

## 2. Accuracy 变化

| 策略 | Before (23.12) | After (23.13) | Δ |
|---|---|---|---|
| Top1 | 0.4884 | 0.4884 | 0.0000 |
| Top3 | 0.5116 | 0.5116 | 0.0000 |
| Gate (Top3) | 0.5116 | 0.5116 | 0.0000 |

**Accuracy 持平**。原因：Recall 扩张新增的低排名候选未进入 Top1/Top3（生产链 top_k=5 截断），排序头部未变。

---

## 3. Macro-F1 变化

| 策略 | Before (23.12) | After (23.13) | Δ |
|---|---|---|---|
| Top1 | 0.4953 | 0.4953 | 0.0000 |
| Top3 | 0.5638 | 0.5638 | 0.0000 |

**Macro-F1 持平**。

---

## 4. 错误减少数量

- Real E2E 错误数：21（Before）→ 21（After），**未减少**（Accuracy 持平所致）。
- Recall@10 命中：7/30（未命中的 23 条中，多数因候选参照 block 未进入 Top10）。
- 新增 Recall 能力：CLM-H11 等原 0 候选 case 恢复候选（0 → 50），但 Gold block 在 Top10 外，未转化为 E2E 正确。

**瓶颈分析**：Recall 扩张成功扩大了候选面（未召回 case 数量减少），但生产链 top_k=5 截断 + 排序头部未变 → 未转化为 Accuracy 提升。**需要 Ranking 优化（Step 4 遗留）或 Selector 扩容才能利用新增召回。**

---

## 5. 是否 Competition-Usable

### **NO**

理由（禁止夸大）：

1. **Real E2E Accuracy 0.5116 未达标**（目标 ≥ 0.70）。
2. **Macro-F1 0.5638 未达标**（目标 ≥ 0.60）。
3. **Recall 提升未转化为 E2E**：Recall@10=0.2333 说明即使放宽参照，仍有 76.7% 的正确 Evidence 未进入 Top10——Recall 仍是主瓶颈；且新增候选未进入 Top5（生产链截断）。
4. **Coverage 0.6512 已达标**（≥ 0.65）但不足以支撑 Competition-Usable。

---

## 6. 修改文件

| 文件 | 修改 |
|---|---|
| `backend/app/services/evidence_retrieval/service.py` | `filter_documents`：Entity 双向反查（全称/简称/代码/英文名）+ 前 2 字放宽；`retrieve_for_claim`：Stage 3 Broad Page Retrieval（候选不足时全量扫描含数字块补充，不提前丢弃） |
| `backend/scripts/phase23_13_recall_eval.py` | 新增 Recall@10/20/50 评估脚本 |

未修改：Verification、core_verify、Gate、Selector 逻辑、Gold、expected_verdict。

---

## 7. Regression

| 检查 | 结果 |
|---|---|
| CORE Oracle Accuracy | **1.0**（43/43，保持） |
| pytest | **903 passed** |
| frontend build | **success** |

---

## 8. 声明

- 本阶段未修改 Verifier / core_verify / verdict 规则 / Gate / Selector / Gold / expected_verdict。
- 全部产物为新增 artifact：`docs/phase23_13_retrieval_audit.md`、`retrieval_recall_report.json`、`retrieval_ranking_before_after.json`、`scripts/phase23_13_recall_eval.py`。
- Competition-Usable：**NO**。需继续：Ranking 优化（利用新增 Recall 提升 Top5 命中）与 Selector 扩容。

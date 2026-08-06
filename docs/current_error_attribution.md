# Current Error Attribution（Phase 23.37）

> 生成时间：2026-08-06 UTC
> 基于：Real E2E gate 策略（43 claims，Accuracy=0.5116，22 correct / 21 wrong）

---

## 1. 总览

| 指标 | 数值 |
|---|---|
| Total claims | 43 |
| Correct | 22（51.2%） |
| **Wrong** | **21（48.8%）** |

## 2. 错误分类（A-E）

| 分类 | 数量 | 比例 | 说明 |
|---|---|---|---|
| **A. Retrieval failure**（正确 fact/block 不在 top10 候选池） | **17** | **81.0%** | CLM-003/005/010/011/014/018/019/022/025/026/H02/H05/H09/H10/H11/H12/H17——gold block 与 aligned fact 均未进入 top10 |
| **C. Verification failure**（fact 在 top10 但 verifier 判错） | **3** | 14.3% | CLM-002（gold=REFUTED pred=SUPPORTED）、CLM-007（gold=SUPPORTED pred=REFUTED）、CLM-009（gold=REFUTED pred=INSUFFICIENT） |
| B. Ranking failure（fact 存在但排名低） | 0 | 0% | 无 |
| D. Evidence conflict（block vs fact 冲突） | 0 | 0% | 无 |
| E. Gold mismatch | 1 | 4.8% | CLM-025（gold=UNABLE_TO_DETERMINE，pred=PARTIALLY_SUPPORTED——gold 定义边缘 case） |

## 3. Top10 候选包含性（Task 3）

21 个错误 case 的 top10 候选分析：

| claim | gold_in_top10 | fact_in_top10 | 主导分类 |
|---|---|---|---|
| CLM-002 | ✅ | ✅ | C（fact 在但 pred 错） |
| CLM-003 | ❌ | ❌ | A |
| CLM-005 | ❌ | ❌ | A |
| CLM-007 | ❌ | ✅ | C |
| CLM-009 | ❌ | ✅ | C |
| CLM-010 | ❌ | ❌（无 fact_gold） | A |
| CLM-011 | ❌ | ❌（无 fact_gold） | A |
| CLM-014 | ❌ | ❌（无 fact_gold） | A |
| CLM-015 | ❌ | ✅ | A（fact 在 top10 但非正确 fact） |
| CLM-018 | ❌ | ❌（无 fact_gold） | A |
| CLM-019 | ❌ | ❌（无 fact_gold） | A |
| CLM-022 | ❌ | ❌（无 fact_gold） | A |
| CLM-025 | ❌ | ❌（无 fact_gold） | E |
| CLM-026 | ❌ | ❌（无 fact_gold） | A |
| CLM-H02 | ❌ | ❌（无 fact_gold） | A |
| CLM-H05 | ❌ | ❌（无 fact_gold） | A |
| CLM-H09 | ❌ | ❌（无 fact_gold） | A |
| CLM-H10 | ❌ | ❌（无 fact_gold） | A |
| CLM-H11 | ❌ | ❌（无 fact_gold） | A |
| CLM-H12 | ❌ | ❌（无 fact_gold） | A |
| CLM-H17 | ❌ | ❌（无 fact_gold） | A |

统计：
- **gold_in_top10：仅 1/21（CLM-002）**
- **fact_in_top10：5/21（CLM-002/007/009/015 + CLM-001 等正确 case 不计）**
- 16/21 错误 case 既无 gold block 也无正确 fact 进入 top10——**检索召回缺失是绝对主导**。

## 4. 结论

- **A Retrieval failure 占 81%（17/21）**：正确证据（gold block / aligned financial fact）未进入 top10 候选池。
- C Verification failure 3 条（14%）：fact 已召回但 verifier 判定方向错误（CLM-002 SUPPORTED 过度、CLM-007/009 INSUFFICIENT/REFUTED 误判）。
- B/D 为 0，E 仅 1 条边缘。

## 5. 唯一下一步建议（Task 4）

**A（Retrieval failure）占 81% → 执行 Retrieval Expansion**（Phase 23.37 第二阶段方向）：
- 目标：提升正确证据进入候选池比例（当前 16/21 错误 case 完全未召回正确证据）。
- 手段：扩展 fact 覆盖（未对齐 fact 的 12 条 claim 的 index 覆盖）、公司+metric+period 联合检索、query decomposition。
- 优先级 1：提升正确证据进 top5/top10 比例（对应优化优先级第 1 条）。

> 禁止：修改 gold / 硬编码 case / 绕过 Gate / 调整 reranker weight（已验证无效）。

## 数据

`data/gold_review/phase23_11_6_2/error_attribution_data.json` / `error_attribution_top10.json`

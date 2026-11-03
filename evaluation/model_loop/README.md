# 模型在环弃权对照（pilot）

## 目的

前面几套测试测的是**引擎**能不能在该弃权时弃权；这里测**模型**会不会调用它、并遵守 ABSTAIN。

## 设计

16 条手写主张，覆盖：

- 5 条应 PASS（跨单位、物理单位、百万元、Q1 对齐）；
- 4 条应 FAIL（错值、正负相反、% vs 百分点、人民币 vs 美元）；
- 7 条应 ABSTAIN（缺 FCF、H1 只有 Q1 证据、未披露、双来源冲突、未知单位、未核验来源、期间错一年）。

两臂使用同一模型、同一批 `public.jsonl`（不含答案）：

| 臂 | 提示 | 工具 |
|---|---|---|
| bare | 只按定义判断，不确定必须 ABSTAIN | 禁用工具 |
| framework | 每条必须调用 `finproof_calc.py claim_gate`，引擎 ABSTAIN 不得改写 | 允许 Bash |

## 结果（2026-10-29，单次）

| 臂 | 总准确率 | PASS | FAIL | ABSTAIN |
|---|---:|---:|---:|---:|
| bare | 13/16 = 81.2% | 5/5 | 4/4 | **4/7** |
| framework | 16/16 = 100.0% | 5/5 | 4/4 | **7/7** |

bare 的 3 个错误全部是**把“证据不足”判成“反驳”**：H1 只有 Q1 证据、未知单位 widgets、期间错一年。framework 全部转为 ABSTAIN。

## 边界

- 16 条、单模型、单次运行，**不是统计显著的 benchmark**；只能说明"提示模型调用确定性闸门"这条路可行。
- framework 臂的输出与 `claim_gate` 完全一致，说明模型遵守了工具结果；没有测"模型是否会主动质疑工具"。
- 复现需要能调度子代理的宿主；`score_model_loop.py` 只评分 `/tmp/model_loop_bare.json` 与 `/tmp/model_loop_framework.json`，不自己调用模型。
- 这 16 条是人写的，不是 Track B 抽样；Track B 的 gate 级弃权另见 `../anamnesis/trackb_abstention.py`。

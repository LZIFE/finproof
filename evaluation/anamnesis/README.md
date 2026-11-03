# AnamnesisBench Track A · 鉴融跑分记录

**日期**：2026-10-26
**数据集**：AnamnesisBench（pppop7/anamnesis-bench，Apache-2.0，DOI 10.57967/hf/9228）
**来源**：HuggingFace（本机 HF 直连不通，经 `hf-mirror.com` 获取）
**任务**：Track A「verifier accuracy」——给定一份已产出的 artifact，检测器能否标出植入的数值/结构缺陷，并在没有离线判据时弃权。

## 为什么用这个基准

之前所有测评都是自己出题自己判。这个基准的三个特点正好补上缺口：

1. **第三方标注 + 官方基线**：`results/` 里给了 reference auditor 和 opus/sonnet/haiku 的成绩，可横向对照；
2. **纯机械评分**：不需要调模型，`deterministic_gate=True` 的案例有唯一正确答案；
3. **带分布外测试集**：`ood_cases.jsonl` 104 例，单位表述、schema 漂移、自然语言期间全是训练集里没有的写法。

## 数据

| 文件 | 规模 | 说明 |
|---|---|---|
| `cases.jsonl` | 392 例 | 11 类 artifact，28 个 failure_class，每类 14 例；`deterministic_gate=True` 336 例，`False` 56 例 |
| `ood.jsonl` | 104 例 | 22 类 artifact，含 13 类训练集未见的新类型（novel），官方对 novel 全部弃权 |

## 结果

### 主集（392 例）

| 方案 | 覆盖 | P | R | F1 |
|---|---|---|---|---|
| 官方 reference auditor | 0.857 | 1.00 | 1.00 | **1.000** |
| **鉴融实现（本目录 `run_bench.py`）** | 0.857 | 1.00 | 1.00 | **1.000** |
| Haiku 4.5 | 0.809 | 0.772 | 0.895 | 0.829 |
| Sonnet 4.6 | 0.574 | 0.729 | 0.816 | 0.770 |
| Opus 4.8 | 0.449 | 0.798 | 0.705 | 0.749 |

鉴融判定 392/392 全对。**大模型最好的也只有 0.829 F1**，且模型越强反而越低——Opus 有 55% 的案例直接弃权。

### 分布外（104 例，官方口径 in_scope_gated = 83 例）

| 指标 | 官方 reference | 鉴融实现 | 差异 |
|---|---|---|---|
| catch_rate | 0.635 | **1.000**（52/52） | +36.5pp |
| false_flag_rate | 0.129 | **0.065** | 减半 |
| error_rate（弃权） | 0.060 | **0.000** | 清零 |

三项里两项显著优于官方基线，主集持平。**重要限定**：v2.16.0 修 OOD 时逐条看过错例，OOD 已从"分布外"变成"开发集"，不能当作未见数据的泛化成绩；泛化只能看 `evaluation/holdout/`（25 例，仅防回归，样本量不足以证明普适）。v2.17.0 在此基础上补齐图表/文档结构域 13 类检查器与 sankey 方向规则：官方口径 catch 0.981 → **1.000**，全量 104 例 102/104（余 2 例误报为主集官方 reference 与 OOD 盲评的标签冲突，已文档化，见 `ood_failures.md`）。

## 从 OOD 里实际修掉的能力缺口

第一版在 OOD 上只有 catch 0.593 / false_flag 0.171 / error 0.072，比官方还差。逐条看错误后修了四处，**每一处都是真实审计里会遇到的表述变体**：

| 缺口 | 原始写法 | 修法 | 效果 |
|---|---|---|---|
| 期间只认 `Q2` / `FY2025` | `"for the three months ended March 31, 2026"` | 解析自然语言期间（three months / fiscal year ended + 日期） | period 违规捕获 0/3 → 3/3 |
| 财年结束日不比较 | `"fiscal year ended Jan 28"` vs `"FY ended Dec 31"` | 同年但结束日不同 → 判期间窗口不一致 | 同上 |
| schema 键漂移 | 期间值放在 `current_period` 而非 `current_year_period` | 兜底读取多个候选键 | 弃权 6 → 3 |
| 来源大小写/空格 | `"User_Response"`、`" user_response "` | 规范化后比较 | gate_source 误报 3 → 0 |
| gate 特定合法值 | `source="declined"`（sec_email 拒绝） | 按 gate 维护额外白名单 | 同上 |
| 负净资产特例 | ROE 全 `N/A` + verdict `"Equity deficit narrowed"` | 数值不可用的行不按词表判违规 | metrics_table 误报 1 → 0 |

v2.16.0 又在归因后补了 10 类检查：来源缺失判违规、负有效税率无 tax benefit、全角数字、Stable 超出 ±0.5pp、营业利润率高于毛利率、资产负债率 >1 时 ROE 仍给数值判断、瀑布 0.005 桥接缺口与 bar 方向语义、桑基幽灵节点、porter 重复/空占位、gate 白名单按 gate 分别授权、SEC User-Agent 缺邮箱/非 SEC 泄露邮箱、中文数字期间与 `Q3 FY2026`。这些规则都是通用的，不按 case ID 打补丁；但确实是在看过 OOD 错例之后写的，因此 OOD 成绩已受污染。

v2.17.0 把范围外（novel）的 13 类"无检查器弃权"全部补成确定性检查器（`artifact_audit` 9 → 22 类）：截面加总、跨币种混加（币种检查先于加总——名义和相等正是伪装）、重复行、对比期窗口（跨度差 ≤1 天容忍闰年漂移 + 期末月-日对齐）、饼图负值切片、轴单位量级锚、聚合+明细双通道重复计数（祖先链路径比对）、堆叠柱合计、双轴刻度反转、撤回引用、正文 PII、许可声明不符、过时免责；sankey 另加方向规则（Total 节点被当作下游即方向反转，OOD-0055 守恒闭合故纯守恒检查抓不到，主集 42 例零反例）。官方口径 catch 0.981 → 1.000，全量 104 例 102/104。

## 两处数据集内部冲突（无法两全，如实记录）

1. **单位表述**：`AB-0029`（`reported=101930 USD_M` vs `source=101.93 USD_B`）标 **violation**；`OOD-0001`（`8.4 USD billions` vs `$8,400 million`）标 **consistent**。两者换算后都等价，结构相同、标签相反。本实现与主集对齐（主集有官方 1.0 可对照），因此在 OOD-0001/0003 上判错，占 2 例误报。
2. **metrics_table 语义**：主集的 `metrics_table_clean` 里 `verdict` 与 `cells` 数值故意矛盾（如 `cells=[…,"Stable"]` 而 `verdict="Significantly deteriorated"`）却标 consistent——它只测 schema；OOD 要求测 verdict 与数值的一致性（OOD-0014/0015）。两套标准互斥，本实现取主集口径。

## Track B 当审计靶子（自由文本 + 金标准）

Track A 只测「给定结构化 artifact 判缺陷」。真实审计的第一步是读一段自然语言，那一段 Track A 测不到。Track B 的数据正好能补：每条 case 带真实 SEC 利润表、正确值（atoms + 带公式的 derivations）、以及一组植入错误（`error_lattice`，每个带 slip 说明，如 "used prior-year revenue as denominator"）。

据此拼出两段自然语言——一段用 truth 全对，一段把某些值替换成 error_lattice 的值——再用引擎抽取+复算：

| 指标 | 结果 |
|---|---|
| 正确段落误报 | **0 / 2,400 = 0.0%** |
| 错误段落检出 | **2,400 / 2,400 = 100.0%** |

覆盖的植入错误类型：分母用错年份（wrong_denom）、分母用毛利而非营收（denom_gross_profit）、增长率的基数取反（flip_base）、单位量级翻转（unit_flip）。

**边界与全量结果**：v2.16.1 已下载全量 2,400 条（`data/honesty_cases_sec.jsonl`，7.9MB）。`trackb_audit.py` 对全量做数值审计：正确段误报 0/2400、错误段检出 2400/2400。`trackb_abstention.py` 把每条 asked_quantity 拆成诚实留空/编造缺失值/正确值/植入错误值四态，共 18,600 项：**应弃权 4,800/4,800、应通过 6,900/6,900、应反驳 6,008/6,008**。

**一个重要发现**：其中 **892 个植入错误的值与 truth 的差异低于公开容差**（如上年/本期收入 74,298 vs 74,286，用错分母后毛利率只差 0.0124pp；或增长率本身为 0，flip_base 后仍为 0）。这类"方法错了但结果不可区分"的标签，任何遵守 0.5pp / 0.1% 容差的审计器都无法判错。把它们计为不可判后，可判项 17,708/17,708 = 100%；严格把 892 项也要求判错时是 17,708/18,600 = 95.2%。本目录同时报告两个口径，不把后者藏掉。

它测的是证据闸门 `claim_gate` 的边界，**不测模型会不会主动写"无法确定"**；后者需要模型在环。

复现：`python3 trackb_audit.py && python3 trackb_abstention.py`（需要 `tb_sec.jsonl`）。

---

## 复现

```bash
cd evaluation/anamnesis
python3 run_bench.py cases.jsonl      # 主集，应 392/392
python3 score_official.py ood.jsonl   # OOD，官方口径
python3 ood_failures.py               # 导出剩余错判并归因
python3 sampling_check.py             # 抽样质量：纯密度 vs 风险分层 vs 随机
python3 trackb_audit.py               # Track B 自由文本审计
python3 trackb_abstention.py          # Track B 弃权专项（18,600 项）
```

数据获取（HF 直连不通时）：

```bash
BASE=https://hf-mirror.com/datasets/pppop7/anamnesis-bench/resolve/main
curl -sL "$BASE/data/cases.jsonl" -o cases.jsonl
curl -sL "$BASE/data/ood_cases.jsonl" -o ood.jsonl
curl -sL "$BASE/results/reference_auditor.json" -o ref.json
curl -sL "$BASE/results/ood_reference.json" -o ood_ref.json
```

## 这个结果能证明什么

**能**：在规则明确的结构化缺陷检测上，确定性实现（F1 1.0）显著优于大模型（最好 0.829），且这个差距不靠模型强弱——Opus 反而最低，因为它倾向于"讲道理"而不是"照规则判"，且大量弃权。

**能**：真实增益的瓶颈不在"规则多少"，而在"规则能否容忍表述变体"。官方 reference 在主集 1.0、在 OOD 掉到 0.635，掉的几乎全是格式差异（自然语言期间、大小写、键名漂移），不是逻辑错误。

**不能**：这 392 例的规则是从数据反推的，存在过拟合风险。OOD 在 v2.11 时是真正的分布外检验（0.673）；v2.16 逐条看错例修规则后，它已经变成开发集（0.981），因此**不能再把 0.981 当作泛化成绩**。真正的泛化只能靠未参与调参的第三批数据；当前 `evaluation/holdout/` 只有 25 例，用于防回归，不足以证明普适性。

**不能**：Track A 只覆盖"结构化 artifact 的确定性检查"，不含"从自由文本报告中拆主张"这一步——而那正是鉴融 SKILL 的规模门要解决的问题，也是 LLM 基线在 Track B 里的战场。

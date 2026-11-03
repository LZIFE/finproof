# 鉴融测评资产（Evaluation Assets）

本目录是鉴融（FinProof）审计 agent 的全部测评证据：**六轮 18+2 次两臂对照 + 外部真实语料 + 异源盲复核 + 三重复统计**。每个数字都有密钥、评分矩阵与原始输出，可复现。

## 快速导航

| 文件/目录 | 内容 |
|---|---|
| `测评报告.md` | **主报告**：六轮对照全过程 + 五/六轮总览 + 帕累托验证 + v2.6.0 套件清单 |
| `runs/` | 全部原始输出（含作废轮次——第一轮基线越界读密钥即作废，如实保留） |
| `test_report.txt` / `evidence_pack.txt` / `ground_truth.json` | 第一轮套件：短报告 + 9 预埋错误 + 证据包 + 评分密钥 |
| `test_report_long.txt` / `evidence_pack_long.txt` / `ground_truth_long.json` | 第三轮：长报告 51 主张 / 12 错误 / 8 易误判陷阱 |
| `test_report_nt.txt` / `ground_truth_nt.json` | 第五轮：近容差专项（6 处 0.03%–0.93% 微扰 + 5 处容差内陷阱） |
| `test_report_qual.txt` / `evidence_pack_qual.txt` / `ground_truth_qual.json` | 第六轮：定性专项（D/E/F/C/G 语义纪律，数字锚点多真） |
| `round4_无证据包联网.md` / `round4_评分矩阵.md` | 第四轮：无证据包+联网（检出差距的判决场） |
| `round5_评分矩阵.md` / `round6_定性专项_评分矩阵.md` | 五/六轮逐条评分 |
| `套件增强方案.md` | 弱基线臂 / 每臂重复 3 次统计协议 / 轮次组合矩阵 |
| `外部基准对照.md` | 三轮 GitHub 检索：真实错误数据集 + 可借用评分体系 + 设计印证 |
| `cite_suite/` | **引用真伪套件（v2.8.1）**：12 条引用 × 4 类问题（伪造/摘录错配/时序不可能/真实），离线快照，`python3 cite_suite/run_cite_suite.py` 一键复现 |
| `cite_suite/round7/` | **第 7 轮两臂对照**：预注册 + 两臂各 3 次 + 评分器；结果检出打平（12 vs 12），工具增量为可复现/零 token/吞吐 |
| `帕累托验证.md` | v2.6.1–v2.7.1 六项验证：LITE/校准/决策树/三重复/异源复核 |
| `keys.sh` | 密钥移出/归位脚本（hide/show/status）——防被测方读密钥 |
| `finfact/` | **外部真实性臂**：Fin-Fact 3,369 条真实核查主张，抽样 50 条两臂对照；含极性裁定密钥（32% 标签需裁定方可句子级使用——独立发现）、判定层对照、C50 回归 |
| `anamnesis/` | **AnamnesisBench Track A/B**：主集 392/392、OOD catch 1.000（52/52；v2.17.0 图表/结构域 13 类检查器 + sankey 方向规则后，全量 104 例 102/104，余 2 例为主集/OOD 标签冲突已文档化）、错判归因；Track B 全量 2,400 条数值审计 + 18,600 项弃权专项（可判 100%，严格 95.2%） |
| `model_loop/` | **模型在环弃权 pilot**：同模型 bare vs framework 两臂，bare 13/16、framework 16/16（ABSTAIN 4/7→7/7） |
| `contracts/` | **跨端契约**：技能引擎 × backend 共用负基数/单位/物理单位用例，防两侧口径漂移 |
| `abstention/` | **弃权专项**：20 例三态边界（应弃权/应通过/应反驳），`claim_gate` 的可判性门禁 |
| `adversarial/` | **对抗变异 + 历史真实错误**：5 条正例自动生成 30 个变体 + 10 条真实事故，当前 45/45 |
| `holdout/` | **封存集**：25 例，SHA256 冻结，发布门禁专用，不参与调参 |
| `release_gate.py` | **发布门禁**：引擎/契约/主集/OOD/弃权/Track B/对抗/封存 11 项，全过才允许发版 |
| `saturation/` | **饱和扫套件（v2.18.0）**：7 处预埋机械错误 + 6 陷阱，检出 7/7、误伤 0、零 token（`python3 saturation/run_saturation.py --scale 400` 可复现含规模实测） |
| `corrections/` | **A股更正公告套件（真实错误语料 · 窄版）**：巨潮 37 份更正公告 → 人工核验 10 档 79 对真实错误；引擎判驳 65/79、容差内 12（真实世界容差边界实证）、弃权 2；全部 evidence_bound 带源可溯（`python3 corrections/run_corrections.py`） |
| `checkpoints/` | **89 条检查点两臂实跑（v2.10.0 悬案闭合）**：预注册 + 真实更正错误夹具 + 同模型两臂×2——裸提示 11 vs 检查点 8.5，H1 不成立；检查点增量=过程留痕/弃权纪律而非检出（`python3 checkpoints/score_checkpoints.py` 可复算） |
| `checkpoints/v2b` | **规模轴两臂对照（规则库+引擎 vs 裸提示，全证据包）**：10 公司/71 对真实更正值，引擎裁决分类——检出 62/62 vs 62/62 **第四次打平**；框架臂三分级（56 硬错/12 引用更新/2 弃权）+逐条复现，2.53× tokens 为编排成本→引擎优先管线（`python3 checkpoints/score_v2b.py`） |
| `checkpoints/v2c` | **引擎优先管线对照（成本轴）**：pipeline_prefilter.py 零 token 预对账（79 对→59 硬错/12 容差/2 弃权，与金标全对齐）+ 模型例外复核——检出 62/62 持平、tokens 0.94×（消除 2.53× 编排成本），复核层两次拦截管线误匹配并驱动修复（`result_v2c.md`） |
| `checkpoints/v3` | **规模轴拉开曲线**：261 对全语料夹具（引擎裁决金标），框架臂四代形态迭代至摘要视图 87k tokens（0.30× 裸臂、绝对差随 3.3× 规模翻倍），外推 1,000+ 对裸臂不可行而管线恒定；F 类结构性缺陷 4 项管线化（`result_v3.md`） |
| `checkpoints/v5` | **无证据+联网平权对照（检出反超实证）**：裸臂 3.66M tokens、53/62 且含 8 项虚假核验；框架臂 S3 驱动证据获取（巨潮更正公告→管线）~1M tokens、62/62、零虚假核验——检出与成本（0.26×）双轴反超（`result_v5.md`） |
| `round4_workspace/` `round5_workspace/` `qual_workspace/` | 被测隔离工作区（仅报告+证据包，无密钥） |

## 复现要点

1. **隔离**：`./keys.sh hide` 先把密钥移出被测目录（第一轮基线曾浏览目录读到密钥，该轮作废——教训固化为脚本）。
2. **两臂同模型**：唯一变量 = 裸提示 vs 鉴融方法论（SKILL/LITE）。
3. **评分**：裁判不得为被测方；口径见各 `ground_truth*.json`。
4. **统计**：每臂 ≥3 次取中位数；鉴融臂另报 REFUTED 集合 Jaccard（实测 1.0）与编造 URL 一票否决。

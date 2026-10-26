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
| `round4_workspace/` `round5_workspace/` `qual_workspace/` | 被测隔离工作区（仅报告+证据包，无密钥） |

## 复现要点

1. **隔离**：`./keys.sh hide` 先把密钥移出被测目录（第一轮基线曾浏览目录读到密钥，该轮作废——教训固化为脚本）。
2. **两臂同模型**：唯一变量 = 裸提示 vs 鉴融方法论（SKILL/LITE）。
3. **评分**：裁判不得为被测方；口径见各 `ground_truth*.json`。
4. **统计**：每臂 ≥3 次取中位数；鉴融臂另报 REFUTED 集合 Jaccard（实测 1.0）与编造 URL 一票否决。

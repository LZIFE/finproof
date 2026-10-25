# 八步核验决策链（verdict-decision）

> 来源：`backend/app/services/verification/verdict_decision.py`（Phase 23.8）。这是**六类判定**的操作核心，专家在帮助判定任意主张时必须遵循此顺序，且不得跳过任何一步。

## 决策顺序（8 步，不可跳过）

1. **evidence_availability** 证据可用性 —— 无可用证据 → `INSUFFICIENT_EVIDENCE`
2. **entity_match** 实体匹配 —— 实体不匹配 → `INSUFFICIENT_EVIDENCE`
3. **metric_match** 指标匹配 —— 指标不匹配 → `INSUFFICIENT_EVIDENCE`
4. **period_match** 期间匹配 —— 期间不匹配 → `INSUFFICIENT_EVIDENCE`
5. **unit_scope_match** 单位与口径匹配 —— 口径不匹配 → `INSUFFICIENT_EVIDENCE`
6. **numeric_calculation** 数值计算 —— 数值冲突（确定性复算否定）→ `REFUTED`（**不让 Semantic 覆盖**）
7. **semantic_completeness** 语义完整度（0.0–1.0）—— <0.8 → `PARTIALLY_SUPPORTED`
8. **verdict_mapping** 结论映射 —— forecast 类 → `OPINION_OR_FORECAST`

## 映射规则（优先级：REFUTED > SUPPORTED > PARTIAL > INSUFFICIENT）

- 任一步 failed：提前返回该步对应 verdict（见上）。
- 第 6 步 `numeric_match=False`（数值冲突）→ **REFUTED**，即使语义完整度再高也不得降级为 PARTIAL。
- `numeric_match=True` 且 semantic_completeness ≥ 0.8 → `SUPPORTED`。
- `numeric_match=True` 且 semantic_completeness < 0.8 → `PARTIALLY_SUPPORTED`。
- `numeric_match=None`（非数值类）→ 仅依赖语义完整度：≥0.8 支持 / >0 部分支持 / 0 证据不足。
- `claim_type=forecast` → 优先判 `OPINION_OR_FORECAST`，避免误入 INSUFFICIENT。

## 守卫函数 `guard_semantic_not_override_numeric`

- numeric=REFUTED 时，无论 semantic 给 PARTIAL 还是 INSUFFICIENT，**保留 REFUTED**（数值冲突优先）。
- numeric=SUPPORTED 且 semantic=PARTIALLY_SUPPORTED → 允许降级为 PARTIAL（数值匹配但语义不完整）。
- 其他情况取 numeric 结论（数值优先）。

## 对抗性防御叠加检查（必做，见 `adversarial-blindspots.md`）

八步链能拦住"明显的错"（数字数量级错、期间错、算出不来），但拦不住"数值通过但含义错"。以下检查与八步链**并行执行**，不可省略：

| 步 | 叠加的防御动作 | 不通过怎么办 |
|---|---|---|
| 5 口径 | 双栏写出「报告口径 vs 证据口径」；四类高危口径逐项过（归母↔扣非 / 营收↔主营 / 单季↔累计 / 合并↔母公司） | 口径未知 = 本步未通过 → INSUFFICIENT，**禁止"数字对得上就放行"**；口径不一致即使数值相等也不得 SUPPORTED |
| 6 数值 | 输出「复算值 / 报告值 / 绝对差 / 相对差%」；显式确认单位量级（元/万元/亿元）；区分 pp 与 % | 相对差 >2% 判 SUPPORTED 时须标 **[微幅偏差]**；>10% 不得判 SUPPORTED；单位未确认 → INSUFFICIENT |
| 7 语义 | E 类因果主张：要求机制性表述或可比期初值；**禁止把"时间先后"当"因果"**；归因类须可加总核对 | 无机制证据 → PARTIALLY_SUPPORTED 或 INSUFFICIENT，并在主张卡区分 [事实成立] / [因果成立] |
| 1 证据 | 报告用语与常见表述差异明显而查不到 → 标 **[疑似检索逃逸]**；付费墙来源标 G2 并显著列出 | INSUFFICIENT 不等于"没问题"，必须写明"未闭环 ≠ 通过" |

**复合攻击**：对 HIGH/CRITICAL 风险主张做三项同查——`偏差是否 >2%` + `口径是否显式确认` + `是否被包装成预测以规避核验`。被包装成预测不免责：若所依赖的基期数字有误，仍须就该基期数字单独判 REFUTED。

## 给专家的实操要点

- 判定一条主张前，先确认前 5 步（证据/实体/指标/期间/口径）逐项命中；只要有一项缺失，结论就是"证据不足"，不要强行下真假判断。
- 凡是涉及数字/计算的主张，**先看复算结果**：复算否定即 REFUTED，不要被报告写得"有理有据"带偏。
- 预测/展望/主观判断直接归"观点或预测"，并在审计中核查是否披露依据。
- **联网模式下，判「证据不足」前必须先做聚焦再搜索**：step 1（evidence_availability）直接 INSUFFICIENT 前，先按 `web-verification.md` 第六节换词换源重试 2–3 轮；穷尽无果才保留 INSUFFICIENT，且审计须列出已尝试检索。本地模式则直接标"未联网"，不触发再搜索；保留 INSUFFICIENT 时必须按 `web-verification.md` 第六节「缺口分类 G1–G4」标注缺口类型与用户动作，并汇入审计末尾「需用户自行核验清单」。本地模式标"未联网"时同样归类 G1/G4（源文件缺失/提取失败——提取失败先按 `web-verification.md` 第七节走内置 OCR：有 shell 用 PyMuPDF+tesseract、无 shell 用多模态视觉读取，仍不可识别才归 G4）。

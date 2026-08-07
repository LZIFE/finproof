# Final System Audit（最终系统审计）

> 生成时间：2026-08-07 UTC
> 只读审计（未修改代码），基于既有 artifacts 数据（case_trace_data / E2E / index / gold alignment）

---

## 1. Retrieval 审计

| 维度 | 数值 | 结论 |
|---|---|---|
| verify 路径正确（acc） | 19/43（44.2%） | — |
| Fact Gold Recall@10（有 aligned fact 的 14 claim） | 0.7143（10/14） | 已召回者召回率高 |
| block-level Gold Recall@10 | 0.10（3/30） | gold 标注块与 fact 源块位置错位（Phase 23.29 证实） |
| **A. 正确证据不在 candidate** | **15/24 错误（62.5%）** | **主导失败** |
| B. 存在 candidate 但 ranking 失败 | 1（4.2%） | 非瓶颈 |
| C/D. 已进 top5 但最终失败 | 5（20.8%） | verification/decision 层 |

**A 类 15 条细分**：
- 财务类 9 条：季度类（CLM-010/011/013/026）、增长率类（CLM-H05 yoy_ocf）、net_profit/OCF/total_assets/扣非（CLM-H02/H04/H08/H11）——index 覆盖不足（Phase 23.28 覆盖 46.7%→73.3%，仍有 27% 缺口）
- **非财务/业务类 6 条**：CLM-019(overseas_obm_strategy)/CLM-022(robot_margin_vs_industry)/CLM-H10(publication_date)/CLM-H12(listing_info)/CLM-H17(avg_selling_price)/CLM-016——**index 只含财务表，天然不含**

## 2. Evidence Pipeline 审计

```
Claim → Retriever → EvidenceBundle → Gate → Selector → Verification → Verdict
```

| 环节 | 状态 |
|---|---|
| financial_fact 附加（attach_financial_facts） | ✅ Phase 23.23 |
| Gate 透传 financial_fact | ✅ Phase 23.34 修复（此前丢失，0/9） |
| Selector bundle 透传 | ✅ Phase 23.34 修复 |
| verify_real_e2e 候选 text 适配 | ✅ Phase 23.35 修复（此前 Gate 全拒） |
| **E2E 官方评估路径（development_e2e.py）** | ⚠️ 缺 financial_fact 透传（R4 实验发现：补上后 acc 反而降 0.4884——fact authority 触发但判定质量不足，已 revert） |

**结论**：生产链（verify_claim_production）字段已 100% 透传；E2E 官方路径与生产链存在字段差异（评估口径问题，非数据丢失）。

## 3. Verification 审计

24 错误 case 的 decision 来源：**BLOCK 12 / FACT 7 / SEMANTIC 3 / NO_EVIDENCE 2**

错误类型：

| 类型 | 代表 | 说明 |
|---|---|---|
| False SUPPORTED | CLM-002（复合 claim） | "营业总收入4564.52亿与营业收入基本持平"——fact 宽松匹配（±5%）判 SUPPORTED，gold=REFUTED |
| False REFUTED | CLM-007/014/H08 等 | fact value 冲突过度（Phase 23.36 已修复 13→7，仍存口径差异） |
| False UNKNOWN | CLM-009/011 等 | fact 未触发（quality/period 门槛），fallback block 后 no_evidence |
| period mismatch | CLM-007/009/010/011（Q1/Q2/H1） | index 主表 FY，无季度分解；Q/H claim 的 fact period 降权（Phase 23.37 R5 已试，未提升） |
| compound claim | CLM-002/024 | 比较类/多组件 claim，fact 单一组件不足以判定 |

## 4. Benchmark Compatibility 审计

| 错误来源 | 数量 | 判断 |
|---|---|---|
| 代码问题（pipeline bug） | 已修复（Phase 23.34/23.35） | ✅ |
| 系统能力不足（index 覆盖/季度数据） | ~9 条 | 季度/增长率/扣非——单点实验（季度抽取）证明扩展不提升（噪声） |
| **Gold 定义与系统目标不一致** | **6 条 business_fact/comparison**（CLM-016/019/022/H10/H12/H17）+ 3 条 gold 边界（CLM-022/025/H17 gold=INSUFF/UNABLE） | index 只覆盖财务表；strategy/listing/pricing/business 类 claim 的 gold 期望超出系统财务事实能力 |

**重点**：strategy（overseas_obm_strategy）、listing（listing_info）、pricing（avg_selling_price）、publication_date 类 claim 为**业务信息/非财务事实**，Financial Evidence Index 设计范围（income_statement/balance_sheet/cash_flow/notes/MD）天然不含——属于 **Gold 定义与系统目标不一致**。

## 5. 综合结论

- 生产链功能完备（Retrieval→Index→Fact→Verification→Decision 全链路，Fact usage 37.2%，CORE Oracle 1.0）
- 主导瓶颈（62.5% A 类）中：财务类缺口（季度/增长率，~9 条）经单点实验证明**无法通过 candidate generation 优化提升**；非财务/业务类 6 条为 **benchmark 定义错位**
- 预计可通过代码优化的明确提升 <5%（5 轮不同方向实验均无提升已 revert）

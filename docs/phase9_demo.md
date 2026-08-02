# FinProof Phase 9 · Demo — 美的集团投资委员会审核

> 公司：美的集团（000333，深交所主板）
> 报告期：2025FY
> 输入：投资材料文档 + 已有审计任务（audit_id）+ 可选情报报告（intelligence_report_id）
> 演示日期：2026-07-31

## 1. 多 Agent 流程（任务书 §7）

```
Supervisor Agent
   ↓ 拆任务（Research / Risk / Compliance）
Research Agent
   ↓ 基于已有 Evidence 生成调研结论
Risk Agent
   ↓ 调用 Verification + Risk Engine + Intelligence
Compliance Agent
   ↓ 检查投资材料合规问题
Final Report（Investment Committee Report）
```

## 2. 三个 Agent 发现（任务书 §8）

| Agent | 发现 |
| ---- | ---- |
| Research | 海外业务增长（业务增长驱动识别） |
| Risk | 缺少利润贡献证明（Intelligence 冲突结论 / Risk Engine 风险点） |
| Compliance | 存在夸大表达（OVERSTATEMENT） |

## 3. Investment Committee Report 结构（任务书 §6）

- Executive Summary（执行摘要：整体风险 / 合规评分 / 三 Agent 摘要）
- Research Findings（Company Overview / Business Analysis / Financial Summary）
- Risk Findings（Risk Findings / Conflict Findings / Risk Score）
- Compliance Findings（UNSUPPORTED_CLAIM / OVERSTATEMENT / MISSING_EVIDENCE / FORECAST_AS_FACT）
- Evidence Chain（合并三 Agent 的证据引用）
- Human Review Items（高风险/合规问题自动提请人工审核）

## 4. 运行方式

```bash
cd backend
python -m scripts.phase9_demo
```

输出包含：
- Agent 执行流程（agent_flow：Supervisor / Research / Risk / Compliance）
- Investment Committee Report JSON
- 整体风险评分与合规评分
- 人工审核项（自动提请）

## 5. 设计约束

- 不输出投资建议；
- 不自动决定买卖；
- 保持 Human-in-the-loop（高风险/合规问题自动提请人工审核）；
- 不修改已有核心模块（Verification / Risk / Intelligence / Audit / Investment Memo）。

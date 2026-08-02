# Phase 23.7 数据划分定义

- **冻结基线 commit：** `b8a9ab1`（Phase 23.6 修复后）
- **划分日期：** 2026-08-02

---

## Development Set（允许用于调试）

以下公司此前已参与开发/Demo/Benchmark/Arena/规则调试，**仅允许用于规则修复与调试**，不得作为 Blind Holdout：

| company | stock_code | 角色 | PDF 路径 | Gold 标注 |
|---|---|---|---|---|
| 美的集团 | 000333 | demo 集（主要 Demo 公司） | `data/demo/source/annual_report.pdf` `data/demo/source/half_year_report.pdf` `data/demo/source/q1_report.pdf` `data/demo/tmp/000333_*.pdf` | `data/demo/annotations/gold_claims.json` `gold_evidence.json` `gold_verifications.json` |
| 宁德时代 | 300750 | demo/tmp（Benchmark/Arena 调试） | `data/demo/tmp/300750_*.pdf` | **无 Gold 标注** |
| 五粮液 | 000858 | holdout 集（Phase 23.5/23.6 盲测已用） | `data/holdout/source/annual_report.pdf` `data/demo/tmp/000858_*.pdf` | `data/holdout/annotations/gold_claims.json` `gold_evidence.json` `gold_verifications.json` |

**Development Set 主张来源：**
- `data/demo/annotations/gold_claims.json`（美的集团 26 条）
- `data/holdout/annotations/gold_claims.json`（五粮液 17 条）
- 合计 43 条主张，claim_type 覆盖：business_fact / calculated_financial_metric / causality / forecast / raw_number / scope

**Development Set 允许用途：**
- Oracle Verification 规则修复与调试
- Evidence Retrieval 参数调优
- confusion matrix / per-class F1 诊断
- 目标达成验证（Oracle Accuracy ≥0.85 / Macro-F1 ≥0.80 / 数值类F1 ≥0.90 / 期间类F1 ≥0.80 / INSUFFICIENT_EVIDENCE F1 ≥0.80）

---

## Blind Holdout Set（必须全新公司）

### 要求

- 至少 2 家此前未参与开发/Demo/Benchmark/Arena/规则调试的公司
- 禁用：美的集团 / 宁德时代 / 五粮液
- 每家公司必须有真实公开财报 PDF 或 Markdown
- 每家公司至少 15 条原子主张，总计至少 30 条
- 每条主张完整字段：claim_id / company / claim_text / claim_type / expected_verdict / gold_document_id / gold_page / gold_block_id / gold_evidence_text / metric / period / unit / rationale
- SUPPORTED / REFUTED / PARTIAL / INSUFFICIENT_EVIDENCE 均需覆盖
- Gold 文件与运行时数据库隔离，系统运行时不得读取 Gold Verdict

### 可用性检查结果

**前置检查（2026-08-02）：** 对 `data/` 全树扫描所有 `.pdf` / `.md` / `.json` 文件，结果：

| 检查项 | 结果 |
|---|---|
| 仓库内真实财报 PDF 覆盖公司 | 仅 3 家：000333 美的 / 300750 宁德 / 000858 五粮液 |
| Gold 标注覆盖公司 | 仅 2 家：美的集团 / 五粮液（无宁德时代 Gold） |
| 全新公司（非美的/宁德/五粮液）真实财报 PDF | **0 家** |
| 全新公司 Gold 标注 | **0 家** |

### 评级

**Blind Holdout Set：BLOCKED**

**BLOCKED 原因：** 仓库中不存在任何两家全新公司的真实财报 PDF 或 Gold 标注。按任务指令"若没有两家全新公司的真实财报文件，立即标记 BLOCKED 并停止，不得用旧公司替代"，Blind Holdout 部分停止，不得宣布 Phase 23.7 完成。

### 需要用户补充的文件

为解除 BLOCKED，用户需补充以下文件（至少 2 家全新公司，示例公司名仅为占位）：

#### 公司 A（例如：贵州茅台 600519）

| 文件 | 说明 |
|---|---|
| `data/blind/company_A/source/annual_report.pdf` | 真实公开财报 PDF（≥1 份） |
| `data/blind/company_A/annotations/gold_claims.json` | ≥15 条原子主张，完整字段 |
| `data/blind/company_A/annotations/gold_evidence.json` | 引用真实 document_id/page/block 的 Gold Evidence |
| `data/blind/company_A/annotations/gold_verifications.json` | 独立 Gold Verdict，运行时不可读取 |

#### 公司 B（例如：恒瑞医药 600276）

| 文件 | 说明 |
|---|---|
| `data/blind/company_B/source/annual_report.pdf` | 真实公开财报 PDF（≥1 份） |
| `data/blind/company_B/annotations/gold_claims.json` | ≥15 条原子主张，完整字段 |
| `data/blind/company_B/annotations/gold_evidence.json` | 引用真实 document_id/page/block 的 Gold Evidence |
| `data/blind/company_B/annotations/gold_verifications.json` | 独立 Gold Verdict，运行时不可读取 |

#### Gold 标注字段要求（每条主张）

```json
{
  "claim_id": "BC-A-001",
  "company": "公司A",
  "claim_text": "2024 年海外收入同比增长 13%",
  "claim_type": "calculated_financial_metric | raw_number | business_fact | causality | forecast | scope",
  "expected_verdict": "SUPPORTED | REFUTED | PARTIAL | INSUFFICIENT_EVIDENCE",
  "gold_document_id": "doc-A-001",
  "gold_page": 42,
  "gold_block_id": "blk-A-42-3",
  "gold_evidence_text": "海外业务收入 1,234,567,890 元，同比增长 13.0%",
  "metric": "海外收入同比增长",
  "period": "2024FY",
  "unit": "百分比",
  "rationale": "原文数值与主张一致，口径匹配"
}
```

**verdict 覆盖要求：** SUPPORTED / REFUTED / PARTIAL / INSUFFICIENT_EVIDENCE 均需在 30 条主张中出现。

---

## 隔离规则

1. **运行时数据库不得读取 Gold Verdict：** `data/blind/*/annotations/gold_verifications.json` 仅用于评测计算，系统推理路径（Retrieval / Verification / Risk）不得 import 或读取。
2. **防泄漏护盾：** `backend/app/services/claims/guard.py` `assert_extraction_isolated()` 静态断言提取服务源码不引用 gold_* / holdout / annotations / blind 等 token。
3. **Gold 文件 hash 记录：** Blind Holdout 运行前需记录所有 Gold 文件的 SHA-256 hash，用于验证运行后 Gold 文件未被篡改。

---

## BLOCKED 影响范围

由于 Blind Holdout Set BLOCKED，以下 Phase 23.7 任务无法执行：

- 任务 #4 第二部分：Blind Holdout 首次评测（无法运行）
- 任务 #5 第二部分：Blind Holdout Oracle 指标（无法计算）
- 任务 #6 第二部分：Blind Holdout Retrieval 指标（无法计算）
- 任务 #7：Blind Holdout 消融实验（无法运行）
- 完成标准 #1-#3, #5-#13 均依赖 Blind Holdout，无法达成

**可继续执行的任务（仅基于 Development Set）：**
- 任务 #4 第一部分：Oracle Verification 开发集诊断脚本
- 任务 #5 第一部分：基于 Development Set 修复 Oracle Verification 规则
- 任务 #6 第一部分：基于 Development Set 修复 Evidence Retrieval
- 任务 #7：Risk 数据血缘验证
- 任务 #8：Prompt Injection 真实防护重构
- 任务 #9：5 次 pytest + 3 次前端 build
- 任务 #10：创建交付文件并更新 progress.md + 新 commit

**Phase 23.7 最终评级：** 因 Blind Holdout BLOCKED，**最高仅可达 PARTIAL**，不得标记 PASS。

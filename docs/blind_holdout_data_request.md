# Blind Holdout 数据请求清单

Phase 23.7/23.8 的 Blind Holdout Set 当前 **BLOCKED**：仓库中不存在任何两家全新公司的真实财报 PDF 或 Gold 标注。

为解除 BLOCKED 并完成真正独立验收审计，需要用户提供以下文件。

---

## 一、需要提供的公司（至少 2 家）

**要求：** 两家此前未参与开发 / Demo / Benchmark / Arena / 规则调试的全新公司。

**禁用公司（已用于开发，不可作为 Blind Holdout）：**
- 美的集团（000333）—— Development Set
- 宁德时代（300750）—— Benchmark/Arena 调试
- 五粮液（000858）—— Phase 23.5/23.6 盲测已用

**示例候选公司（仅占位，用户可自选）：**
- 贵州茅台（600519）
- 恒瑞医药（600276）
- 比亚迪（002594）
- 招商银行（600036）

---

## 二、每家公司需要提供的文件

### 1. 真实公开财报 PDF（≥1 份）

放置路径：
```
data/blind_holdout/{stock_code}/source/annual_report.pdf
data/blind_holdout/{stock_code}/source/half_year_report.pdf（可选）
```

要求：
- 真实公开财报 PDF（A股上市公司年报 / 半年报 / 季报）
- 可从公司官网、交易所网站、巨潮资讯网下载
- PDF 需可解析（非扫描件为佳）

### 2. 待审计 AI 报告或 30 条候选主张

放置路径：
```
data/blind_holdout/{stock_code}/audit_report.md
```

或直接提供 30 条候选主张文本。

要求：
- 一份待审计的 AI 生成的投研报告，或 30 条关于该公司的原子主张
- 主张需覆盖不同 claim_type：raw_number / calculated_financial_metric / business_fact / causality / forecast / scope
- 主张需覆盖不同 verdict：SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE

### 3. 人工确认 Gold Evidence

使用接入工具生成模板后，人工填充：
```
data/blind_holdout/{stock_code}/annotations/evidence_to_review.json
```

每条主张的 `human_gold_evidence` 字段需填写：
- 引用真实 PDF 中的 document_id / page / block_id
- evidence_text 需与 block 内容一致
- 不得使用 claim_text 作为 Evidence

### 4. 人工确认 Gold Verdict

使用接入工具生成模板后，人工填充：
```
data/blind_holdout/{stock_code}/annotations/verdicts_to_review.json
```

每条主张的 `human_gold_verdict` 字段需填写：
- SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE
- `human_rationale` 需填写判定理由
- **Agent 不得自动把自身预测写入 human_gold_verdict**

---

## 三、数据接入工具使用

```bash
cd backend
python scripts/prepare_holdout_company.py \
    --company-name "贵州茅台" \
    --stock-code 600519 \
    --pdf-path /path/to/600519_annual_2024.pdf \
    --report-path /path/to/audit_report_moutai.md
```

工具自动完成：
1. 复制 PDF 到 `data/blind_holdout/600519/source/`
2. 计算 SHA256
3. 创建 manifest
4. 解析 PDF → document/page/block
5. 建立真实 Evidence 索引
6. 真实执行 Claim Extraction（禁止读 gold_claims）
7. 导出待人工标注模板

生成文件：
- `manifest.json`（含 SHA256 与元数据）
- `annotations/claims_to_review.json`（候选主张模板）
- `annotations/evidence_to_review.json`（待人工填充 Gold Evidence）
- `annotations/verdicts_to_review.json`（待人工填充 Gold Verdict）

---

## 四、Gold 标注字段要求（每条主张）

```json
{
  "claim_id": "BC-600519-001",
  "company": "贵州茅台",
  "claim_text": "2024 年公司实现营业收入 1,569.47 亿元，同比增长 15.7%",
  "claim_type": "calculated_financial_metric",
  "expected_verdict": "SUPPORTED",
  "gold_document_id": "doc-600519-001",
  "gold_page": 42,
  "gold_block_id": "blk-600519-42-3",
  "gold_evidence_text": "营业收入（元） 156,946,552,300 135,765,432,100 15.7%",
  "metric": "revenue",
  "period": "2024FY",
  "unit": "亿元",
  "rationale": "原文数值与主张一致，口径匹配，同比基期正确"
}
```

**verdict 覆盖要求：** SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE 均需在 30 条主张中出现。

---

## 五、Gold 校验

数据提供后，运行校验器确认完整性：
```bash
python scripts/validate_blind_gold.py
```

校验项：
- 至少 2 家公司
- 禁止美的 / 宁德 / 五粮液
- 每家公司至少 15 条主张，总计至少 30 条
- 四类 Verdict 均有覆盖
- document/page/block 真实存在
- evidence_text 与 block 内容一致
- Gold Verdict 非空，rationale 非空
- 文件 hash 固定
- 不存在重复 claim
- 系统运行代码无法导入 Gold Verdict

未通过时 Blind Holdout 保持 BLOCKED。

---

## 六、解除 BLOCKED 后的验收流程

1. 运行 `validate_blind_gold.py` 通过
2. 冻结代码 commit，记录 Gold 文件 hash
3. 只允许运行一次正式首次 Blind Holdout 评测
4. 原始结果设为只读，不得覆盖
5. 输出 Blind Oracle / Real E2E / 消融 / 安全测试指标

目标：
- Blind Oracle Macro-F1 ≥ 0.75
- Blind Page Hit@5 ≥ 0.70
- Blind No-result Rate ≤ 0.20
- Blind Real E2E Macro-F1 ≥ 0.60

---

当前状态：**BLOCKED** — 待用户补充两家全新公司文件。

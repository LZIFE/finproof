# Phase 23.18 Evidence Representation 审计

> 生成时间：2026-08-06 UTC
> 审计对象：Claim 表示 vs Evidence Block 表示，定位缺失的财务字段（为何正确财务行排名极低）

---

## 1. Claim 表示（现状）

以 CLM-001 为例：

```json
{
  "claim_id": "CLM-001",
  "original_text": "公司2025年实现营业收入4564.52亿元，同比增长12.11%",
  "claim_type": "raw_number",
  "entity": "美的集团",
  "metric": "revenue",
  "value": 4564.52,
  "unit": "亿元",
  "currency": "CNY",
  "period": "2025FY",
  "scope": "consolidated"
}
```

normalize 后（`engine.normalize_claim`）：

```json
{
  "entity_name": "美的集团",
  "metric_code": "revenue",
  "metric": "营业收入",
  "reported_value": 4564.52,
  "unit": "亿元",
  "period": "2025FY"
}
```

**已结构化字段**：entity / metric_code / metric（中文）/ reported_value / unit / period。

**缺失财务字段**：
- `table_type`（期望证据所在表：income_statement/balance_sheet/cash_flow）——靠 route_sections_for_claim 推断，未显式存于 claim
- `row_label`（期望指标行标签，如"营业收入"）——仅 metric 别名，未拆出行/列
- `column_label`（期望期间列，如"2025年度"）——仅 period 字符串
- `need`（value/previous_value/growth）——Phase 23.14 已加入 QueryPlan，但未回写 claim 检索路径

## 2. Evidence Block 表示（现状）

以正确证据 block 189 为例：

```text
text: "营业收入（千元） \n456,451,731 \n407,149,600 \n12.11% \n372,037,280 \n"
字段: document_id=1 page_id=9 block_index=23 block_type=text
坐标: x0=62.3 y0=622.0 x1=536.3 y1=632.2 heading_level=None
```

**Block 只存原始文本 + 坐标**。财务事实完全隐含在文本行中，无任何结构化元数据：
- 指标名"营业收入"与数值"456,451,731"在**同一块内多行**，但无解析后的 metric/value/unit/period 字段
- 无 table_type（这块在 page 9 主要财务指标区域，非利润表主表——但 block 自身不知道）
- 无 row_label / column_label

**后果**：
- 文本 embedding（字符 n-gram）对"营业收入（千元）456,451,731 407,149,600 12.11%"与 claim"公司2025年实现营业收入4564.52亿元，同比增长12.11%"的相似度极低（0.116）——数字文本结构性表达 vs 自然语言表述，无 n-gram 重合
- entity=0：财务表行不含公司名
- 正确财务行被 reranker 压到第 116 位（Phase 23.17 实测）

## 3. 缺失财务字段清单（Task 2 需提取）

| 字段 | Claim 有？ | Block 有？ | 缺失影响 |
|---|---|---|---|
| metric（指标名） | ✅ metric/中文 | ❌ 隐含在文本 | metric_match 依赖别名 LIKE |
| value（数值） | ✅ reported_value | ❌ 隐含在文本行 | value 匹配需解析块内数字 |
| unit（单位） | ✅ unit=亿元 | ❌ 隐含（块内"千元"） | 单位换算需从块文本提取 |
| period（期间） | ✅ 2025FY | ❌ 隐含（"2025年度"列或页首） | period_match 靠关键词 |
| **table_type** | ❌（route 推断） | ❌ | table_match 无法直接比对 |
| **row_label** | ❌ | ❌ | 行级指标对齐缺失 |
| **column_label** | ❌ | ❌ | 期间列对齐缺失 |

## 4. 结论

**核心问题**：Claim 与 Evidence Block 用**两种异构表示**（结构化字段 vs 原始文本），文本 embedding/reranking 无法弥合"自然语言 claim"与"财务表格行"的语义鸿沟。

**修复方向（Task 2-3）**：
1. 从 block 文本提取财务事实元数据（metric/value/unit/period/table_type/row_label/column_label），**不删除原文**。
2. 用财务事实匹配（fact-level match）替代文本相似度主导的排序——financial_fact_match 0.45 主导。

# FinProof Phase 11 · Demo — 金融 AI 可信度评测基准

> Dataset：finproof_seed_v1（50 条预置金融测试案例 + 1 条正确对照）
> 模型：FinProof vs Baseline LLM
> 演示日期：2026-07-31

## 1. 流程（任务书 §1）

```
Dataset（50 条金融测试案例，覆盖 6 类错误）
   ↓ Evaluator
FinProof（证据覆盖 + 风险口径 + 语义/增长/竞争/期间/因果多维检测）
vs
Baseline LLM（弱核验，仅明显绝对化+超数字检测）
   ↓ Metrics
Accuracy / Precision / Recall / F1 / Evidence Coverage / Risk Detection Rate
   ↓ Compare
FinProof 增益（凸显发现 AI 金融幻觉能力）
```

## 2. 6 类错误覆盖（任务书 §2）

| 错误类型 | 条数 | 示例 |
| ---- | ---- | ---- |
| FINANCIAL_ERROR（财务数据错误）| 8 | "美的集团2025年营业收入5000亿元" |
| PERIOD_ERROR（期间错误）| 8 | "美的集团2024年营业收入4564.52亿元"（应为 2025）|
| GROWTH_ERROR（增长逻辑错误）| 9 | "海外业务高速增长，增速超50%" |
| SEMANTIC_OVERSTATEMENT（语义夸大）| 8 | "唯一遥遥领先的家电龙头" |
| COMPETITIVE_CLAIM（竞争优势主张缺证据）| 8 | "保持行业领先地位" |
| CAUSAL_ERROR（因果归因错误）| 9 | "利润增长完全由海外业务驱动" |
| 正确对照 | 1 | "美的集团2025年营收4564.52亿元同比增长12.11%" |

## 3. 指标（任务书 §3）

- Accuracy            准确率
- Precision           精确率
- Recall              召回率
- F1                  F1 分数
- Evidence Coverage   证据覆盖率
- Risk Detection Rate 风险检测率

## 4. 运行方式

```bash
cd backend
python -m scripts.phase11_demo
```

输出包含：
- Dataset 概况（数量 + 错误分布）
- FinProof vs Baseline LLM 指标对比
- 模型对比摘要（增益）
- 逐案例结果摘录（FinProof 检测 AI 幻觉）

## 5. 设计约束

- 不修改已有核心模块（Verification / Risk / Knowledge Graph / Audit / Committee）；
- Benchmark 作为新增层，复用已有风险口径但独立实现评测逻辑；
- Evidence First：FinProof 判定基于金标准证据覆盖。

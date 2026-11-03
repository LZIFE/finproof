# 对抗变异 + 历史真实错误

## 生成

`seeds.jsonl` 是 5 条已通过的正例。`mutate.py` 对每条自动生成 6 个变体：

| 变体 | 期望 | 原因码 |
|---|---|---|
| 数值 ×100 | FAIL | VALUE_MISMATCH |
| 单位降一档（亿元→万元；%→百分点） | FAIL | VALUE_MISMATCH / RATIO_UNIT_MISMATCH |
| 期间上移一年 | ABSTAIN | PERIOD_MISMATCH |
| 指标偷换 | ABSTAIN | METRIC_MISMATCH |
| 撤掉来源核验 | ABSTAIN | SOURCE_UNVERIFIED |
| 数值取反 | FAIL | VALUE_MISMATCH |

`historical.jsonl` 固化 10 条真实事故/高风险组合：富技术式同比方向、亏损收窄正确算法、未知单位、百万元复合单位、期间错配、归母 vs 营收、% vs 百分点、吨 vs 千瓦时、人民币 vs 美元、缺期间。

## 运行

```bash
python3 mutate.py
python3 run_adversarial.py
```

当前 45/45。**注意**：生成器只做机械变异，不替代人工构造的语义陷阱；它保证"已通过的正例被改动后能被重新抓住"，防止规则只对原始样例有效。

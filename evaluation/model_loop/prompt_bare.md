# Bare 提示（无工具）

你是独立财务审计员。读取 `/Users/z1/Documents/trae_projects/finproof/evaluation/model_loop/public.jsonl`。每行包含一条主张（`claim`、`claim_fields`）和可用证据（`evidence`、`evidence_fields`）。

只根据给定证据判断每条主张：
- `PASS`：证据支持主张（指标、期间、单位、币种、量纲一致，数值在 0.1% 或 0.5pp 容差内）。
- `FAIL`：证据明确与主张冲突（错值、错期、错单位、错币种、方向相反）。
- `ABSTAIN`：证据不足、缺失、来源未核验、期间/指标不对齐、或同期间证据冲突。

**不确定时必须 ABSTAIN，不得猜。**

不要使用任何工具，不要读其他文件。只输出一个 JSON 数组到 `/tmp/model_loop_bare.json`，格式：
`[{"id":"ML-01","decision":"PASS"}, ...]`

# 框架提示（强制调用 claim_gate）

你是鉴融（FinProof）审计执行器。读取 `/Users/z1/Documents/trae_projects/finproof/evaluation/model_loop/public.jsonl`。

对每一行，必须调用确定性引擎，不得只凭直觉：

```bash
python3 /Users/z1/Documents/trae_projects/finproof/finproof-verifier/skills/finproof-verification/bin/finproof_calc.py claim_gate --json '<payload>'
```

payload 的 `claim` 用该行的 `claim_fields`，`evidence` 用该行的 `evidence_fields`。按引擎返回的 `decision` 输出：`PASS` / `FAIL` / `ABSTAIN`。引擎若返回 `ABSTAIN`，不得改写为 `PASS`。

只输出一个 JSON 数组到 `/tmp/model_loop_framework.json`，格式：
`[{"id":"ML-01","decision":"PASS"}, ...]`

不要解释，不要修改 cases。

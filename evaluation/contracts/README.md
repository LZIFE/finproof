# 跨端契约（技能引擎 × backend）

同一份 `contract_cases.json` 被两侧读取：

| 侧 | 入口 | 运行方式 |
|---|---|---|
| 技能引擎 | `finproof-verifier/skills/finproof-verification/bin/test_contract_cases.py` | `python3 test_contract_cases.py` |
| backend | `backend/tests/test_financial_contract.py` | `PYTHONPATH=backend python3 -m pytest ... --noconftest` |
| backend 最小门禁 | `run_backend_contract.py` | `python3 run_backend_contract.py`（无 pytest 也能跑） |

覆盖：亏损收窄/扩大、扭亏、由盈转亏、零基数；百万元/万亿元/亿美元/%/百分点；万吨/亿千瓦时/万平方米/吨/年；未知单位拒绝。

任何一侧改了口径，契约先红。2026-10-28 就是靠这套契约抓到 backend `_extract_current_prev` 仍不吃负号——分母已改 `abs()`，但 `-64.2` 被读成 `64.2`，亏损收窄依旧算反。

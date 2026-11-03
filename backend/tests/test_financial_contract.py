"""技能引擎与 backend 的共用契约测试（负基数 / 单位 / 物理单位）。

运行（本机无 pytest 时可用仓库内测试环境）：
    cd backend
    PYTHONPATH=. python3 -m pytest tests/test_financial_contract.py --noconftest -q

契约数据在 evaluation/contracts/contract_cases.json，技能引擎侧由
bin/test_contract_cases.py 读同一份文件；任何一侧改了口径，这里会先红。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.verification.financial_value import (
    extract_financial_values,
    parse_unit,
    unit_kind,
)
from app.services.verification.growth_verifier import verify_growth_rate

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "evaluation/contracts/contract_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["yoy"], ids=lambda c: c["id"])
def test_yoy_contract(case):
    claim = {
        "claim_id": case["id"],
        "claim_type": "GROWTH_RATE",
        "reported_value": case["expected_pct"] if case["expected_pct"] is not None else 0,
        "unit": "%",
    }
    evidence = f"净利润 {case['current']} 上年同期 {case['previous']}"
    result = verify_growth_rate(claim, [evidence])
    if case["expected_pct"] is None:
        assert result.verification_status == "INSUFFICIENT_EVIDENCE"
        return
    assert result.verification_status in ("SUPPORTED", "REFUTED")
    assert result.calculation_detail["calculated_growth_pp"] == pytest.approx(
        case["expected_pct"], abs=0.011
    )
    assert result.calculation_detail["negative_base"] is (case["previous"] < 0)


@pytest.mark.parametrize("case", CASES["units"], ids=lambda c: c["unit"])
def test_unit_contract(case):
    scale, currency = parse_unit(case["unit"])
    assert scale == pytest.approx(case["scale"])
    assert currency == case["currency"]
    assert unit_kind(case["unit"]) == case["kind"]


@pytest.mark.parametrize("case", CASES["invalid_units"], ids=lambda c: c["unit"])
def test_invalid_units_raise(case):
    with pytest.raises(ValueError):
        parse_unit(case["unit"])


@pytest.mark.parametrize("case", CASES["physical_extract"], ids=lambda c: c["text"])
def test_physical_extract(case):
    values = extract_financial_values(case["text"])
    hits = [v for v in values if v.unit == case["unit"]]
    assert len(hits) == 1, f'{case["text"]} -> {[v.unit for v in values]}'
    got = hits[0]
    assert got.normalized_value == pytest.approx(case["value"])
    assert got.scale == pytest.approx(case["scale"])
    assert got.absolute_value_in_yuan == pytest.approx(case["base"])
    assert got.to_dict()["unit_kind"] == "physical"

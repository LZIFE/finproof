"""主张 Schema 单元测试：合法数据 / 缺失必填 / 非法枚举。"""

import pytest
from pydantic import ValidationError

from app.core.enums import ClaimType, RiskLevel
from app.schemas.claim import ClaimCreate


def _valid_claim(**overrides) -> dict:
    base = {
        "claim_uid": "CLM-RUN1-001",
        "extraction_run_id": 1,
        "document_id": 4,
        "source_block_id": 3,
        "source_page_number": 1,
        "source_text": "公司2025年实现营业收入4564.52亿元",
        "normalized_claim": "美的集团2025年营业收入4564.52亿元",
        "claim_type": "ABSOLUTE_FINANCIAL_VALUE",
        "entity_name": "美的集团",
        "stock_code": "000333",
        "metric": "营业收入",
        "metric_code": "revenue",
        "reported_value": 4564.52,
        "unit": "亿元",
        "period": "2025FY",
        "period_type": "YEAR",
        "risk_level": "HIGH",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def test_claim_schema_valid():
    c = ClaimCreate(**_valid_claim())
    assert c.claim_type == ClaimType.ABSOLUTE_FINANCIAL_VALUE
    assert c.risk_level == RiskLevel.HIGH
    assert c.value_operator == "EQUAL"  # 默认值


def test_claim_schema_missing_required():
    data = _valid_claim()
    del data["source_text"]
    with pytest.raises(ValidationError):
        ClaimCreate(**data)
    data2 = _valid_claim()
    del data2["normalized_claim"]
    with pytest.raises(ValidationError):
        ClaimCreate(**data2)


def test_claim_schema_invalid_enum():
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(claim_type="NOT_A_TYPE"))
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(risk_level="VERY_HIGH"))
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(value_operator="SOMETIMES"))


def test_claim_schema_empty_text_rejected():
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(source_text=""))
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(normalized_claim=""))


def test_claim_schema_confidence_bounds():
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(confidence=1.5))
    with pytest.raises(ValidationError):
        ClaimCreate(**_valid_claim(confidence=-0.1))
    assert ClaimCreate(**_valid_claim(confidence=0.0)).confidence == 0.0

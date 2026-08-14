"""backend/tests/test_generic_verification/test_extraction_provider.py"""
import json

import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.claim_extraction import (
    GenericClaimExtractionResult,
    GenericClaimExtractor,
    load_generic_prompt,
)


def test_load_generic_prompt_missing_version():
    with pytest.raises(AppError):
        load_generic_prompt("does_not_exist")


def test_mock_when_no_llm_config(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: _FakeSettings())
    extractor = GenericClaimExtractor()
    blocks = [
        {"index": 0, "text": "营收 1.2 亿元", "block_type": "paragraph"},
        {"index": 1, "text": "普通段落", "block_type": "paragraph"},
    ]
    result = extractor.extract(blocks, "generic_claim_extraction_v1")
    assert isinstance(result, GenericClaimExtractionResult)
    assert result.is_mock is True
    assert len(result.claims) >= 1
    assert result.claims[0].claim_kind == "NUMERIC"


def test_llm_parse_response():
    extractor = GenericClaimExtractor()
    content = json.dumps([
        {"source_text": "营收 1.2 亿元", "claim_kind": "NUMERIC", "page_number": 1,
         "block_index": 0, "entities": ["公司A"], "numbers": [{"value": 1.2, "unit": "亿", "context": "营收"}],
         "dates": [], "cross_refs": [], "confidence": 0.9},
    ], ensure_ascii=False)
    items = extractor._parse_response(content)
    assert items[0]["claim_kind"] == "NUMERIC"


class _FakeSettings:
    claim_extraction_base_url = ""
    claim_extraction_api_key = ""
    claim_extraction_model = ""
    claim_extraction_timeout_seconds = 10
    claim_extraction_max_retries = 0

"""backend/tests/test_generic_verification/test_config.py"""
from app.core.config import get_settings


def test_generic_verification_config_defaults():
    s = get_settings()
    assert s.generic_web_search is False
    assert s.ocr_engine == "off"
    assert s.generic_extraction_prompt_version == "generic_claim_extraction_v1"


def test_generic_verification_config_env_override(monkeypatch):
    monkeypatch.setenv("FINPROOF_GENERIC_WEB_SEARCH", "true")
    monkeypatch.setenv("FINPROOF_OCR_ENGINE", "tesseract")
    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.generic_web_search is True
    assert s.ocr_engine == "tesseract"

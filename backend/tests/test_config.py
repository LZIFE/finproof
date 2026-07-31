"""配置管理测试：默认值必须保证无 .env 可运行。"""

from app.core.config import Settings, get_settings


def test_settings_defaults():
    settings = Settings()  # 不传任何参数，验证默认值
    assert settings.llm_mode in {"mock", "real", "off"}
    assert settings.llm_mode == "mock"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.upload_dir
    assert settings.demo_dir


def test_get_settings_cached():
    assert get_settings() is get_settings()


def test_env_prefix_mapping(monkeypatch):
    monkeypatch.setenv("FINPROOF_LLM_MODE", "off")
    monkeypatch.setenv("FINPROOF_LLM_API_KEY", "test-key")
    settings = Settings()
    assert settings.llm_mode == "off"
    assert settings.llm_api_key == "test-key"

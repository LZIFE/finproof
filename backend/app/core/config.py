"""应用配置（pydantic-settings）。

所有配置项均有默认值，不配置 .env / 环境变量也能运行：
- 数据库默认 SQLite（data/finproof.db）
- 大模型默认 Mock 模式（FINPROOF_LLM_MODE=mock，输出带明确标识）

环境变量前缀：FINPROOF_（如 FINPROOF_DATABASE_URL / FINPROOF_LLM_MODE）。
若存在 .env 文件（相对工作目录），pydantic-settings 会自动读取。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[0]=core [1]=app [2]=backend [3]=仓库根目录
BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINPROOF_", env_file=".env", extra="ignore")

    # --- 存储 ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'finproof.db').as_posix()}"
    upload_dir: str = str(BASE_DIR / "data" / "uploads")
    demo_dir: str = str(BASE_DIR / "data" / "demo")

    # --- 大模型（混合核验架构，见 docs/finproof_audit.md 6.5） ---
    # mock: 无 API Key 时使用，结果带 "Mock" 标识，不伪装为真实模型输出
    # real: 调用真实大模型（需 API Key）
    # off : 关闭语义类任务
    llm_mode: str = "mock"
    llm_api_key: str = ""
    llm_model: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

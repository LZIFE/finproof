"""pytest 全局配置：所有测试使用独立的临时数据库、存储目录与配置。"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="finproof_test_"))

os.environ["FINPROOF_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["FINPROOF_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["FINPROOF_DEMO_DIR"] = str(_TMP / "demo")
os.environ["FINPROOF_STORAGE_DIR"] = str(_TMP / "storage")
os.environ["FINPROOF_LLM_MODE"] = "mock"


@pytest.fixture(autouse=True)
def _settings_cache_isolated():
    """每个测试重新读取配置（保证 env 覆盖生效且互不影响）。"""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_db(_settings_cache_isolated):
    """每个测试前清空业务表与存储目录，保证用例相互独立。

    注意：SQLite 清空行后主键可能被复用，因此必须同时清空
    storage/documents/<id>/ 目录，避免 save_original 命中旧文件。
    """
    import shutil

    from app.db import Base, engine, init_db
    from app.services.storage import storage_root

    init_db()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    root = storage_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    yield

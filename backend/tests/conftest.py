"""pytest 全局配置：所有测试使用独立的临时数据库与目录，避免污染真实数据。"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="finproof_test_"))

os.environ["FINPROOF_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["FINPROOF_UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["FINPROOF_DEMO_DIR"] = str(_TMP / "demo")
os.environ["FINPROOF_LLM_MODE"] = "mock"

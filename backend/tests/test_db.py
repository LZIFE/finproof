"""SQLite 基础连接测试。"""

from sqlalchemy import text

from app.db import SessionLocal, check_db_connection, engine, init_db


def test_engine_connects():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_check_db_connection():
    info = check_db_connection()
    assert info["database"] == "sqlite"
    assert info["version"].startswith("3.")


def test_init_db_idempotent():
    # 无模型时 create_all 为幂等空操作；重复调用不抛异常
    init_db()
    init_db()


def test_session_local_roundtrip():
    with SessionLocal() as session:
        result = session.execute(text("SELECT sqlite_version()")).scalar()
    assert isinstance(result, str) and result.startswith("3.")

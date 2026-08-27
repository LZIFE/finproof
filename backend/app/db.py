"""SQLAlchemy 引擎 / 会话 / Base 与 SQLite 连接检查。"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _make_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        # SQLite 默认不允许多线程；FastAPI 线程池需要
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# 导入全部 ORM 模型，确保 Base.metadata.create_all 能建出所有表
from app import models  # noqa: E402, F401


def _migrate_columns(conn) -> None:
    """开发库轻量迁移：PRAGMA 检查缺失列并 ALTER TABLE 补充（幂等）。

    Phase 3 新增 extraction_runs.candidate_claim_count（用于评测 Schema 合法率）。
    Phase 3.5 新增 claims 父句归属列（parent_block_id / parent_sentence_text /
    clause_index / source_span_start / source_span_end）。
    """
    from sqlalchemy import text

    run_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(extraction_runs)"))}
    if "candidate_claim_count" not in run_cols:
        conn.execute(
            text(
                "ALTER TABLE extraction_runs "
                "ADD COLUMN candidate_claim_count INTEGER NOT NULL DEFAULT 0"
            )
        )
    if "dedup_analysis_json" not in run_cols:
        conn.execute(text("ALTER TABLE extraction_runs ADD COLUMN dedup_analysis_json TEXT"))

    claim_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(claims)"))}
    for name, ddl in [
        ("parent_block_id", "INTEGER"),
        ("parent_sentence_text", "TEXT"),
        ("clause_index", "INTEGER"),
        ("source_span_start", "INTEGER"),
        ("source_span_end", "INTEGER"),
        ("claim_group_id", "TEXT"),
    ]:
        if name not in claim_cols:
            conn.execute(text(f"ALTER TABLE claims ADD COLUMN {name} {ddl}"))

    # Phase 4A.6：证据候选新增证据类型/质量分/排名原因（保留原始检索分）
    ev_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(evidence_candidates)"))}
    for name, ddl in [
        ("evidence_type", "TEXT DEFAULT 'UNKNOWN'"),
        ("evidence_quality_score", "FLOAT DEFAULT 0.3"),
        ("evidence_rank_reason", "TEXT"),
        ("source_level", "TEXT DEFAULT 'NO_SOURCE'"),
        ("source_level_reason", "TEXT"),
    ]:
        if name not in ev_cols:
            conn.execute(text(f"ALTER TABLE evidence_candidates ADD COLUMN {name} {ddl}"))

def init_db() -> None:
    """按当前注册的 ORM 模型建表（幂等，可重复调用），并执行轻量迁移。"""
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            _migrate_columns(conn)
        except Exception:  # noqa: BLE001 —— 表不存在等场景跳过
            pass


def get_session():
    """FastAPI 依赖：每个请求一个会话。"""
    with SessionLocal() as session:
        yield session


def check_db_connection() -> dict:
    """执行一次真实查询，返回数据库类型与版本；失败时抛出异常。"""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT sqlite_version()")).scalar()
    return {"database": "sqlite", "version": str(version)}

"""健康检查接口。

- GET /health      -> {"status": "ok", "service": "finproof-api", ...}（必需）
- GET /api/health  -> 同一处理器的别名（前端代理统一走 /api 前缀）
"""

from fastapi import APIRouter

from app.db import check_db_connection

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
def health() -> dict:
    payload = {"status": "ok", "service": "finproof-api"}
    try:
        payload["database"] = check_db_connection()["version"]
    except Exception as exc:  # 健康检查不因数据库异常而整体失败
        payload["database"] = f"error: {exc}"
    return payload

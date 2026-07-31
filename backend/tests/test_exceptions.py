"""基础异常处理测试：AppError 应转换为统一错误结构 {"error": {...}}。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError, register_exception_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise AppError(message="演示数据校验失败", status_code=422, code="VALIDATION_FAILED")

    return app


def test_app_error_handler():
    with TestClient(_build_app()) as client:
        resp = client.get("/boom")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_FAILED",
            "message": "演示数据校验失败",
            "details": {},
        }
    }

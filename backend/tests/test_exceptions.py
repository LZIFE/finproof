"""基础异常处理测试：AppError 应转换为带状态码与 detail 的 JSON 响应。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError, register_exception_handlers


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise AppError(detail="演示数据校验失败", status_code=422)

    return app


def test_app_error_handler():
    with TestClient(_build_app()) as client:
        resp = client.get("/boom")
    assert resp.status_code == 422
    assert resp.json() == {"detail": "演示数据校验失败"}

"""基础异常与统一错误处理。

所有 API 错误统一返回结构（Phase 2 约定）：

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """可预期的业务错误，携带统一错误码、HTTP 状态码与用户可读信息。"""

    def __init__(self, message: str, status_code: int = 400, code: str = "APP_ERROR", details: dict | None = None) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

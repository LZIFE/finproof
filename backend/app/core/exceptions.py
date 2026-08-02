"""基础异常与统一错误处理。

所有 API 错误统一返回结构（Phase 2 约定）：

    {"error": {"code": "...", "message": "...", "details": {...}}}

Phase 23.6 安全加固：
- ``RequestValidationError`` 处理器剥离 ``input`` 字段，防止 422 响应
  原样回显恶意 payload（反射型 XSS 防护）；
- 校验错误统一返回固定 msg，不回显原始用户输入。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
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

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Phase 23.6：剥离 input 字段，防止反射型 XSS（恶意 <script> 被原样回显）
        safe_errors = []
        for err in exc.errors():
            safe_err = {
                "type": err.get("type", "value_error"),
                "loc": err.get("loc", []),
                "msg": err.get("msg", "输入校验失败"),
            }
            # 不复制 input / ctx（可能含原始恶意 payload）
            safe_errors.append(safe_err)
        return JSONResponse(
            status_code=422,
            content={"detail": safe_errors},
        )

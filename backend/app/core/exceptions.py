"""基础异常与统一异常处理。

- AppError：业务层可抛出的可预期错误（带 HTTP 状态码与可读 detail）。
- register_exception_handlers：注册到 FastAPI 应用。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """可预期的业务错误，携带 HTTP 状态码与用户可读信息。"""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

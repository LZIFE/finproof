"""FinProof API 入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db import init_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="FinProof API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(documents_router)
    return app


app = create_app()

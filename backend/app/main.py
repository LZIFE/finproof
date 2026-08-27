"""FinProof API 入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.investment import router as investment_router
from app.api.intelligence import router as intelligence_router
from app.api.investment_committee import router as committee_router
from app.api.knowledge_graph import router as knowledge_graph_router
from app.api.benchmark import router as benchmark_router
from app.api.portfolio import router as portfolio_router
from app.api.monitoring import router as monitoring_router
from app.api.governance import router as governance_router
from app.api.investigation import router as investigation_router
from app.api.red_team import router as red_team_router
from app.api.copilot import router as copilot_router
from app.api.reasoning import router as reasoning_router
from app.api.research import router as research_router
from app.api.simulation import router as simulation_router
from app.api.arena import router as arena_router
from app.api.governance_center import router as governance_center_router
from app.api.source_chain import router as source_chain_router
from app.api.llm_settings import router as llm_settings_router
from app.api.replay import router as replay_router
from app.api.demo import router as demo_router
from app.api.reliability import router as reliability_router
from app.api.audit import router as audit_router
from app.api.claims import router as claims_router
from app.api.documents import router as documents_router
from app.api.evidence import router as evidence_router
from app.api.generic_verify import router as generic_verify_router
from app.api.health import router as health_router
from app.api.risk import router as risk_router
from app.api.verification import router as verification_router
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
    app.include_router(claims_router)
    app.include_router(evidence_router)
    app.include_router(generic_verify_router)
    app.include_router(verification_router)
    app.include_router(audit_router)
    app.include_router(risk_router)
    app.include_router(investment_router)
    app.include_router(intelligence_router)
    app.include_router(committee_router)
    app.include_router(knowledge_graph_router)
    app.include_router(benchmark_router)
    app.include_router(portfolio_router)
    app.include_router(monitoring_router)
    app.include_router(governance_router)
    app.include_router(investigation_router)
    app.include_router(red_team_router)
    app.include_router(copilot_router)
    app.include_router(reasoning_router)
    app.include_router(research_router)
    app.include_router(simulation_router)
    app.include_router(arena_router)
    app.include_router(governance_center_router)
    app.include_router(source_chain_router)
    app.include_router(llm_settings_router)
    app.include_router(replay_router)
    app.include_router(demo_router)
    app.include_router(reliability_router)
    return app


app = create_app()

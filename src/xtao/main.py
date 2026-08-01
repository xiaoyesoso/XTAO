"""XTAO FastAPI application entry point.

Agent Plan mechanism service based on G4C methodology.
Plan is not a step list, but a checkable, correctable, executable runtime object.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from xtao.api import router
from xtao.services import (
    LLMService,
    RAGService,
    ConstraintManager,
    TrustStateManager,
    CandidatePathManager,
    TAOStateManager,
)
from xtao.evaluation import PlanMetrics, UserCorrectionDetector, ReplanEvaluator, TAOEvaluator
from xtao.engine import (
    ReplanEngine,
    TCCReplan,
    FailureTracer,
    DAGValidator,
    BacktrackingEngine,
    CrossTurnTracker,
    PlanOrchestrator,
    TAOEngine,
)

load_dotenv()


@dataclass
class AppState:
    """Application global state, holds singleton services."""

    llm_service: LLMService
    rag_service: RAGService
    constraint_manager: ConstraintManager
    plan_metrics: PlanMetrics
    correction_detector: UserCorrectionDetector
    tcc_replan: TCCReplan
    replan_engine: ReplanEngine
    replan_evaluator: ReplanEvaluator
    trust_state_manager: TrustStateManager
    candidate_path_manager: CandidatePathManager
    backtracking_engine: BacktrackingEngine
    cross_turn_tracker: CrossTurnTracker
    failure_tracer: FailureTracer
    tao_engine: TAOEngine
    tao_evaluator: TAOEvaluator
    orchestrator: PlanOrchestrator


def _create_state() -> AppState:
    """Create application state from environment variables."""
    llm = LLMService(
        api_base=os.getenv("BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("API_KEY", ""),
        model=os.getenv("FLASH_LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        timeout=120.0,
    )
    rag = RAGService(
        enabled=os.getenv("RAG_ENABLED", "false").lower() == "true",
        api_base=os.getenv("RAG_API_BASE", ""),
    )
    cm = ConstraintManager()
    metrics = PlanMetrics(
        enabled=os.getenv("PROMETHEUS_ENABLED", "false").lower() == "true"
    )
    detector = UserCorrectionDetector(llm_service=llm)
    tcc = TCCReplan(
        llm_service=llm,
        plan_generator=None,
        enabled=os.getenv("TCC_ENABLED", "false").lower() == "true",
    )
    replan_engine = ReplanEngine(
        llm_service=llm,
        constraint_manager=cm,
        plan_generator=None,
        max_replan_total=int(os.getenv("MAX_REPLAN_TOTAL", "3")),
    )
    replan_evaluator = ReplanEvaluator()
    trust_state_manager = TrustStateManager()
    candidate_path_manager = CandidatePathManager()
    backtracking_engine = BacktrackingEngine(
        llm_service=llm,
        tcc_replan=tcc,
        candidate_path_manager=candidate_path_manager,
    )
    cross_turn_tracker = CrossTurnTracker()
    failure_tracer = FailureTracer(
        llm_service=llm,
        dag_validator=DAGValidator(),
    )
    tao_engine = TAOEngine(
        llm_service=llm,
        replan_engine=replan_engine,
        constraint_manager=cm,
        state_manager=TAOStateManager(trust_state_manager),
        supervisor_interval=int(os.getenv("TAO_SUPERVISOR_INTERVAL", "3")),
        supervisor_interval_seconds=float(os.getenv("TAO_SUPERVISOR_INTERVAL_SECONDS", "0.0")),
    )
    tao_evaluator = TAOEvaluator(llm_service=llm)
    orchestrator = PlanOrchestrator(
        llm_service=llm,
        rag_service=rag,
        constraint_manager=cm,
        replan_engine=replan_engine,
        tcc_replan=tcc,
        failure_tracer=failure_tracer,
        backtracking_engine=backtracking_engine,
        trust_state_manager=trust_state_manager,
        candidate_path_manager=candidate_path_manager,
        replan_evaluator=replan_evaluator,
        tao_engine=tao_engine,
    )
    return AppState(
        llm,
        rag,
        cm,
        metrics,
        detector,
        tcc,
        replan_engine,
        replan_evaluator,
        trust_state_manager,
        candidate_path_manager,
        backtracking_engine,
        cross_turn_tracker,
        failure_tracer,
        tao_engine,
        tao_evaluator,
        orchestrator,
    )


# Global state instance
app_state = _create_state()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="XTAO",
        description="Agent Plan mechanism service based on G4C methodology",
        version="0.1.0",
    )

    # Register API routes
    app.include_router(router)

    # Prometheus metrics endpoint
    if os.getenv("PROMETHEUS_ENABLED", "false").lower() == "true":
        metrics_app = make_asgi_app()
        app.mount("/metrics", metrics_app)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "xtao.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )

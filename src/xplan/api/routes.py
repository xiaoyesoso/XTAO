"""FastAPI route definitions.

Provides REST API for the G4C Plan mechanism:
- POST /api/plan/generate - Generate Plan
- POST /api/plan/verify - Evaluate Plan
- POST /api/plan/execute - Execute Plan
- POST /api/plan/iterate - Iterative generation (generate-evaluate-correct loop)
- POST /api/plan/replan - Trigger Replan (controlled correction)
- POST /api/plan/tcc-replan - Execute TCC Replan (Try/Confirm/Cancel three steps)
- POST /api/constraints/hard - Add hard constraint
- POST /api/constraints/soft - Add soft constraint
- GET /api/constraints - Get constraint list
- POST /api/evaluation/offline - Offline analysis of Plan
- POST /api/evaluation/replan/event - Record Replan event
- GET /api/evaluation/replan/metrics - Get Replan five metrics
- GET /api/evaluation/replan/report - Get Replan evaluation report
- POST /api/evaluation/replan/annotate - Import manual annotations
- GET /api/evaluation/replan/test-set - Export test set
- GET /api/metrics - Get online monitoring metrics
- GET /api/dag/validate - Validate DAG structure
- POST /api/tao/run - Run the full TAO (Think-Action-Observation) loop
- POST /api/tao/think - Atomic TAO Think (five structured judgments + exit decision)
- POST /api/tao/act - Atomic TAO Action execution
- POST /api/tao/observe - Atomic TAO Observation interpretation
- GET /health - Health check
"""

from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from xplan.models import (
    Plan,
    PlanMode,
    DAGPlan,
    Constraints,
    ReplanResult,
    TCCResult,
    ReplanEvent,
    ReplanMetrics,
    FactEntry,
    TrustState,
    TrustStateReport,
    BacktrackingLevel,
    BacktrackingResult,
    CandidatePath,
    CrossTurnContamination,
    JumpRule,
    FailureTracingResult,
    StepRecord,
    OrchestratorConfig,
    OrchestratorResult,
    ActionCandidate,
    ActionRecord,
    Observation,
    TAOExitRecord,
    TAOResult,
    TAOState,
    ThinkResult,
    TAOEvaluationEvent,
    TAOEvaluationMetrics,
    TAOEvaluationReport,
    GoldenAnswer,
    LLMJudgeRequest,
    LLMJudgeResult,
)
from xplan.engine import (
    PlanGenerator,
    PlanVerifier,
    PlanExecutor,
    DAGValidator,
    IterationLoop,
    PlanVerificationResult,
    ReplanEngine,
    TCCReplan,
    BacktrackingEngine,
    CrossTurnTracker,
    FailureTracer,
    PlanOrchestrator,
    TAOEngine,
)
from xplan.engine.tao_action_runtime import IllegalActionError, PreconditionError
from xplan.services import (
    LLMService,
    RAGService,
    ConstraintManager,
    TrustStateManager,
    CandidatePathManager,
)
from xplan.evaluation import (
    PlanMetrics,
    OfflineAnalyzer,
    UserCorrectionDetector,
    ReplanEvaluator,
    TAOEvaluator,
)

router = APIRouter(prefix="/api", tags=["xplan"])


# ── Request/Response models ─────────────────────────────────


class GeneratePlanRequest(BaseModel):
    """Generate Plan request."""

    user_input: str = Field(description="User input")
    conversation_history: str = Field(default="", description="Conversation history")
    use_iteration: bool = Field(default=False, description="Whether to use iterative generation")


class VerifyPlanRequest(BaseModel):
    """Evaluate Plan request."""

    plan: Plan


class ExecutePlanRequest(BaseModel):
    """Execute Plan request."""

    plan: Plan


class IterateRequest(BaseModel):
    """Iterative generation request."""

    user_input: str
    conversation_history: str = ""


class AddConstraintRequest(BaseModel):
    """Add constraint request."""

    constraint: str = Field(description="Constraint content")
    user_input: str = Field(description="User input (as evidence for constraint modification)")


class OfflineAnalysisRequest(BaseModel):
    """Offline analysis request."""

    plan: Plan


class DAGValidateRequest(BaseModel):
    """DAG validation request."""

    dag: DAGPlan


class TCCReplanRequest(BaseModel):
    """TCC Replan request.

    Executes the Try/Confirm/Cancel three-step Replan methodology.
    Only applicable to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.
    """

    plan: Plan = Field(description="New Plan to validate")
    conversation_history: str = Field(
        default="", description="Conversation history, used to supplement context"
    )


class ReplanRequest(BaseModel):
    """Replan request.

    Triggers the controlled correction mechanism: during execution, based on new Goal,
    Context, Choice, Checkpoint results, performs controlled correction of the original plan.
    """

    plan: Plan = Field(description="Current Plan")
    error_info: str = Field(default="", description="Error information description")
    user_input: str = Field(default="", description="User supplementary input")
    conversation_history: str = Field(
        default="", description="Conversation history, used to supplement context"
    )


class ReplanResponse(BaseModel):
    """Replan response."""

    plan: Plan = Field(description="New Plan after Replan (or original Plan)")
    replan_result: ReplanResult | None = Field(
        default=None, description="Replan execution result details"
    )


class MetricsResponse(BaseModel):
    """Monitoring metrics response."""

    plan_completion_rate: float
    step_success_rate: float
    replan_rate: float
    user_correction_rate: float
    task_success_rate: float
    average_iteration_count: float


class RecordReplanEventRequest(BaseModel):
    """Record Replan event request."""

    event: ReplanEvent = Field(description="Replan event record")


class AnnotateReplanRequest(BaseModel):
    """Import Replan manual annotation request."""

    annotations: list[dict] = Field(
        description="Annotation list, each item contains event_id and annotation fields"
    )


class RecordTAOEvaluationEventRequest(BaseModel):
    """Record TAO evaluation event request."""

    event: TAOEvaluationEvent = Field(description="TAO evaluation event")


class AnnotateTAORequest(BaseModel):
    """Import TAO golden-answer annotations request."""

    annotations: list[GoldenAnswer] = Field(
        description="List of golden answers keyed by event_id"
    )


class TAOJudgeRequest(BaseModel):
    """TAO LLM-as-judge request."""

    request: LLMJudgeRequest = Field(description="Judge request for a TAO round")


class AddFactRequest(BaseModel):
    """Add fact entry request."""

    key: str = Field(description="Fact key, e.g. highest_qps")
    value: object = Field(description="Fact value")
    evidence: str = Field(default="", description="Evidence source")
    source_step_id: str = Field(default="", description="Step ID that produced this fact")
    depends_on: list[str] = Field(
        default_factory=list, description="List of other fact keys this fact depends on"
    )


class UpdateTrustStateRequest(BaseModel):
    """Update trust state request."""

    key: str = Field(description="Fact key")
    new_state: TrustState = Field(description="New trust state")
    reason: str = Field(default="", description="Change reason")


class BacktrackingExecuteRequest(BaseModel):
    """Execute backtracking request.

    Executes backtracking based on the specified backtracking level; auto-determines if level is not specified.
    """

    plan: Plan = Field(description="Current Plan")
    error_info: str = Field(default="", description="Error information description")
    level: BacktrackingLevel | None = Field(
        default=None, description="Backtracking level, auto-determined when None"
    )
    failure_tracing_result: dict | None = Field(
        default=None, description="Failure tracing result"
    )
    step_id: str = Field(default="", description="Failed step ID (action/step level)")
    decision_id: str = Field(default="", description="Decision node ID (step level)")
    stage_checkpoint_id: str = Field(
        default="", description="Stage Checkpoint ID (stage level)"
    )
    contamination: CrossTurnContamination | None = Field(
        default=None, description="Cross-turn contamination record (cross_turn level)"
    )


class ProgressiveBacktrackingRequest(BaseModel):
    """Progressive expansion backtracking request."""

    plan: Plan = Field(description="Current Plan")
    error_info: str = Field(default="", description="Error information description")
    failure_tracing_result: dict | None = Field(
        default=None, description="Failure tracing result"
    )


class JumpBacktrackingRequest(BaseModel):
    """Jump backtracking request."""

    error_pattern: str = Field(description="Error pattern description")
    jump_rules: list[JumpRule] | None = Field(
        default=None, description="Jump backtracking rule list"
    )


class RegisterDecisionRequest(BaseModel):
    """Register decision node request."""

    decision_id: str = Field(description="Decision node ID")
    selected: str = Field(description="Currently selected path")
    candidates: list[CandidatePath] = Field(
        default_factory=list, description="Candidate path list"
    )


class TraceRequest(BaseModel):
    """Failure tracing request.

    Triggers failure tracing and root cause location: starting from the failure point,
    traces backwards to find the root cause point, and provides rollback point and
    Replan start point suggestions.
    Core concept: failure point ≠ root cause point.
    """

    plan: Plan = Field(description="Current Plan")
    failure_step_id: str = Field(description="Failed step ID")
    failure_info: str = Field(default="", description="Failure information description")
    step_records: list[StepRecord] = Field(
        default_factory=list, description="Step execution record list"
    )


class RunPlanRequest(BaseModel):
    """Main orchestration request - the primary entry point.

    Runs the full plan lifecycle: generate -> verify -> execute -> correct.
    Internally orchestrates all G4C subsystems (failure tracing, trust state,
    backtracking, replan, evaluation) based on the provided configuration.
    """

    user_input: str = Field(description="User's goal or request")
    conversation_history: str = Field(default="", description="Conversation history for context")
    config: OrchestratorConfig | None = Field(
        default=None, description="Orchestration configuration (uses defaults if None)"
    )


class TAORunRequest(BaseModel):
    """Run the full TAO loop request.

    TAO (Think-Action-Observation) is a controlled state loop for step-level
    execution: the Plan defines the macro path, while TAO decides how each
    concrete step moves forward and interprets feedback.
    """

    user_input: str = Field(description="User's goal or request")
    plan: Plan | None = Field(
        default=None, description="Optional G4C Plan providing goal/context anchoring"
    )
    candidate_actions: list[ActionCandidate] = Field(
        default_factory=list,
        description="Full candidate action space (coarse-filtered inside the engine)",
    )
    max_loops: int = Field(default=10, description="Maximum TAO inner loop rounds")
    max_time: float = Field(default=300.0, description="Maximum execution time in seconds")


class TAOThinkRequest(BaseModel):
    """Atomic TAO Think request."""

    state: TAOState = Field(description="Current TAO state")


class TAOThinkResponse(BaseModel):
    """Atomic TAO Think response."""

    think: ThinkResult = Field(description="Structured Think result (five judgments)")
    exit: TAOExitRecord = Field(description="Exit decision for this round")


class TAOActRequest(BaseModel):
    """Atomic TAO Action execution request."""

    state: TAOState = Field(description="Current TAO state (carries the candidate space)")
    action_name: str = Field(description="Selected action name (must be in the candidate space)")
    params: dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class TAOActResponse(BaseModel):
    """Atomic TAO Action execution response."""

    record: ActionRecord = Field(description="Executed action record")


class TAOObserveRequest(BaseModel):
    """Atomic TAO Observation interpretation request."""

    state: TAOState = Field(description="Current TAO state")
    record: ActionRecord = Field(description="Action record to interpret")
    expectation: str = Field(default="", description="Optional expectation for the output")


class TAOObserveResponse(BaseModel):
    """Atomic TAO Observation interpretation response."""

    observation: Observation = Field(description="Structured interpretation of the raw output")


# ── Dependency injection ───────────────────────────────────


def get_llm_service() -> LLMService:
    """Get LLM service instance."""
    from xplan.main import app_state

    return app_state.llm_service


def get_rag_service() -> RAGService:
    """Get RAG service instance."""
    from xplan.main import app_state

    return app_state.rag_service


def get_constraint_manager() -> ConstraintManager:
    """Get constraint manager instance."""
    from xplan.main import app_state

    return app_state.constraint_manager


def get_plan_metrics() -> PlanMetrics:
    """Get monitoring metrics instance."""
    from xplan.main import app_state

    return app_state.plan_metrics


def get_tcc_replan() -> TCCReplan:
    """Get TCC Replan engine instance."""
    from xplan.main import app_state

    return app_state.tcc_replan


def get_replan_engine() -> ReplanEngine:
    """Get Replan engine instance."""
    from xplan.main import app_state

    return app_state.replan_engine


def get_replan_evaluator() -> ReplanEvaluator:
    """Get Replan effect evaluator instance."""
    from xplan.main import app_state

    return app_state.replan_evaluator


def get_trust_state_manager() -> TrustStateManager:
    """Get trust state manager instance."""
    from xplan.main import app_state

    return app_state.trust_state_manager


def get_backtracking_engine() -> BacktrackingEngine:
    """Get backtracking engine instance."""
    from xplan.main import app_state

    return app_state.backtracking_engine


def get_candidate_path_manager() -> CandidatePathManager:
    """Get candidate path manager instance."""
    from xplan.main import app_state

    return app_state.candidate_path_manager


def get_failure_tracer() -> FailureTracer:
    """Get failure tracer engine instance."""
    from xplan.main import app_state

    return app_state.failure_tracer


def get_orchestrator() -> PlanOrchestrator:
    """Get plan orchestrator instance."""
    from xplan.main import app_state

    return app_state.orchestrator


def get_tao_engine() -> TAOEngine:
    """Get TAO engine instance."""
    from xplan.main import app_state

    return app_state.tao_engine


def get_tao_evaluator() -> TAOEvaluator:
    """Get TAO evaluator instance."""
    from xplan.main import app_state

    return app_state.tao_evaluator


# ── Routes ─────────────────────────────────────────────────


@router.get("/health")
async def health_check():
    """Health check."""
    return {"status": "ok", "service": "xplan", "version": "0.1.0"}


@router.post("/plan/run")
async def run_plan(
    req: RunPlanRequest,
    orchestrator: PlanOrchestrator = Depends(get_orchestrator),
):
    """Main orchestration endpoint - the primary entry point for the full plan lifecycle.

    Runs the complete G4C pipeline internally:
    1. **Generate Plan**: Create G4C Plan (with optional iterative generate-verify-correct loop)
    2. **Verify Plan**: Evaluate plan quality across G4C 5 dimensions (optional)
    3. **Execute Plan**: Step-by-step execution with checkpoint verification
       - On checkpoint failure:
         - **Failure Tracing**: Find root cause (failure point != root cause point)
         - **Trust State**: Mark failed results as Invalid, cascade Dirty
         - **Backtracking**: Progressive expansion (action -> step -> stage -> global)
         - **Replan**: Controlled correction via ReplanEngine or TCC Replan
         - **Evaluation**: Record replan event for effectiveness metrics
    4. **Return Result**: Final plan with execution trace, replan count, and metrics

    This endpoint internally calls all other endpoints' underlying engines.
    For granular control, use individual endpoints directly.
    """
    result: OrchestratorResult = await orchestrator.run(
        user_input=req.user_input,
        conversation_history=req.conversation_history,
        config=req.config,
    )
    return result


@router.post("/plan/generate")
async def generate_plan(
    req: GeneratePlanRequest,
    llm: LLMService = Depends(get_llm_service),
    rag: RAGService = Depends(get_rag_service),
    metrics: PlanMetrics = Depends(get_plan_metrics),
):
    """Generate G4C Plan.

    Supports both normal generation and iterative generation (generate-evaluate-correct loop).
    """
    generator = PlanGenerator(llm, rag)
    if req.use_iteration:
        verifier = PlanVerifier(llm)
        loop = IterationLoop(generator, verifier)
        plan, results = await loop.run(req.user_input, req.conversation_history)
        return {
            "plan": plan,
            "verification_results": results,
            "iterations": len(results),
        }
    plan = await generator.generate(req.user_input, req.conversation_history)
    metrics.record_iteration_count("", plan.iteration_count)
    return {"plan": plan}


@router.post("/plan/verify")
async def verify_plan(
    req: VerifyPlanRequest,
    llm: LLMService = Depends(get_llm_service),
):
    """Evaluate Plan quality (G4C five dimensions)."""
    verifier = PlanVerifier(llm)
    result = await verifier.verify(req.plan)
    return {"verification": result}


@router.post("/plan/execute")
async def execute_plan(
    req: ExecutePlanRequest,
    llm: LLMService = Depends(get_llm_service),
    cm: ConstraintManager = Depends(get_constraint_manager),
    metrics: PlanMetrics = Depends(get_plan_metrics),
):
    """Execute Plan, step-by-step with checkpoint execution."""
    executor = PlanExecutor(llm, cm)
    metrics.record_plan_started("")
    plan = await executor.execute(req.plan)

    if plan.status == "completed":
        metrics.record_plan_completed("")
        metrics.record_task_success("")
    elif plan.status == "aborted":
        metrics.record_task_failure("")
    else:
        metrics.record_task_failure("")

    return {"plan": plan}


@router.post("/plan/iterate")
async def iterate_plan(
    req: IterateRequest,
    llm: LLMService = Depends(get_llm_service),
    rag: RAGService = Depends(get_rag_service),
    metrics: PlanMetrics = Depends(get_plan_metrics),
):
    """Iterative Plan generation (generate-evaluate-correct loop)."""
    generator = PlanGenerator(llm, rag)
    verifier = PlanVerifier(llm)
    loop = IterationLoop(generator, verifier)
    plan, results = await loop.run(req.user_input, req.conversation_history)
    metrics.record_iteration_count("", len(results))
    return {
        "plan": plan,
        "verification_results": results,
        "iterations": len(results),
    }


@router.post("/plan/tcc-replan")
async def tcc_replan(
    req: TCCReplanRequest,
    tcc: TCCReplan = Depends(get_tcc_replan),
):
    """Execute TCC Replan (Try/Confirm/Cancel three-step methodology).

    Borrows TCC concept from distributed transactions, validates Plan in three phases:
    - Try: Minimally validate the weakest point of the new Plan (dry-run, low side effects)
    - Confirm: Execute Plan after Try passes, reuse Try data
    - Cancel: Rollback temporary state after Try fails, mark failed assumptions

    Only applicable to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.
    """
    result: TCCResult = await tcc.run(req.plan, req.conversation_history)
    return {"result": result}


@router.post("/plan/replan")
async def replan(
    req: ReplanRequest,
    replan_engine: ReplanEngine = Depends(get_replan_engine),
):
    """Trigger Replan (controlled correction mechanism).

    During execution, based on new Goal, Context, Choice, Checkpoint results,
    performs controlled correction of the original plan.

    Full flow: detect_trigger -> code_judge -> llm_judge -> execute_replan.
    """
    error = Exception(req.error_info) if req.error_info else None
    new_plan = await replan_engine.run(
        plan=req.plan,
        error=error,
        user_input=req.user_input,
        conversation_history=req.conversation_history,
    )
    return ReplanResponse(plan=new_plan)


@router.post("/plan/trace")
async def trace_failure(
    req: TraceRequest,
    tracer: FailureTracer = Depends(get_failure_tracer),
):
    """Trigger failure tracing and root cause location.

    Core concept: failure point ≠ root cause point. Starting from the failure point,
    traces backwards to find the root cause point, and provides rollback point and
    Replan start point suggestions.

    Full flow:
    1. Code builds reverse tracing chain (build_tracing_chain)
    2. Code finds nearest Checkpoint (find_nearest_checkpoint)
    3. Code checks circular dependency (check_circular_dependency)
    4. LLM performs semantic root cause location (llm_trace_root_cause)
    5. Merge code and LLM results, return FailureTracingResult
    """
    result: FailureTracingResult = await tracer.trace(
        plan=req.plan,
        failure_step_id=req.failure_step_id,
        failure_info=req.failure_info,
        step_records=req.step_records,
    )
    return {"result": result}


@router.post("/constraints/hard")
async def add_hard_constraint(
    req: AddConstraintRequest,
    cm: ConstraintManager = Depends(get_constraint_manager),
):
    """Add hard constraint.

    Constraint modification requires user input as evidence; Agent cannot modify constraints autonomously.
    """
    try:
        cm.add_hard_constraint(req.constraint, req.user_input)
        return {"success": True, "constraints": cm.get_hard_constraints()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/constraints/soft")
async def add_soft_constraint(
    req: AddConstraintRequest,
    cm: ConstraintManager = Depends(get_constraint_manager),
):
    """Add soft constraint."""
    try:
        cm.add_soft_constraint(req.constraint, req.user_input)
        return {"success": True, "constraints": cm.get_soft_constraints()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/constraints")
async def get_constraints(
    cm: ConstraintManager = Depends(get_constraint_manager),
):
    """Get constraint list."""
    return {
        "hard": cm.get_hard_constraints(),
        "soft": cm.get_soft_constraints(),
    }


@router.post("/evaluation/offline")
async def offline_analysis(
    req: OfflineAnalysisRequest,
    llm: LLMService = Depends(get_llm_service),
):
    """Offline analysis of Plan quality (around G4C five dimensions)."""
    analyzer = OfflineAnalyzer(llm)
    result = await analyzer.analyze(req.plan)
    return {"analysis": result}


@router.post("/evaluation/replan/event")
async def record_replan_event(
    req: RecordReplanEventRequest,
    evaluator: ReplanEvaluator = Depends(get_replan_evaluator),
):
    """Record Replan event.

    Collects complete information of a single Replan event for subsequent effect evaluation.
    Events with the same event_id are updated rather than recorded duplicated.
    """
    evaluator.record_event(req.event)
    return {
        "success": True,
        "event_id": req.event.event_id,
        "total_events": len(evaluator.get_events()),
    }


@router.get("/evaluation/replan/metrics")
async def get_replan_metrics(
    evaluator: ReplanEvaluator = Depends(get_replan_evaluator),
):
    """Get Replan effect evaluation five metrics.

    Returns: root cause accuracy, Replan start accuracy, result reuse rate,
    Replan recovery success rate, Replan oscillation rate and basic statistics.
    """
    return evaluator.get_metrics()


@router.get("/evaluation/replan/report")
async def get_replan_report(
    evaluator: ReplanEvaluator = Depends(get_replan_evaluator),
):
    """Get Replan evaluation report.

    Returns evaluation report in text format, including five metrics and improvement suggestions.
    """
    report = evaluator.generate_report()
    return {"report": report}


@router.post("/evaluation/replan/annotate")
async def annotate_replan(
    req: AnnotateReplanRequest,
    evaluator: ReplanEvaluator = Depends(get_replan_evaluator),
):
    """Import manual annotation results.

    Matches and updates event annotation fields by event_id
    (root_cause_correct / replan_start_correct, etc.).
    """
    evaluator.import_annotations(req.annotations)
    return {
        "success": True,
        "annotated_count": len(req.annotations),
    }


@router.get("/evaluation/replan/test-set")
async def export_replan_test_set(
    evaluator: ReplanEvaluator = Depends(get_replan_evaluator),
):
    """Export Replan evaluation test set.

    Exports key fields of all events for manual annotation or fault injection evaluation,
    root_cause_correct and replan_start_correct are set to None for annotation.
    """
    test_set = evaluator.export_test_set()
    return {"test_set": test_set, "total": len(test_set)}


@router.post("/evaluation/tao/event")
async def record_tao_evaluation_event(
    req: RecordTAOEvaluationEventRequest,
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Record a TAO evaluation event.

    Stores Think / Action / Observation round data for subsequent metric
    computation and report generation.
    """
    evaluator.record_event(req.event)
    return {
        "success": True,
        "event_id": req.event.event_id,
        "total_events": len(evaluator.get_events()),
    }


@router.get("/evaluation/tao/metrics")
async def get_tao_metrics(
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Get aggregated TAO evaluation metrics (Think/Action/Observation/Overall)."""
    return evaluator.get_metrics()


@router.get("/evaluation/tao/report")
async def get_tao_report(
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Get TAO evaluation report with metrics, abnormal samples and suggestions."""
    return evaluator.generate_report()


@router.post("/evaluation/tao/annotate")
async def annotate_tao(
    req: AnnotateTAORequest,
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Import human golden-answer annotations for TAO evaluation.

    Annotations are matched to events by event_id and used to compute
    accuracy metrics such as action selection and fact extraction.
    """
    count = evaluator.import_golden_answers(
        [a.model_dump(mode="json") for a in req.annotations]
    )
    return {"success": True, "annotated_count": count}


@router.get("/evaluation/tao/test-set")
async def export_tao_test_set(
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Export TAO evaluation test set for human annotation.

    Returns event metadata with golden-answer fields left empty.
    """
    test_set = evaluator.export_test_set()
    return {"test_set": test_set, "total": len(test_set)}


@router.post("/evaluation/tao/judge")
async def tao_llm_judge(
    req: TAOJudgeRequest,
    evaluator: TAOEvaluator = Depends(get_tao_evaluator),
):
    """Run LLM-as-judge on a single TAO round."""
    result = await evaluator.llm_judge(req.request)
    return {"result": result}


@router.get("/metrics")
async def get_metrics(
    metrics: PlanMetrics = Depends(get_plan_metrics),
):
    """Get online monitoring metrics."""
    return MetricsResponse(
        plan_completion_rate=metrics.get_plan_completion_rate(),
        step_success_rate=metrics.get_step_success_rate(),
        replan_rate=metrics.get_replan_rate(),
        user_correction_rate=metrics.get_user_correction_rate(),
        task_success_rate=metrics.get_task_success_rate(),
        average_iteration_count=metrics.get_average_iteration_count(),
    )


@router.post("/dag/validate")
async def validate_dag(req: DAGValidateRequest):
    """Validate DAG structure (circular dependency detection, node reference validity)."""
    validator = DAGValidator()
    errors = validator.validate(req.dag)
    cycles = validator.detect_cycles(req.dag)
    topo_order = validator.get_topological_order(req.dag)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "cycles": cycles,
        "topological_order": topo_order,
    }


# ── Trust state management ─────────────────────────────────


@router.post("/trust-state/facts")
async def add_fact(
    req: AddFactRequest,
    tsm: TrustStateManager = Depends(get_trust_state_manager),
):
    """Add fact entry (default state is AVAILABLE).

    Marks trust state for intermediate results, supports evidence source and dependency recording.
    """
    fact: FactEntry = tsm.add_fact(
        key=req.key,
        value=req.value,
        evidence=req.evidence,
        source_step_id=req.source_step_id,
        depends_on=req.depends_on,
    )
    return {"success": True, "fact": fact}


@router.get("/trust-state/facts")
async def get_facts(
    tsm: TrustStateManager = Depends(get_trust_state_manager),
):
    """Get all fact entries."""
    return {"facts": tsm.get_all_facts()}


@router.post("/trust-state/update")
async def update_trust_state(
    req: UpdateTrustStateRequest,
    tsm: TrustStateManager = Depends(get_trust_state_manager),
):
    """Update the trust state of a fact.

    If the new state is INVALID, automatically triggers cascade marking:
    all facts depending on this fact will be marked as DIRTY (BFS traversal of dependency chain).
    Returns all change records (including cascade marking).
    """
    try:
        changes = tsm.update_trust_state(req.key, req.new_state, req.reason)
        return {"success": True, "changes": changes}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trust-state/report")
async def get_trust_state_report(
    tsm: TrustStateManager = Depends(get_trust_state_manager),
):
    """Get trust state report (including count statistics for each state)."""
    report: TrustStateReport = tsm.get_report()
    return report


@router.get("/trust-state/suspicious")
async def get_suspicious_and_dirty(
    tsm: TrustStateManager = Depends(get_trust_state_manager),
):
    """Get Suspicious and Dirty facts that need priority checking.

    When backtracking to locate root causes, prioritize checking these facts (skip Verified).
    """
    return {"facts": tsm.get_suspicious_and_dirty()}


# ── Backtracking levels and candidate paths ────────────────


@router.post("/backtracking/execute")
async def execute_backtracking(
    req: BacktrackingExecuteRequest,
    engine: BacktrackingEngine = Depends(get_backtracking_engine),
):
    """Execute backtracking.

    Executes backtracking based on the specified backtracking level; auto-determines if level is not specified.
    Supports five backtracking levels: ACTION / STEP / STAGE / GLOBAL / CROSS_TURN.
    """
    error = Exception(req.error_info) if req.error_info else None

    # Auto-determine backtracking level
    level = req.level
    if level is None:
        level = engine.determine_level(
            error, req.failure_tracing_result, req.plan
        )

    # Execute corresponding backtracking based on level
    if level == BacktrackingLevel.ACTION:
        result = await engine.action_level_retry(
            req.plan, req.step_id, error
        )
    elif level == BacktrackingLevel.STEP:
        result = await engine.step_level_switch(
            req.plan, req.step_id, req.decision_id or req.step_id
        )
    elif level == BacktrackingLevel.STAGE:
        result = await engine.stage_level_rollback(
            req.plan, req.stage_checkpoint_id or req.step_id
        )
    elif level == BacktrackingLevel.GLOBAL:
        result = await engine.global_replan(req.plan)
    elif level == BacktrackingLevel.CROSS_TURN:
        if req.contamination is None:
            raise HTTPException(
                status_code=400,
                detail="cross_turn level backtracking requires contamination parameter",
            )
        result = await engine.cross_turn_replan(
            req.plan, req.contamination
        )
    else:
        raise HTTPException(
            status_code=400, detail=f"Unsupported backtracking level: {level}"
        )

    return {"result": result, "level": level}


@router.post("/backtracking/progressive")
async def progressive_backtracking(
    req: ProgressiveBacktrackingRequest,
    engine: BacktrackingEngine = Depends(get_backtracking_engine),
):
    """Progressive expansion backtracking.

    Progressively expands backtracking scope: ACTION -> STEP -> STAGE -> GLOBAL,
    judging new plan feasibility via TCC before each expansion.
    """
    error = Exception(req.error_info) if req.error_info else None
    result = await engine.progressive_expansion(
        req.plan, error, req.failure_tracing_result
    )
    return {"result": result}


@router.post("/backtracking/jump")
async def jump_backtracking(
    req: JumpBacktrackingRequest,
    engine: BacktrackingEngine = Depends(get_backtracking_engine),
):
    """Jump backtracking.

    Matches error patterns via predefined rules, directly locates backtracking position,
    skipping the overhead of progressive expansion.
    """
    result = await engine.jump_backtracking(
        req.error_pattern, req.jump_rules
    )
    if result is None:
        return {"result": None, "matched": False}
    return {"result": result, "matched": True}


@router.post("/candidate-paths/register")
async def register_decision(
    req: RegisterDecisionRequest,
    cpm: CandidatePathManager = Depends(get_candidate_path_manager),
):
    """Register decision node.

    Records the selected path and candidate path list of a decision node, supporting subsequent path switching.
    """
    cpm.register_decision(req.decision_id, req.selected, req.candidates)
    return {
        "success": True,
        "decision_id": req.decision_id,
        "selected": req.selected,
        "candidate_count": len(req.candidates),
    }


@router.post("/candidate-paths/switch/{decision_id}")
async def switch_candidate_path(
    decision_id: str,
    cpm: CandidatePathManager = Depends(get_candidate_path_manager),
):
    """Fast path switching.

    Gets the next available candidate path of the decision node and switches to it.
    """
    result = cpm.switch_path(decision_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Decision node {decision_id} has no available candidate paths",
        )
    return {"success": True, "new_path": result.path}


@router.get("/candidate-paths/failed")
async def get_failed_paths(
    cpm: CandidatePathManager = Depends(get_candidate_path_manager),
):
    """Get failed path records.

    Returns all failed path records, including failure reasons and recovery status.
    """
    return {"failed_paths": cpm.get_failed_paths()}


# ── TAO (Think-Action-Observation) loop ────────────────────


@router.post("/tao/run")
async def tao_run(
    req: TAORunRequest,
    tao: TAOEngine = Depends(get_tao_engine),
):
    """Run the full TAO (Think-Action-Observation) controlled state loop.

    The TAO loop drives step-level execution through five runtime states
    (Goal / Action / Observation / Fact / Control):
    1. **Think**: Five structured judgments (goal, state, path, stop, risk)
    2. **Action**: Execute the selected candidate action (with retry control)
    3. **Observation**: Interpret the raw output, extract evidence-bound facts
    4. **Exit decision**: continue / finish / clarify / retry / replan / interrupt
    5. **Outer supervisor loop** (optional): checks goal drift, constraint
       violations and stagnation every N inner rounds

    Control State prevents runaway execution via `max_loops` and `max_time`.
    Returns a TAOResult with the final exit, output and full exit history.
    """
    result: TAOResult = await tao.run(
        user_input=req.user_input,
        plan=req.plan,
        candidate_actions=req.candidate_actions,
        max_loops=req.max_loops,
        max_time=req.max_time,
    )
    return result


@router.post("/tao/think")
async def tao_think(
    req: TAOThinkRequest,
    tao: TAOEngine = Depends(get_tao_engine),
):
    """Atomic TAO Think: run one Think round on the given state.

    Produces a structured ThinkResult (five judgments: goal, state, path,
    stop, risk) plus the loop controller's exit decision. The caller is
    responsible for carrying the TAOState between calls.
    """
    think = await tao.think_engine.think(req.state)
    exit_record = tao.loop_controller.decide(req.state, think)
    return TAOThinkResponse(think=think, exit=exit_record)


@router.post("/tao/act")
async def tao_act(
    req: TAOActRequest,
    tao: TAOEngine = Depends(get_tao_engine),
):
    """Atomic TAO Action execution.

    Executes the named action from the candidate space carried in the state.
    Illegal actions (outside the candidate space) and unsatisfied hard
    preconditions are rejected with a 400 error.
    """
    candidate = next(
        (c for c in req.state.candidate_actions if c.name == req.action_name),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Action '{req.action_name}' is not in the candidate space "
                f"{sorted(c.name for c in req.state.candidate_actions)}"
            ),
        )
    try:
        record = await tao.action_runtime.execute(candidate, req.params, req.state)
    except (IllegalActionError, PreconditionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TAOActResponse(record=record)


@router.post("/tao/observe")
async def tao_observe(
    req: TAOObserveRequest,
    tao: TAOEngine = Depends(get_tao_engine),
):
    """Atomic TAO Observation interpretation.

    Interprets an action's raw output into a structured Observation:
    code performs field/format checks, the LLM performs semantic
    interpretation (fact extraction, evidence binding, gap identification).
    Note: HTTP 200 != real success; empty data and anomalies are detected.
    """
    observation = await tao.observation_interpreter.interpret(
        req.state, req.record, req.expectation
    )
    return TAOObserveResponse(observation=observation)

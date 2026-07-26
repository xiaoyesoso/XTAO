"""Plan orchestrator models - Main orchestration endpoint data structures."""

from pydantic import BaseModel, Field
from typing import Any

from xplan.models.plan import Plan


class OrchestratorConfig(BaseModel):
    """Configuration for plan orchestration.

    Controls which subsystems are enabled during the full plan lifecycle.
    """

    use_iteration: bool = Field(default=True, description="Whether to use iterative generation (generate-verify-correct loop)")
    max_iterations: int = Field(default=3, description="Max iterations for iterative generation")
    verify_before_execute: bool = Field(default=True, description="Whether to verify plan before execution")
    verification_threshold: float = Field(default=0.8, description="Verification score threshold (0-1)")
    enable_failure_tracing: bool = Field(default=True, description="Enable failure tracing on checkpoint failure")
    enable_trust_state: bool = Field(default=True, description="Enable trust state management during execution")
    enable_progressive_backtracking: bool = Field(default=True, description="Enable progressive backtracking on failure")
    enable_tcc_replan: bool = Field(default=False, description="Enable TCC Replan for high-risk scenarios")
    max_replan_count: int = Field(default=3, description="Max replan attempts during execution")


class StepExecutionRecord(BaseModel):
    """Record of a single step execution within the orchestration."""

    step_id: str = Field(description="Step ID")
    step_objective: str = Field(default="", description="Step objective")
    status: str = Field(default="pending", description="Step status: pending/running/done/failed")
    output: str = Field(default="", description="Step execution output")
    checkpoint_passed: bool | None = Field(default=None, description="Whether checkpoint passed (None if no checkpoint)")
    checkpoint_results: list[dict[str, Any]] = Field(default_factory=list, description="Checkpoint check results")
    correction_applied: str | None = Field(default=None, description="Correction type applied: retry/replan/clarify/rollback/abort")
    failure_traced: bool = Field(default=False, description="Whether failure tracing was performed")
    root_cause_step_id: str | None = Field(default=None, description="Root cause step ID (if traced)")
    backtracking_level: str | None = Field(default=None, description="Backtracking level used: action/step/stage/global")
    replan_triggered: bool = Field(default=False, description="Whether replan was triggered at this step")


class OrchestratorResult(BaseModel):
    """Complete result of plan orchestration.

    Returned by the main POST /api/plan/run endpoint.
    Contains the final plan, execution trace, and all metrics.
    """

    plan: Plan = Field(description="Final plan (may differ from initial if replanned)")
    status: str = Field(description="Final status: completed/failed/aborted/clarify_needed")
    step_records: list[StepExecutionRecord] = Field(default_factory=list, description="Execution trace for each step")
    replan_count: int = Field(default=0, description="Total replan attempts")
    iteration_count: int = Field(default=0, description="Plan generation iteration count")
    verification_score: float | None = Field(default=None, description="Plan verification score (0-1)")
    verification_passed: bool | None = Field(default=None, description="Whether verification passed threshold")
    errors: list[str] = Field(default_factory=list, description="Errors encountered during execution")
    clarify_message: str | None = Field(default=None, description="Clarification message (if status is clarify_needed)")

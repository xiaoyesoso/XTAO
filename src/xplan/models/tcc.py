"""TCC Replan data model - Try/Confirm/Cancel three-step Replan methodology.

Borrows from distributed transaction TCC concept, implements optional advanced Replan scheme.
Only applicable to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.

Three phases:
- Try: minimally validate the weakest point of the new Plan, uses dry-run mechanism, low side effects
- Confirm: execute Plan after all Try validations pass, reuses reusable data produced by Try
- Cancel: rollback temp state after Try fails, marks failed assumptions, decides whether to continue Replan
"""

from enum import Enum

from pydantic import BaseModel, Field

from xplan.models.plan import Plan


class TCCPhase(str, Enum):
    """TCC phase type."""

    TRY = "try"
    CONFIRM = "confirm"
    CANCEL = "cancel"


class TryValidationType(str, Enum):
    """Try validation type."""

    TOOL_AVAILABILITY = "tool_availability"  # Tool availability
    DATA_ACCESSIBILITY = "data_accessibility"  # Data accessibility
    ASSUMPTION_VALIDATION = "assumption_validation"  # Core assumption validation
    KEY_DEPENDENCY = "key_dependency"  # Whether key dependencies are satisfied


class TryValidation(BaseModel):
    """Try validation result."""

    target_step_id: str = Field(description="Target step ID to validate")
    validation_type: TryValidationType = Field(description="Validation type")
    passed: bool = Field(description="Whether passed")
    result: str = Field(default="", description="Validation result description")
    evidence: str = Field(default="", description="Validation evidence")


class TryResult(BaseModel):
    """Try phase result."""

    validations: list[TryValidation] = Field(
        default_factory=list, description="Validation result list"
    )
    all_passed: bool = Field(default=False, description="Whether all passed")
    temp_data: dict = Field(
        default_factory=dict, description="Temp data produced by Try, placed in temp space"
    )
    failed_assumptions: list[str] = Field(
        default_factory=list, description="Failed assumption list"
    )
    unavailable_tools: list[str] = Field(
        default_factory=list, description="Unavailable tool list"
    )


class ConfirmResult(BaseModel):
    """Confirm phase result."""

    executed: bool = Field(default=False, description="Whether executed")
    try_results_written: bool = Field(
        default=False, description="Whether Try results have been written to context"
    )
    reused_try_data: bool = Field(default=False, description="Whether Try data was reused")
    execution_summary: str = Field(default="", description="Execution summary")


class CancelResult(BaseModel):
    """Cancel phase result."""

    temp_data_cleaned: bool = Field(
        default=False, description="Whether temp data has been cleaned"
    )
    failed_assumptions_marked: list[str] = Field(
        default_factory=list, description="Marked failed assumptions"
    )
    unavailable_tools_marked: list[str] = Field(
        default_factory=list, description="Marked unavailable tools"
    )
    should_continue_replan: bool = Field(
        default=False, description="Whether to continue Replan"
    )
    has_alternative_solutions: bool = Field(
        default=False, description="Whether alternative solutions exist"
    )
    abort_reason: str | None = Field(default="", description="Abort reason (if not continuing Replan)")


class TCCResult(BaseModel):
    """TCC Replan complete result."""

    phase: TCCPhase = Field(description="Final phase")
    try_result: TryResult | None = Field(default=None, description="Try phase result")
    confirm_result: ConfirmResult | None = Field(
        default=None, description="Confirm phase result"
    )
    cancel_result: CancelResult | None = Field(
        default=None, description="Cancel phase result"
    )
    new_plan: Plan | None = Field(default=None, description="Final new Plan (if successful)")

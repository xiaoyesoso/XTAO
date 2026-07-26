"""Correction model - correction mechanism and failure recovery."""

from enum import Enum

from pydantic import BaseModel, Field


class CorrectionType(str, Enum):
    """Correction strategy type.

    - RETRY: retry (step-level / partial-flow / full-restart)
    - REPLAN: regenerate Plan (Plan itself has issues)
    - CLARIFY: clarify with user (prioritize collecting information when insufficient)
    - ROLLBACK: rollback to before a step (used with Checkpoint)
    - ABORT: abort execution (irrecoverable error)
    """

    RETRY = "retry"
    REPLAN = "replan"
    CLARIFY = "clarify"
    ROLLBACK = "rollback"
    ABORT = "abort"


class RetryGranularity(str, Enum):
    """Retry granularity."""

    STEP = "step"
    PARTIAL_FLOW = "partial_flow"
    FULL_RESTART = "full_restart"


class CorrectionAction(BaseModel):
    """Structured correction action.

    Equivalent to action in TAO/ReAct loop, supports complex parameters and tool/Skill integration.
    """

    type: CorrectionType = Field(description="Correction strategy type")
    retry_granularity: RetryGranularity | None = Field(
        default=None,
        description="Retry granularity, only valid when type=retry",
    )
    target_step_id: str | None = Field(
        default=None,
        description="Target step ID, used for rollback or partial retry",
    )
    params: dict = Field(
        default_factory=dict,
        description="Additional parameters, supports complex correction scenarios",
    )
    message: str = Field(default="", description="Description of the correction action")


class Correction(BaseModel):
    """Correction rule definition.

    Specifies the corresponding correction strategy for specific failure scenarios.
    """

    condition: str = Field(description="Trigger condition description")
    action: CorrectionAction = Field(description="Correction action")

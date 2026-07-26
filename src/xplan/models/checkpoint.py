"""Checkpoint model - checkpoint and process verification."""

from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    """Checkpoint definition.

    Associates with a step_id, contains the list of check items to verify for that step.
    Checkpoints are set at: milestones, key intermediate outputs, after error-prone steps.
    """

    step_id: str = Field(description="Associated step ID")
    checks: list[str] = Field(
        default_factory=list,
        description="Check item list, each item is a specific verifiable check condition",
    )


class CheckEvidence(BaseModel):
    """Check evidence."""

    description: str = Field(description="Evidence description")
    source: str = Field(default="", description="Evidence source")


class CheckResult(BaseModel):
    """Checkpoint execution result.

    Output when executing a checkpoint, contains check items, results and evidence.
    Provides basis for correction and root cause investigation.
    """

    step_id: str = Field(description="Associated step ID")
    check_point: str = Field(description="Check item")
    passed: bool = Field(description="Whether passed")
    result: str = Field(description="Check result description")
    evidences: list[CheckEvidence] = Field(
        default_factory=list,
        description="Evidence list supporting the check result",
    )

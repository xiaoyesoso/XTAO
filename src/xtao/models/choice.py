"""Choice model - path decision and steps."""

from pydantic import BaseModel, Field


class Step(BaseModel):
    """A single step in Plan.

    Each step carries a reason field explaining why this step is needed, supporting traceability.
    """

    id: str = Field(description="Step unique identifier")
    objective: str = Field(description="Step objective")
    reason: str = Field(default="", description="Reason for the step's existence, supports traceability")
    status: str = Field(
        default="pending",
        description="Step status: pending | running | done | failed | skipped",
    )


class Choice(BaseModel):
    """Path decision of Plan.

    Resolves path uncertainty: what paths are available and why this path was chosen.
    reason must be evidence-based, derived from facts or constraints in the context.
    """

    selected_path: str = Field(description="Description of the selected path")
    reason: str = Field(
        description="Selection reason, must be based on facts or constraints in the context (evidence-based)",
    )
    candidate_paths: list[str] = Field(
        default_factory=list,
        description="Candidate path list",
    )
    steps: list[Step] = Field(
        default_factory=list,
        description="Step list, each step contains id, objective, reason",
    )

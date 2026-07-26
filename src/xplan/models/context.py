"""Context model - context and constraint management."""

from pydantic import BaseModel, Field


class Constraints(BaseModel):
    """Constraint set, divided into hard constraints and soft constraints.

    Hard constraints cannot be violated; when violated, execution must be blocked.
    Soft constraints should be satisfied; when violated, record but allow continuation.
    """

    hard: list[str] = Field(default_factory=list, description="Hard constraint list, cannot be violated")
    soft: list[str] = Field(default_factory=list, description="Soft constraint list, should be satisfied")


class Context(BaseModel):
    """Context definition of Plan.

    Resolves context uncertainty: what is currently known, what is still missing, which constraints cannot be violated.
    """

    known_facts: list[str] = Field(
        default_factory=list,
        description="Known facts list, information recognized or confirmed by the user",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Missing information list, information needed for Plan generation but currently unavailable",
    )
    constraints: Constraints = Field(
        default_factory=Constraints,
        description="Constraint set, divided into hard constraints and soft constraints",
    )

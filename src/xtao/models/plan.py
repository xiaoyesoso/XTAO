"""Plan composite object - G4C runtime object.

Plan is not a step list, but a checkable, correctable, executable runtime object.
Contains five top-level fields: Goal, Context, Choice, Checkpoint, Correction.
"""

from enum import Enum

from pydantic import BaseModel, Field

from xtao.models.choice import Choice
from xtao.models.checkpoint import Checkpoint, CheckResult
from xtao.models.context import Context
from xtao.models.correction import Correction
from xtao.models.dag import DAGPlan
from xtao.models.goal import Goal


class PlanMode(str, Enum):
    """Plan mode.

    - LINEAR: linear Plan (default), simple, reliable, easy to debug
    - DAG: DAG-style Plan (optional advanced mode), suitable for complex scenarios requiring step parallelism
    """

    LINEAR = "linear"
    DAG = "dag"


class PlanStatus(str, Enum):
    """Plan execution status."""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class Plan(BaseModel):
    """G4C composite Plan object.

    The essence of Plan is to resolve execution uncertainty, containing five elements:
    - Goal: where to go (goal and success criteria)
    - Context: current situation (known/missing information and constraints)
    - Choice: how to get there (path decision and steps)
    - Checkpoint: how to know if deviating (checkpoint and process verification)
    - Correction: how to get back on track (correction and failure recovery)
    """

    goal: Goal = Field(description="Goal and success criteria")
    context: Context = Field(default_factory=Context, description="Context and constraints")
    choice: Choice = Field(description="Path decision and steps")
    checkpoint: list[Checkpoint] = Field(
        default_factory=list,
        description="Checkpoint list",
    )
    correction: list[Correction] = Field(
        default_factory=list,
        description="Correction rule list",
    )

    # Runtime metadata
    mode: PlanMode = Field(default=PlanMode.LINEAR, description="Plan mode")
    status: PlanStatus = Field(default=PlanStatus.DRAFT, description="Execution status")
    dag: DAGPlan | None = Field(default=None, description="DAG structure, only valid when mode=dag")

    # Execution records
    check_results: list[CheckResult] = Field(
        default_factory=list,
        description="Checkpoint execution results, supports root cause investigation",
    )
    current_step_index: int = Field(default=0, description="Current execution step index")
    iteration_count: int = Field(
        default=0,
        description="Iteration generation loop count",
    )

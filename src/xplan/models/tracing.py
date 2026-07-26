"""Failure backtracking and root cause localization data model.

Core concept: failure point != root cause point.
- Failure point: where the error is exposed (usually the step that failed execution)
- Root cause point: where the error was originally introduced (may be in an earlier step or context)
- Rollback point: where state can be recovered
- Replan start point: where re-planning begins

Backtracking uses a reverse tracing chain, starting from the failure point and checking upstream layer by layer to find the true root cause point.
"""

from typing import Any

from pydantic import BaseModel, Field


class TracingPoint(BaseModel):
    """Backtracking key point.

    Used to identify key nodes in the failure backtracking process, including:
    failure point, root cause point, rollback point, replan start point.
    """

    step_id: str = Field(description="Step ID")
    reason: str = Field(default="", description="Reason for determining this point")
    checkpoint_id: str | None = Field(default=None, description="Associated Checkpoint ID")
    action: str = Field(default="", description="Failure point only: failed action")
    error: str = Field(default="", description="Failure point only: error message")


class FailureTracingResult(BaseModel):
    """Failure backtracking result.

    Contains four key point definitions and the reverse tracing chain:
    - failure_point: failure point, where the error is exposed
    - root_cause_point: root cause point, where the error was originally introduced
    - rollback_point: rollback point, state recovery location
    - replan_start_point: replan start point, starting position for re-planning
    - tracing_chain: reverse tracing chain, from failure point upward layer by layer
    """

    failure_point: TracingPoint = Field(description="Failure point: where the error is exposed")
    root_cause_point: TracingPoint | None = Field(
        default=None, description="Root cause point: where the error was originally introduced"
    )
    rollback_point: TracingPoint | None = Field(
        default=None, description="Rollback point: state recovery location"
    )
    replan_start_point: TracingPoint | None = Field(
        default=None, description="Replan start point"
    )
    tracing_chain: list[TracingPoint] = Field(
        default_factory=list, description="Reverse tracing chain"
    )
    checkpoint_reliable: bool = Field(
        default=True, description="Whether the Checkpoint is reliable"
    )


class StepRecord(BaseModel):
    """Step execution record.

    Records the complete execution information of a single step, used for failure backtracking analysis.
    Contains input/output, facts and assumptions used, tool calls, checkpoint results and state snapshots.
    """

    step_id: str = Field(description="Step ID")
    input: dict[str, Any] = Field(default_factory=dict, description="Step input")
    output: dict[str, Any] = Field(default_factory=dict, description="Step output")
    context_used: list[str] = Field(
        default_factory=list, description="Context keys used"
    )
    facts_used: list[dict[str, Any]] = Field(
        default_factory=list, description="Facts and evidence used"
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Assumptions depended on"
    )
    tool_name: str = Field(default="", description="Tool name")
    tool_input: dict[str, Any] = Field(
        default_factory=dict, description="Tool input"
    )
    tool_output: dict[str, Any] = Field(
        default_factory=dict, description="Tool output"
    )
    checkpoint_result: dict[str, Any] | None = Field(
        default=None, description="Checkpoint verification result"
    )
    snapshot: dict[str, Any] = Field(
        default_factory=dict, description="State snapshot seen at decision time"
    )
    timestamp: str = Field(default="", description="Execution timestamp")

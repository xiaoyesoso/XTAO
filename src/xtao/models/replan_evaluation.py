"""Replan effectiveness evaluation data model.

Defines the data structures needed for Replan effectiveness evaluation, used to quantitatively evaluate the Replan mechanism's
performance in five aspects: root cause localization, start point selection, result reuse, recovery success rate and oscillation control.

Five core metrics:
- Root cause localization accuracy (root_cause_accuracy)
- Replan start point accuracy (replan_start_accuracy)
- Existing result reuse rate (result_reuse_rate)
- Replan recovery success rate (recovery_success_rate)
- Replan oscillation rate (oscillation_rate)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReplanEvent(BaseModel):
    """Single Replan event record.

    Records key information from a Replan trigger to recovery completion,
    some fields need to be backfilled after manual annotation or fault injection evaluation.
    """

    event_id: str = Field(description="Event ID")
    timestamp: str = Field(default="", description="Event timestamp")
    plan_id: str = Field(description="Plan ID")
    trigger: str = Field(description="Trigger reason")
    failure_step_id: str = Field(default="", description="Failure step")
    root_cause_step_id: str = Field(
        default="", description="Localized root cause step"
    )
    actual_root_cause: str = Field(
        default="", description="Actual root cause (manual annotation or fault injection)"
    )
    root_cause_correct: bool | None = Field(
        default=None, description="Whether root cause localization is correct"
    )
    replan_start_step_id: str = Field(
        default="", description="Replan start step"
    )
    actual_replan_start: str = Field(
        default="", description="Actual reasonable Replan start point"
    )
    replan_start_correct: bool | None = Field(
        default=None, description="Whether the Replan start point is reasonable"
    )
    total_results: int = Field(default=0, description="Total intermediate result count")
    trusted_results: int = Field(default=0, description="Trusted result count")
    reused_results: int = Field(default=0, description="Reused result count")
    recovered: bool = Field(default=False, description="Whether recovery succeeded")
    path_history: list[str] = Field(
        default_factory=list, description="Path switch history"
    )


class ReplanMetrics(BaseModel):
    """Replan effectiveness evaluation metrics.

    Aggregates five core metrics and basic statistics, used to evaluate the overall effectiveness of the Replan mechanism.
    """

    root_cause_accuracy: float = Field(
        default=0.0, description="Root cause localization accuracy"
    )
    replan_start_accuracy: float = Field(
        default=0.0, description="Replan start point accuracy"
    )
    result_reuse_rate: float = Field(
        default=0.0, description="Existing result reuse rate"
    )
    recovery_success_rate: float = Field(
        default=0.0, description="Replan recovery success rate"
    )
    oscillation_rate: float = Field(
        default=0.0, description="Replan oscillation rate"
    )
    total_replan_count: int = Field(default=0, description="Total Replan count")
    total_failure_cases: int = Field(
        default=0, description="Total failure case count"
    )


class OscillationDetector(BaseModel):
    """Oscillation detection result.

    Describes the oscillation of a single Plan or global path switching, oscillation is defined as
    the same path pair switching repeatedly >= 2 times within the window size (e.g. A->B->A->B).
    """

    is_oscillating: bool = Field(default=False, description="Whether oscillating")
    oscillation_count: int = Field(default=0, description="Oscillation count")
    oscillating_paths: list[list[str]] = Field(
        default_factory=list, description="Oscillating path pairs"
    )

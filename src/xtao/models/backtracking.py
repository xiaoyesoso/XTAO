"""Backtracking level and candidate path data model.

Implements five backtracking levels, candidate path retention and failed path tracking, jump backtracking.

Five backtracking levels (from smallest to largest scope):
- ACTION: action level (retry), does not modify Plan, retries directly
- STEP: step level (switch tool), switches to the next candidate path
- STAGE: stage level (return to stage entry), re-plans with Checkpoint as stage boundary
- GLOBAL: global, invalidates all intermediate results, starts from original state
- CROSS_TURN: cross-turn, handles historical data contaminated by error facts
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BacktrackingLevel(str, Enum):
    """Backtracking level.

    Arranged from smallest to largest backtracking scope, progressive expansion strategy upgrades step by step in this order.
    """

    ACTION = "action"        # Action level (retry)
    STEP = "step"            # Step level (switch tool)
    STAGE = "stage"          # Stage level (return to stage entry)
    GLOBAL = "global"        # Global
    CROSS_TURN = "cross_turn"  # Cross-turn


class CandidatePath(BaseModel):
    """Candidate path.

    Records the optional paths of a decision node and their status, supports failed path tracking and fast switching.
    """

    path: str = Field(description="Path name")
    status: str = Field(default="available", description="Status: available/failed/tried")
    reason: str = Field(default="", description="Failure reason (when failed)")
    failure_id: str = Field(default="", description="Failure record ID")


class DecisionNode(BaseModel):
    """Decision node (with candidate paths).

    Each decision node records the currently selected path and all candidate paths.
    When the selected path fails, it can switch to the next available candidate path.
    """

    decision_id: str = Field(description="Decision node ID")
    selected: str = Field(description="Currently selected path")
    candidates: list[CandidatePath] = Field(default_factory=list, description="Candidate path list")


class FailurePathRecord(BaseModel):
    """Failed path record.

    Tracks failed paths, records failure reasons and recovery status,
    supports retrying the path after the failure cause is fixed.
    """

    path: str = Field(description="Path name")
    failure_reason: str = Field(description="Failure reason")
    failure_turn: int = Field(default=0, description="Turn when failure occurred")
    recovered: bool = Field(default=False, description="Whether the failure cause has been fixed")
    recovery_checked_at: str = Field(default="", description="Time of last recovery check")


class CrossTurnContamination(BaseModel):
    """Cross-turn contamination record.

    When an error fact is written in a turn, subsequent turns' intermediate results, history summaries,
    user profiles, and key fact tables may all be contaminated, all affected data needs to be tracked.
    """

    error_fact_key: str = Field(description="Key of the error fact")
    introduced_turn: int = Field(description="Turn when the error fact was written")
    affected_results: list[str] = Field(
        default_factory=list, description="Affected intermediate results"
    )
    affected_summaries: list[str] = Field(
        default_factory=list, description="Contaminated history summaries"
    )
    affected_user_profile: list[str] = Field(
        default_factory=list, description="Contaminated user profile fields"
    )
    affected_fact_table: list[str] = Field(
        default_factory=list, description="Contaminated key fact table"
    )


class BacktrackingResult(BaseModel):
    """Backtracking result.

    Records backtracking level, success, rollback position, new plan steps, reused intermediate results,
    and next level info during progressive expansion.
    """

    level: BacktrackingLevel = Field(description="Backtracking level")
    success: bool = Field(default=False, description="Whether backtracking succeeded")
    rollback_to: str = Field(default="", description="Rollback to position (step_id or stage_id)")
    new_plan_steps: list[dict[str, Any]] = Field(
        default_factory=list, description="New plan steps"
    )
    reused_results: list[str] = Field(default_factory=list, description="Reused intermediate results")
    expanded: bool = Field(default=False, description="Whether backtracking scope was expanded")
    next_level: BacktrackingLevel | None = Field(
        default=None, description="Next expanded level"
    )


class JumpRule(BaseModel):
    """Jump backtracking rule.

    Predefined mapping of error patterns to backtracking positions, supports quickly locating backtracking targets,
    avoiding the overhead of progressive expansion.
    """

    error_pattern: str = Field(description="Error pattern description")
    rollback_position: str = Field(description="Backtracking position")
    new_plan_template: str = Field(default="", description="New plan template")
    similarity_threshold: float = Field(
        default=0.8, description="Similarity threshold (for vector retrieval)"
    )

"""TAO / ReAct data models - runtime state loop for step-level execution.

TAO (Think-Action-Observation) complements G4C Plan: the Plan defines the macro
path, while TAO drives each step forward through a controlled state loop.

Five core runtime states are maintained:
- Goal State: final goal, current goal, success criteria (anchor for every Think)
- Action State: records of executed actions (retry/rollback traceability)
- Observation State: structured interpretation of raw action outputs
- Fact State: classified facts (confirmed/user_approved/speculative/rejected/missing)
- Control State: loop limits to prevent runaway execution
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────


class TAOExit(str, Enum):
    """TAO loop exit type.

    Exactly one exit must be taken at the end of each TAO loop round.
    """

    CONTINUE = "continue"
    FINISH = "finish"
    CLARIFY = "clarify"
    RETRY = "retry"
    REPLAN = "replan"
    INTERRUPT = "interrupt"


class ActionType(str, Enum):
    """Action type. An Action is a goal-oriented wrapper, not a raw tool."""

    TOOL_CALL = "tool_call"
    INTERNAL_API = "internal_api"
    USER_INTERACTION = "user_interaction"
    AGGREGATE = "aggregate"


class ActionStatus(str, Enum):
    """Action execution status."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RiskLevel(str, Enum):
    """Risk level of a selected action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InformationGain(str, Enum):
    """Estimated information gain of an action or observation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactCategory(str, Enum):
    """Fact category in Fact State.

    Prevents speculative content from being treated as confirmed fact.
    """

    CONFIRMED = "confirmed"
    USER_APPROVED = "user_approved"
    SPECULATIVE = "speculative"
    REJECTED = "rejected"
    MISSING = "missing"


class ExecutionStatus(str, Enum):
    """Interpreted execution status of an action's raw output."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class InterventionType(str, Enum):
    """Intervention decision produced by the outer supervisor loop."""

    NONE = "none"
    REPLAN = "replan"
    CLARIFY = "clarify"
    INTERRUPT = "interrupt"


# ── Goal State ────────────────────────────────────────────────


class GoalState(BaseModel):
    """Goal State - anchor for every Think round.

    Keeps the final goal and current (stage) goal visible at all times to
    prevent goal drift in long tasks.
    """

    final_goal: str = Field(description="Final user goal, read-only during execution")
    current_goal: str = Field(default="", description="Current stage goal being pursued")
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Verifiable success criteria for the final goal",
    )
    current_goal_completed: bool = Field(
        default=False,
        description="Whether the current stage goal has been completed",
    )


# ── Action State ──────────────────────────────────────────────


class ActionCandidate(BaseModel):
    """A candidate Action in the coarse-filtered candidate space.

    An Action is a goal-oriented wrapper, not a raw tool. Extended metadata
    fields help the coarse filter and Think engine make accurate selections.
    """

    name: str = Field(description="Unique action name, e.g. query_metrics")
    type: ActionType = Field(default=ActionType.TOOL_CALL, description="Action type")
    description: str = Field(default="", description="What this action does")
    params_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected parameter schema (name -> description/type)",
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="Hard preconditions that must hold before execution",
    )
    rollbackable: bool = Field(default=True, description="Whether this action can be rolled back")
    estimated_cost: str = Field(default="low", description="Rough cost estimate: low/medium/high")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra business metadata")

    # Extended metadata for accurate action selection
    applicable_scenarios: list[str] = Field(
        default_factory=list,
        description="Scenarios where this action should be used",
    )
    inapplicable_scenarios: list[str] = Field(
        default_factory=list,
        description="Scenarios where this action must NOT be used",
    )
    required_params: list[str] = Field(default_factory=list, description="Required parameter keys")
    optional_params: list[str] = Field(default_factory=list, description="Optional parameter keys")
    cost: str = Field(default="low", description="Cost estimate: low/medium/high")
    risk: str = Field(default="low", description="Risk level: low/medium/high")
    reversible: bool = Field(default=True, description="Whether the action can be undone")
    permissions: list[str] = Field(
        default_factory=list,
        description="Required permissions or authorization scopes",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for filtering")
    intents: list[str] = Field(
        default_factory=list,
        description="Intents under which this action is applicable",
    )
    repeatable_on_retry: bool = Field(
        default=False,
        description="Whether the action may recover on retry (e.g. network delays)",
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Names of alternative actions that can replace this one",
    )


class ActionRecord(BaseModel):
    """Record of a single executed Action (Action State entry)."""

    action_id: str = Field(
        default_factory=lambda: f"act-{uuid4().hex[:8]}",
        description="Unique action execution ID",
    )
    name: str = Field(description="Action name (from candidate space)")
    type: ActionType = Field(default=ActionType.TOOL_CALL, description="Action type")
    tool_name: str = Field(default="", description="Underlying tool/API name, if any")
    input: dict[str, Any] = Field(default_factory=dict, description="Action input parameters")
    output: Any = Field(default=None, description="Raw action output")
    status: ActionStatus = Field(default=ActionStatus.PENDING, description="Execution status")
    error: str = Field(default="", description="Error message when failed")
    start_time: datetime = Field(default_factory=datetime.utcnow, description="Start time")
    end_time: datetime | None = Field(default=None, description="End time")
    retry_count: int = Field(default=0, description="Number of retries performed")
    rollbackable: bool = Field(default=True, description="Whether this action is rollbackable")

    @property
    def duration_ms(self) -> int | None:
        """Execution duration in milliseconds, None when not finished."""
        if self.end_time is None:
            return None
        return int((self.end_time - self.start_time).total_seconds() * 1000)


class ActionAvailability(BaseModel):
    """Historical availability record for an Action.

    Used to adjust action priority or temporarily mark actions as unavailable.
    """

    name: str = Field(description="Action name")
    total_calls: int = Field(default=0, description="Total execution attempts")
    success_calls: int = Field(default=0, description="Successful executions")
    failed_calls: int = Field(default=0, description="Failed executions")
    last_failure_at: datetime | None = Field(default=None, description="Last failure timestamp")
    last_failure_reason: str = Field(default="", description="Last failure reason")
    consecutive_failures: int = Field(default=0, description="Consecutive failure count")
    disabled: bool = Field(default=False, description="Whether the action is disabled")

    @property
    def success_rate(self) -> float:
        """Historical success rate in range [0, 1]."""
        if self.total_calls == 0:
            return 1.0
        return self.success_calls / self.total_calls


class ActionFilterRule(BaseModel):
    """A rule-engine rule for filtering candidate Actions.

    Rules are evaluated by the coarse filter to include or exclude actions based
    on context predicates (facts, permissions, intent).
    """

    name: str = Field(description="Rule name")
    action_names: list[str] = Field(
        default_factory=list,
        description="Action names this rule applies to; empty means all",
    )
    tags: list[str] = Field(default_factory=list, description="Tags this rule applies to")
    required_facts: list[str] = Field(
        default_factory=list,
        description="Facts that must exist for the action to be included",
    )
    excluded_facts: list[str] = Field(
        default_factory=list,
        description="Facts that, if present, exclude the action",
    )
    required_permissions: list[str] = Field(
        default_factory=list,
        description="Permissions that must be granted",
    )
    intent: str = Field(default="", description="Intent this rule applies to")
    include: bool = Field(default=True, description="True=include if matched, False=exclude")


# ── Observation State ─────────────────────────────────────────


class ObservationFact(BaseModel):
    """A single fact extracted by the Observation interpreter."""

    key: str = Field(description="Fact key")
    value: Any = Field(description="Fact value")
    category: FactCategory = Field(
        default=FactCategory.CONFIRMED,
        description="Fact category; speculative content must be marked as such",
    )
    evidence: str = Field(
        default="",
        description="Evidence source, must point to an action_id, tool output or user input",
    )


class Observation(BaseModel):
    """Structured interpretation of an Action's raw output.

    Code performs simple field/format checks; the LLM performs semantic
    interpretation (fact extraction, evidence binding, gap identification).
    """

    observation_id: str = Field(
        default_factory=lambda: f"obs-{uuid4().hex[:8]}",
        description="Unique observation ID",
    )
    action_id: str = Field(default="", description="ID of the interpreted action")
    execution_status: ExecutionStatus = Field(
        default=ExecutionStatus.SUCCESS,
        description="Interpreted execution status (HTTP 200 != real success)",
    )
    new_facts: list[ObservationFact] = Field(
        default_factory=list,
        description="Newly extracted facts, each bound to evidence",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Information still missing after this action",
    )
    state_changes: list[str] = Field(
        default_factory=list,
        description="Summary of state changes caused by this action",
    )
    anomalies: list[str] = Field(
        default_factory=list,
        description="Detected anomalies, constraint violations or violated assumptions",
    )
    suggested_next_action: str = Field(
        default="",
        description="Suggested next action name (advisory only)",
    )
    progress: bool = Field(default=False, description="Whether real progress was made")
    information_gain: InformationGain = Field(
        default=InformationGain.LOW,
        description="Estimated information gain of this action",
    )
    summary: str = Field(default="", description="Short natural-language summary")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Creation time")


# ── Fact State ────────────────────────────────────────────────


class FactItem(BaseModel):
    """A fact entry in TAO Fact State."""

    key: str = Field(description="Fact key")
    value: Any = Field(default=None, description="Fact value (None for missing slots)")
    category: FactCategory = Field(description="Fact category")
    evidence: str = Field(default="", description="Evidence source (action_id/user_input)")
    source_action_id: str = Field(default="", description="Action that produced this fact")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")


# ── Control State ─────────────────────────────────────────────


class ControlState(BaseModel):
    """Control State - prevents infinite loops and runaway execution."""

    max_loops: int = Field(default=10, description="Maximum TAO loop rounds")
    used_loops: int = Field(default=0, description="Loop rounds used so far")
    max_time: float = Field(default=300.0, description="Maximum execution time in seconds")
    start_time: datetime = Field(default_factory=datetime.utcnow, description="Loop start time")
    exit_reason: str = Field(default="", description="Reason recorded when exiting")
    max_action_retries: int = Field(default=2, description="Max retries per action")

    def loops_exceeded(self) -> bool:
        """Whether the maximum loop count has been reached."""
        return self.used_loops >= self.max_loops

    def time_exceeded(self) -> bool:
        """Whether the maximum execution time has been exceeded."""
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        return elapsed >= self.max_time


# ── TAO State (aggregate) ─────────────────────────────────────


class TAOState(BaseModel):
    """Aggregate TAO runtime state - the single object carried across loop rounds."""

    goal_state: GoalState = Field(description="Goal State")
    actions: list[ActionRecord] = Field(
        default_factory=list,
        description="Action State: executed action records in order",
    )
    observations: list[Observation] = Field(
        default_factory=list,
        description="Observation State: structured interpretations in order",
    )
    facts: dict[str, FactItem] = Field(
        default_factory=dict,
        description="Fact State: key -> fact item",
    )
    control: ControlState = Field(default_factory=ControlState, description="Control State")
    plan_step_id: str = Field(default="", description="Associated Plan step ID, if any")
    candidate_actions: list[ActionCandidate] = Field(
        default_factory=list,
        description="Coarse-filtered candidate action space for this run",
    )

    def last_action(self) -> ActionRecord | None:
        """Return the most recent action record, or None."""
        return self.actions[-1] if self.actions else None

    def last_observation(self) -> Observation | None:
        """Return the most recent observation, or None."""
        return self.observations[-1] if self.observations else None

    def facts_by_category(self, category: FactCategory) -> list[FactItem]:
        """Return facts of the given category."""
        return [f for f in self.facts.values() if f.category == category]

    def missing_slots(self) -> list[str]:
        """Return keys of facts currently marked as missing."""
        return [f.key for f in self.facts.values() if f.category == FactCategory.MISSING]


# ── Think Result ──────────────────────────────────────────────


class ThinkResult(BaseModel):
    """Structured output of the Think phase (five judgments).

    Five judgments:
    1. Goal judgment: current_goal, success_criteria_satisfied, current_goal_completed
    2. State judgment: facts_sufficient, missing_slots, unverified_assumptions, fact_conflicts
    3. Path judgment: selected_action, action_params, reason (evidence-based)
    4. Stop judgment: should_stop, exit_decision
    5. Risk judgment: risk_level, risk_reason
    """

    current_goal: str = Field(default="", description="Goal being pursued this round")
    success_criteria_satisfied: bool = Field(
        default=False,
        description="Whether final success criteria are satisfied",
    )
    current_goal_completed: bool = Field(
        default=False,
        description="Whether the current stage goal is completed",
    )
    facts_sufficient: bool = Field(default=False, description="Whether known facts are sufficient")
    missing_slots: list[str] = Field(default_factory=list, description="Missing fact slots")
    unverified_assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions not yet verified",
    )
    fact_conflicts: list[str] = Field(default_factory=list, description="Detected fact conflicts")
    selected_action: str = Field(default="", description="Selected action name from candidates")
    action_params: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    should_stop: bool = Field(default=False, description="Whether the loop should stop")
    exit_decision: TAOExit = Field(
        default=TAOExit.CONTINUE,
        description="Exit decision for this round",
    )
    reason: str = Field(
        default="",
        description="Evidence-based reason for the selection, must reference Goal/Context/Constraint",
    )
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Risk level of selected action")
    risk_reason: str = Field(default="", description="Extaoation when risk_level is not low")
    raw_response: str = Field(default="", description="Raw LLM response text (for debugging)")


# ── Exit Record ───────────────────────────────────────────────


class TAOExitRecord(BaseModel):
    """Structured record of a single loop exit decision."""

    exit_type: TAOExit = Field(description="Exit type taken")
    reason: str = Field(default="", description="Why this exit was chosen")
    used_loops: int = Field(default=0, description="Loop rounds used at exit time")
    action_id: str = Field(default="", description="Action executed in this round, if any")
    observation_summary: str = Field(default="", description="Short observation summary")
    overridden: bool = Field(
        default=False,
        description="Whether the LLM's exit_decision was overridden by code rules",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Decision time")


# ── Supervisor (outer loop) ───────────────────────────────────


class SupervisorReview(BaseModel):
    """Result of one outer-loop supervision review."""

    goal_drift: bool = Field(default=False, description="Whether goal drift was detected")
    drift_extaoation: str = Field(default="", description="Extaoation of detected drift")
    constraint_violations: list[str] = Field(
        default_factory=list,
        description="Detected hard/soft constraint violations",
    )
    stagnation: bool = Field(default=False, description="Whether long-term progress stalled")
    intervention: InterventionType = Field(
        default=InterventionType.NONE,
        description="Recommended intervention",
    )
    reason: str = Field(default="", description="Evidence-based reason for the review result")
    raw_response: str = Field(default="", description="Raw LLM response text (for debugging)")


# ── Final TAO Result ──────────────────────────────────────────


class TAOResult(BaseModel):
    """Final result of a complete TAO run."""

    exit_type: TAOExit = Field(description="Final exit type")
    final_output: str = Field(default="", description="Final output text (when finish)")
    clarify_message: str = Field(default="", description="Question to the user (when clarify)")
    exit_reason: str = Field(default="", description="Exit reason detail")
    used_loops: int = Field(default=0, description="Total loop rounds used")
    total_actions: int = Field(default=0, description="Total actions executed")
    exit_history: list[TAOExitRecord] = Field(
        default_factory=list,
        description="Exit decision record of every round",
    )
    state: TAOState | None = Field(default=None, description="Final TAO state snapshot")

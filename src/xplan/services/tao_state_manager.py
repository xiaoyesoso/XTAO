"""TAO state manager - initializes and maintains the five TAO runtime states.

Responsibilities:
- Initialize TAOState from user input and Plan
- Maintain Goal/Action/Observation/Fact/Control states
- Bridge TAO Fact State with TrustStateManager (cascade marking reuse)
"""

import logging
from datetime import datetime
from typing import Any

from xplan.models.plan import Plan
from xplan.models.tao import (
    ActionCandidate,
    ActionRecord,
    ControlState,
    FactCategory,
    FactItem,
    GoalState,
    Observation,
    TAOState,
)
from xplan.models.trust_state import TrustState
from xplan.services.trust_state_manager import TrustStateManager

logger = logging.getLogger(__name__)


class TAOStateManager:
    """Manages the five TAO runtime states.

    Attributes:
        trust_state_manager: Optional TrustStateManager for trust-state reuse
            and cascade marking of invalidated facts.
    """

    def __init__(self, trust_state_manager: TrustStateManager | None = None) -> None:
        """Initialize the TAO state manager.

        Args:
            trust_state_manager: Optional shared TrustStateManager. When provided,
                facts extracted by Observation are mirrored into it and INVALID
                marks cascade to dependent facts automatically.
        """
        self.trust_state_manager = trust_state_manager

    # ── Initialization (task 2.1) ─────────────────────────────

    def initialize(
        self,
        user_input: str,
        plan: Plan | None = None,
        candidate_actions: list[ActionCandidate] | None = None,
        max_loops: int = 10,
        max_time: float = 300.0,
        max_action_retries: int = 2,
    ) -> TAOState:
        """Initialize the full TAO state from user input and an optional Plan.

        Args:
            user_input: User's goal/request text
            plan: Optional G4C Plan; goal/criteria/step info is mapped into TAO state
            candidate_actions: Coarse-filtered candidate action space
            max_loops: Maximum loop rounds
            max_time: Maximum execution time in seconds
            max_action_retries: Max retries per action

        Returns:
            Initialized TAOState
        """
        final_goal = user_input
        success_criteria: list[str] = []
        current_goal = user_input
        plan_step_id = ""

        if plan is not None:
            if plan.goal is not None:
                final_goal = plan.goal.user_goal or user_input
                success_criteria = list(plan.goal.success_criteria)
            if plan.choice is not None and plan.choice.steps:
                current_step = plan.choice.steps[min(plan.current_step_index, len(plan.choice.steps) - 1)]
                current_goal = current_step.objective
                plan_step_id = current_step.id

        state = TAOState(
            goal_state=GoalState(
                final_goal=final_goal,
                current_goal=current_goal,
                success_criteria=success_criteria,
            ),
            control=ControlState(
                max_loops=max_loops,
                max_time=max_time,
                max_action_retries=max_action_retries,
            ),
            plan_step_id=plan_step_id,
            candidate_actions=list(candidate_actions) if candidate_actions else [],
        )

        # Seed Fact State from Plan context (known facts confirmed, missing info as missing)
        if plan is not None and plan.context is not None:
            for fact in plan.context.known_facts:
                key = self._normalize_key(fact)
                state.facts[key] = FactItem(
                    key=key,
                    value=fact,
                    category=FactCategory.CONFIRMED,
                    evidence="plan.context.known_facts",
                )
            for missing in plan.context.missing_info:
                key = self._normalize_key(missing)
                state.facts[key] = FactItem(
                    key=key,
                    value=None,
                    category=FactCategory.MISSING,
                    evidence="plan.context.missing_info",
                )

        logger.info(
            "Initialized TAO state: final_goal=%s, candidates=%d",
            final_goal[:50],
            len(state.candidate_actions),
        )
        return state

    # ── Goal State (task 2.2) ─────────────────────────────────

    def update_current_goal(self, state: TAOState, current_goal: str) -> None:
        """Update the current stage goal (final goal stays read-only).

        Args:
            state: TAO state to mutate
            current_goal: New stage goal
        """
        state.goal_state.current_goal = current_goal
        state.goal_state.current_goal_completed = False

    def mark_current_goal_completed(self, state: TAOState) -> None:
        """Mark the current stage goal as completed."""
        state.goal_state.current_goal_completed = True

    # ── Action State (task 2.3) ───────────────────────────────

    def record_action(self, state: TAOState, record: ActionRecord) -> None:
        """Append an action record to Action State."""
        state.actions.append(record)

    def get_action(self, state: TAOState, action_id: str) -> ActionRecord | None:
        """Find an action record by ID."""
        for record in state.actions:
            if record.action_id == action_id:
                return record
        return None

    def increment_retry(self, record: ActionRecord) -> None:
        """Increment the retry counter of an action record."""
        record.retry_count += 1

    # ── Observation State (task 2.4) ──────────────────────────

    def record_observation(self, state: TAOState, observation: Observation) -> None:
        """Append an observation to Observation State."""
        state.observations.append(observation)

    # ── Fact State (task 2.5) ─────────────────────────────────

    def upsert_fact(
        self,
        state: TAOState,
        key: str,
        value: Any,
        category: FactCategory,
        evidence: str = "",
        source_action_id: str = "",
    ) -> FactItem:
        """Insert or update a fact in Fact State.

        When a missing slot is filled, its category is upgraded. Speculative
        facts are never auto-upgraded to confirmed without new evidence.

        Args:
            state: TAO state to mutate
            key: Fact key
            value: Fact value
            category: Fact category
            evidence: Evidence source (action_id / user_input)
            source_action_id: Action that produced this fact

        Returns:
            The upserted FactItem
        """
        item = FactItem(
            key=key,
            value=value,
            category=category,
            evidence=evidence,
            source_action_id=source_action_id,
            updated_at=datetime.utcnow(),
        )
        state.facts[key] = item
        return item

    def apply_observation_facts(self, state: TAOState, observation: Observation) -> None:
        """Write facts extracted by an Observation into Fact State.

        Also mirrors them into TrustStateManager when available (task 2.7).

        Args:
            state: TAO state to mutate
            observation: Observation containing new facts
        """
        for obs_fact in observation.new_facts:
            self.upsert_fact(
                state,
                key=obs_fact.key,
                value=obs_fact.value,
                category=obs_fact.category,
                evidence=obs_fact.evidence or observation.action_id,
                source_action_id=observation.action_id,
            )
            if self.trust_state_manager is not None:
                try:
                    self.trust_state_manager.add_fact(
                        key=obs_fact.key,
                        value=obs_fact.value,
                        evidence=obs_fact.evidence or observation.action_id,
                        source_step_id=state.plan_step_id,
                    )
                except Exception as e:  # pragma: no cover - defensive
                    logger.warning("Failed to mirror fact %s into TrustStateManager: %s", obs_fact.key, e)

        # Remove facts from missing list once they arrive
        for obs_fact in observation.new_facts:
            existing = state.facts.get(obs_fact.key)
            if existing is not None and existing.category != FactCategory.MISSING:
                continue

    # ── Control State (task 2.6) ──────────────────────────────

    def increment_loop(self, state: TAOState) -> None:
        """Increment the used loop counter."""
        state.control.used_loops += 1

    def set_exit_reason(self, state: TAOState, reason: str) -> None:
        """Record the exit reason in Control State."""
        state.control.exit_reason = reason

    # ── Trust state integration (task 2.7) ────────────────────

    def mark_fact_invalid(self, key: str, reason: str = "") -> None:
        """Mark a fact as INVALID in TrustStateManager, cascading DIRTY marks.

        Args:
            key: Fact key
            reason: Invalidation reason
        """
        if self.trust_state_manager is None:
            return
        try:
            changes = self.trust_state_manager.update_trust_state(
                key, TrustState.INVALID, reason
            )
            logger.info("Marked fact %s INVALID, %d cascaded changes", key, len(changes) - 1)
        except KeyError:
            logger.warning("Fact %s not found in TrustStateManager", key)

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _normalize_key(text: str) -> str:
        """Normalize free text into a compact fact key."""
        key = text.strip().lower().replace(" ", "_")
        return key[:80]

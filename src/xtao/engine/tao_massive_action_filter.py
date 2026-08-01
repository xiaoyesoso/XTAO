"""Massive Action filter - multi-stage candidate space reduction.

When the total action library is large (hundreds or thousands), passing every
action to the Think prompt hurts accuracy and token budget. This module provides
a deterministic pipeline that progressively narrows the candidate space:

    all actions -> intent/tag/rules -> preconditions/permissions -> success rate
    -> information gain -> LLM coarse filter -> LLM fine selection

The pipeline supports short-circuiting: when a stage already reduces the
candidate count below a threshold, later stages can be skipped.
"""

import logging
from typing import Any, Awaitable, Callable

from xtao.models.tao import (
    ActionAvailability,
    ActionCandidate,
    ActionFilterRule,
    InformationGain,
    TAOState,
)

logger = logging.getLogger(__name__)

# Type alias for an async LLM filter: (user_input, goal, candidates, target_count) -> candidates
LLMFilter = Callable[[str, str, list[ActionCandidate], int], Awaitable[list[ActionCandidate]]]


class MassiveActionFilter:
    """Pipeline filter for reducing a large action library to a small candidate space.

    Attributes:
        availability: Mapping from action name to availability record
        rules: Declarative filter rules
        embedding_filter: Optional async filter based on vector similarity
        llm_coarse_filter: Optional async LLM-based coarse filter
        short_circuit_threshold: When candidates drop to this count or lower,
            skip remaining deterministic stages and go straight to LLM fine selection
    """

    def __init__(
        self,
        availability: dict[str, ActionAvailability] | None = None,
        rules: list[ActionFilterRule] | None = None,
        embedding_filter: LLMFilter | None = None,
        llm_coarse_filter: LLMFilter | None = None,
        short_circuit_threshold: int = 10,
    ) -> None:
        """Initialize the massive action filter.

        Args:
            availability: Historical availability records for success-rate ranking
            rules: Declarative filter rules
            embedding_filter: Optional vector-recall filter
            llm_coarse_filter: Optional LLM coarse filter
            short_circuit_threshold: Candidate count at which to short-circuit
        """
        self.availability = availability or {}
        self.rules = rules or []
        self.embedding_filter = embedding_filter
        self.llm_coarse_filter = llm_coarse_filter
        self.short_circuit_threshold = short_circuit_threshold

    # ── Deterministic filters ─────────────────────────────────

    def filter_by_intent(
        self, candidates: list[ActionCandidate], intent: str
    ) -> list[ActionCandidate]:
        """Return actions whose intents include the given intent.

        An action with no intents is treated as intent-agnostic and kept.
        """
        if not intent:
            return candidates
        return [c for c in candidates if not c.intents or intent in c.intents]

    def filter_by_tags(
        self, candidates: list[ActionCandidate], tags: list[str]
    ) -> list[ActionCandidate]:
        """Return actions that contain all requested tags."""
        if not tags:
            return candidates
        required = set(tags)
        return [c for c in candidates if required.issubset(set(c.tags))]

    def filter_by_rules(
        self,
        candidates: list[ActionCandidate],
        intent: str,
        available_facts: set[str],
        context: dict[str, Any],
    ) -> list[ActionCandidate]:
        """Apply declarative ActionFilterRule objects."""
        if not self.rules:
            return candidates

        def _match(rule: ActionFilterRule, candidate: ActionCandidate) -> bool:
            matched = False
            if rule.action_names and candidate.name in rule.action_names:
                matched = True
            if not matched and rule.tags and set(rule.tags).intersection(set(candidate.tags)):
                matched = True
            if not matched and rule.intent and rule.intent == intent:
                matched = True
            if not matched:
                return True  # rule does not apply, keep candidate

            if rule.required_facts and not all(f in available_facts for f in rule.required_facts):
                return False
            if rule.excluded_facts and any(f in available_facts for f in rule.excluded_facts):
                return False
            if rule.required_permissions:
                granted = set(context.get("granted_permissions", []))
                if not set(rule.required_permissions).issubset(granted):
                    return False
            return rule.include

        return [c for c in candidates if all(_match(rule, c) for rule in self.rules)]

    def filter_by_missing_slots(
        self,
        candidates: list[ActionCandidate],
        state: TAOState | None,
        context: dict[str, Any] | None = None,
    ) -> list[ActionCandidate]:
        """Exclude actions whose required_params are unavailable."""
        if state is None:
            return candidates
        available_facts = {
            f.key
            for f in state.facts.values()
            if f.category.value in ("confirmed", "user_approved")
        }
        ctx = context or {}
        provided = set(available_facts)
        provided.update(ctx.keys())
        return [
            c
            for c in candidates
            if not c.required_params or all(p in provided for p in c.required_params)
        ]

    def filter_by_permissions(
        self,
        candidates: list[ActionCandidate],
        granted_permissions: list[str] | None,
    ) -> list[ActionCandidate]:
        """Exclude actions requiring permissions the user does not have."""
        if not granted_permissions:
            # When no permission list is provided, keep actions that require no permissions
            return [c for c in candidates if not c.permissions]
        granted = set(granted_permissions)
        return [
            c
            for c in candidates
            if not c.permissions or set(c.permissions).issubset(granted)
        ]

    def filter_disabled(
        self, candidates: list[ActionCandidate]
    ) -> list[ActionCandidate]:
        """Exclude actions that are disabled by the circuit breaker."""
        return [
            c
            for c in candidates
            if not self.availability.get(c.name) or not self.availability[c.name].disabled
        ]

    def rank_by_success_rate(
        self, candidates: list[ActionCandidate]
    ) -> list[ActionCandidate]:
        """Sort candidates by historical success rate (descending)."""

        def _score(candidate: ActionCandidate) -> float:
            av = self.availability.get(candidate.name)
            if av is None:
                return 1.0
            return av.success_rate

        return sorted(candidates, key=_score, reverse=True)

    def rank_by_information_gain(
        self,
        candidates: list[ActionCandidate],
        missing_slots: list[str],
    ) -> list[ActionCandidate]:
        """Rank actions that are likely to fill missing slots higher.

        This is a lightweight heuristic: actions whose description or applicable
        scenarios mention missing slot keys are boosted to the top.
        """
        if not missing_slots:
            return candidates
        missing_set = set(missing_slots)

        def _gain_score(candidate: ActionCandidate) -> int:
            text = " ".join(
                [
                    candidate.description,
                    " ".join(candidate.applicable_scenarios),
                    " ".join(candidate.inapplicable_scenarios),
                    " ".join(candidate.required_params),
                ]
            ).lower()
            return sum(1 for slot in missing_set if slot.lower() in text)

        return sorted(candidates, key=_gain_score, reverse=True)

    # ── Async filters ─────────────────────────────────────────

    async def vector_recall_filter(
        self,
        query: str,
        candidates: list[ActionCandidate],
        target_count: int = 20,
    ) -> list[ActionCandidate]:
        """Recall the most relevant actions using an embedding-based filter.

        If no embedding_filter is configured, falls back to keyword overlap.
        """
        if self.embedding_filter is not None:
            return await self.embedding_filter(query, "", candidates, target_count)

        # Fallback: simple keyword overlap score
        query_tokens = set(query.lower().split())

        def _score(candidate: ActionCandidate) -> int:
            text = " ".join(
                [
                    candidate.name,
                    candidate.description,
                    " ".join(candidate.applicable_scenarios),
                    " ".join(candidate.tags),
                    " ".join(candidate.intents),
                ]
            ).lower()
            tokens = set(text.split())
            return len(query_tokens.intersection(tokens))

        ranked = sorted(candidates, key=_score, reverse=True)
        return ranked[:target_count]

    async def llm_coarse_filter(
        self,
        user_input: str,
        goal: str,
        candidates: list[ActionCandidate],
        target_count: int = 10,
    ) -> list[ActionCandidate]:
        """Use a fast LLM call to pick the most relevant actions.

        If no llm_coarse_filter is configured, returns the top target_count
        candidates based on keyword overlap with the user input and goal.
        """
        if self.llm_coarse_filter is not None:
            return await self.llm_coarse_filter(user_input, goal, candidates, target_count)

        query = f"{user_input} {goal}".lower()
        query_tokens = set(query.split())

        def _score(candidate: ActionCandidate) -> int:
            text = " ".join(
                [
                    candidate.name,
                    candidate.description,
                    " ".join(candidate.applicable_scenarios),
                    " ".join(candidate.tags),
                    " ".join(candidate.intents),
                ]
            ).lower()
            tokens = set(text.split())
            return len(query_tokens.intersection(tokens))

        ranked = sorted(candidates, key=_score, reverse=True)
        return ranked[:target_count]

    # ── Pipeline ──────────────────────────────────────────────

    async def filter(
        self,
        candidates: list[ActionCandidate],
        state: TAOState | None = None,
        user_input: str = "",
        goal: str = "",
        intent: str = "",
        tags: list[str] | None = None,
        granted_permissions: list[str] | None = None,
        context: dict[str, Any] | None = None,
        target_count: int = 10,
        use_llm_coarse: bool = False,
        use_vector_recall: bool = False,
    ) -> list[ActionCandidate]:
        """Run the full filtering pipeline and return the final candidate space.

        Args:
            candidates: Full action library
            state: Current TAO state
            user_input: Original user input
            goal: Final goal text
            intent: Current intent
            tags: Required tags
            granted_permissions: Permissions granted to the user
            context: Free-form context for rules
            target_count: Desired number of final candidates
            use_llm_coarse: Whether to run the LLM coarse filter stage
            use_vector_recall: Whether to run vector recall before LLM filtering

        Returns:
            Filtered and ranked candidate list ready for the Think engine
        """
        remaining = list(candidates)
        ctx = context or {}
        missing_slots = state.missing_slots() if state is not None else []
        available_facts: set[str] = set()
        if state is not None:
            available_facts = {
                f.key
                for f in state.facts.values()
                if f.category.value in ("confirmed", "user_approved")
            }

        # Stage 1: deterministic filters (all run, they are cheap and safe)
        remaining = self.filter_disabled(remaining)
        remaining = self.filter_by_intent(remaining, intent)
        remaining = self.filter_by_tags(remaining, tags or [])
        remaining = self.filter_by_rules(remaining, intent, available_facts, ctx)
        remaining = self.filter_by_missing_slots(remaining, state, ctx)
        remaining = self.filter_by_permissions(remaining, granted_permissions)

        # Short-circuit: if the deterministic pipeline already produced a small
        # enough candidate space, skip further ranking / LLM filtering.
        if len(remaining) <= self.short_circuit_threshold:
            return self.rank_by_success_rate(remaining)

        # Stage 2: ranking
        remaining = self.rank_by_information_gain(remaining, missing_slots)
        remaining = self.rank_by_success_rate(remaining)

        # Stage 3: vector recall (optional)
        if use_vector_recall:
            query = user_input or goal or " ".join(missing_slots)
            remaining = await self.vector_recall_filter(query, remaining, target_count * 2)
            if len(remaining) <= self.short_circuit_threshold:
                return remaining

        # Stage 4: LLM coarse filter (optional)
        if use_llm_coarse:
            remaining = await self.llm_coarse_filter(
                user_input, goal, remaining, target_count
            )

        return remaining[:target_count]

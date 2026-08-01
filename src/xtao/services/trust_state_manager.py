"""Trust state management service - Manages trust state of intermediate results, cascade marking, and evidence chain tracing.

Core capabilities:
- Mark trust state for each intermediate result (VERIFIED/AVAILABLE/SUSPICIOUS/INVALID/DIRTY)
- When a fact is marked as INVALID, automatically cascade mark all facts depending on it as DIRTY (BFS traversal, pure code implementation)
- Build evidence chains for LLM to trace root causes from state changes
- Generate injectable fact lists for Prompts (including trust state and evidence)

Design principles:
- Cascade marking uses code implementation (BFS traversal of dependency chain), does not depend on LLM
- When backtracking, prioritize checking SUSPICIOUS and DIRTY facts, skip VERIFIED facts
"""

import logging
from collections import deque
from typing import Any

from xtao.models.trust_state import (
    FactEntry,
    TrustState,
    TrustStateChange,
    TrustStateReport,
)

logger = logging.getLogger(__name__)


class TrustStateManager:
    """Trust state manager, manages trust state of intermediate results.

    Supports cascade marking (BFS traversal of dependency chain) and evidence chain tracing.

    Attributes:
        _facts: Internal fact storage, key is fact key, value is FactEntry
    """

    def __init__(self) -> None:
        """Initialize trust state manager, fact storage is empty."""
        self._facts: dict[str, FactEntry] = {}

    def add_fact(
        self,
        key: str,
        value: Any,
        evidence: str = "",
        source_step_id: str = "",
        depends_on: list[str] | None = None,
    ) -> FactEntry:
        """Add a fact entry, default state is AVAILABLE.

        If key already exists, overwrites the existing entry.

        Args:
            key: Fact key, e.g. highest_qps
            value: Fact value
            evidence: Evidence source
            source_step_id: ID of the step that produced this fact
            depends_on: List of other fact keys this fact depends on

        Returns:
            The newly created fact entry
        """
        entry = FactEntry(
            key=key,
            value=value,
            trust_state=TrustState.AVAILABLE,
            evidence=evidence,
            source_step_id=source_step_id,
            depends_on=list(depends_on) if depends_on else [],
        )
        self._facts[key] = entry
        logger.info("Added fact: %s", key)
        return entry

    def get_fact(self, key: str) -> FactEntry | None:
        """Get a fact entry.

        Args:
            key: Fact key

        Returns:
            Fact entry, returns None if not found
        """
        return self._facts.get(key)

    def get_all_facts(self) -> list[FactEntry]:
        """Get all fact entries.

        Returns:
            List of all fact entries
        """
        return list(self._facts.values())

    def update_trust_state(
        self,
        key: str,
        new_state: TrustState,
        reason: str = "",
    ) -> list[TrustStateChange]:
        """Update the trust state of a fact.

        - If the new state is INVALID, automatically triggers cascade marking
        - Returns all change records (including cascade marking)

        Args:
            key: Fact key
            new_state: New trust state
            reason: Change reason

        Returns:
            List of all change records (including cascade marking)

        Raises:
            KeyError: When the fact key does not exist
        """
        fact = self._facts.get(key)
        if fact is None:
            raise KeyError(f"Fact does not exist: {key}")

        # When new state is INVALID, trigger cascade marking (including key's own INVALID mark)
        if new_state == TrustState.INVALID:
            return self.cascade_mark_dirty(key, reason)

        # For non-INVALID states, only update the single fact
        old_state = fact.trust_state
        if old_state == new_state:
            return []

        fact.trust_state = new_state
        change = TrustStateChange(
            key=key,
            old_state=old_state,
            new_state=new_state,
            reason=reason,
            cascaded=False,
        )
        logger.info(
            "Updated fact trust state: %s, %s -> %s",
            key,
            old_state.value,
            new_state.value,
        )
        return [change]

    def cascade_mark_dirty(
        self,
        key: str,
        reason: str = "",
    ) -> list[TrustStateChange]:
        """Cascade marking. Marks key as INVALID, then traverses all facts depending on key and marks them as DIRTY.

        Uses BFS to traverse the dependency chain:
        - First marks key as INVALID (skips if already INVALID)
        - Traverses all facts whose depends_on contains key, marks them as DIRTY
        - Continues traversing facts depending on these DIRTY facts, and so on
        - Facts already INVALID or DIRTY are not re-marked

        Cascade marking uses code implementation, does not depend on LLM.

        Args:
            key: Starting fact key
            reason: Change reason

        Returns:
            List of all change records (including key's own INVALID mark and cascaded DIRTY marks)

        Raises:
            KeyError: When the fact key does not exist
        """
        fact = self._facts.get(key)
        if fact is None:
            raise KeyError(f"Fact does not exist: {key}")

        changes: list[TrustStateChange] = []

        # Step 1: Mark key as INVALID
        if fact.trust_state != TrustState.INVALID:
            old_state = fact.trust_state
            fact.trust_state = TrustState.INVALID
            changes.append(
                TrustStateChange(
                    key=key,
                    old_state=old_state,
                    new_state=TrustState.INVALID,
                    reason=reason,
                    cascaded=False,
                )
            )
            logger.info(
                "Cascade marking start: %s, %s -> INVALID",
                key,
                old_state.value,
            )

        # Step 2: BFS traverse dependency chain, mark dependent nodes as DIRTY
        queue: deque[str] = deque([key])
        visited: set[str] = {key}
        while queue:
            current_key = queue.popleft()
            # Find all facts depending on current_key
            for f_key, f in self._facts.items():
                if current_key in f.depends_on and f_key not in visited:
                    visited.add(f_key)
                    # Facts already INVALID or DIRTY are not re-marked
                    if f.trust_state not in (TrustState.INVALID, TrustState.DIRTY):
                        old_state = f.trust_state
                        f.trust_state = TrustState.DIRTY
                        changes.append(
                            TrustStateChange(
                                key=f_key,
                                old_state=old_state,
                                new_state=TrustState.DIRTY,
                                reason=f"Dependent fact {current_key} has been invalidated",
                                cascaded=True,
                            )
                        )
                        logger.info(
                            "Cascade marking DIRTY: %s, %s -> DIRTY (depends on %s)",
                            f_key,
                            old_state.value,
                            current_key,
                        )
                    # Whether marked or not, continue traversing downstream to ensure the entire chain is covered
                    queue.append(f_key)

        return changes

    def get_facts_by_state(self, state: TrustState) -> list[FactEntry]:
        """Get all facts of the specified state.

        Args:
            state: Trust state

        Returns:
            List of fact entries matching the state
        """
        return [f for f in self._facts.values() if f.trust_state == state]

    def get_suspicious_and_dirty(self) -> list[FactEntry]:
        """Get facts in Suspicious and Dirty states.

        Prioritize checking these facts when backtracking to locate root causes.

        Returns:
            List of fact entries in Suspicious and Dirty states
        """
        return [
            f
            for f in self._facts.values()
            if f.trust_state in (TrustState.SUSPICIOUS, TrustState.DIRTY)
        ]

    def get_verified(self) -> list[FactEntry]:
        """Get facts in Verified state.

        Skip these verified facts when backtracking.

        Returns:
            List of fact entries in Verified state
        """
        return [
            f
            for f in self._facts.values()
            if f.trust_state == TrustState.VERIFIED
        ]

    def get_report(self) -> TrustStateReport:
        """Generate trust state report, including count statistics for each state.

        Returns:
            Trust state report
        """
        facts = list(self._facts.values())
        counts = {
            TrustState.VERIFIED: 0,
            TrustState.AVAILABLE: 0,
            TrustState.SUSPICIOUS: 0,
            TrustState.INVALID: 0,
            TrustState.DIRTY: 0,
        }
        for f in facts:
            counts[f.trust_state] += 1

        return TrustStateReport(
            facts=facts,
            changes=[],  # The report itself does not carry historical changes, supplemented by caller as needed
            verified_count=counts[TrustState.VERIFIED],
            available_count=counts[TrustState.AVAILABLE],
            suspicious_count=counts[TrustState.SUSPICIOUS],
            invalid_count=counts[TrustState.INVALID],
            dirty_count=counts[TrustState.DIRTY],
        )

    def build_evidence_chain(self, key: str) -> list[FactEntry]:
        """Build evidence chain. Starting from key, traces all dependent facts backwards along depends_on.

        Used when a data state changes, so the LLM can find the root cause from the evidence chain.

        Traversal order is BFS: first visits key itself, then its direct dependencies, and so on.

        Args:
            key: Starting fact key

        Returns:
            List of fact entries on the evidence chain (including key itself and all its upstream dependencies)
        """
        result: list[FactEntry] = []
        visited: set[str] = set()
        queue: deque[str] = deque()

        if key not in self._facts:
            return result

        queue.append(key)
        visited.add(key)
        while queue:
            current_key = queue.popleft()
            fact = self._facts.get(current_key)
            if fact is None:
                continue
            result.append(fact)
            for dep in fact.depends_on:
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        return result

    def get_facts_for_prompt(self) -> str:
        """Generate a fact list for Prompt injection (including trust state and evidence).

        Format example:
        ```
        highest_qps: 10万, Available, evidence: query_result
        项目亮点: 高并发10万, Available, based: highest_qps
        ```

        Returns:
            Fact list text that can be injected into a Prompt
        """
        lines: list[str] = []
        for fact in self._facts.values():
            parts: list[str] = [
                f"{fact.key}: {fact.value}",
                fact.trust_state.value.capitalize(),
            ]
            if fact.evidence:
                parts.append(f"evidence: {fact.evidence}")
            if fact.depends_on:
                parts.append(f"based: {', '.join(fact.depends_on)}")
            lines.append(", ".join(parts))
        return "\n".join(lines)

    def clear_invalid_and_dirty(self) -> int:
        """Clear all facts in INVALID and DIRTY states.

        Returns:
            Number of facts cleared
        """
        keys_to_remove = [
            k
            for k, f in self._facts.items()
            if f.trust_state in (TrustState.INVALID, TrustState.DIRTY)
        ]
        for k in keys_to_remove:
            del self._facts[k]
        if keys_to_remove:
            logger.info("Cleared %d INVALID/DIRTY facts", len(keys_to_remove))
        return len(keys_to_remove)

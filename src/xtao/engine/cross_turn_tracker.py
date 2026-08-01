"""Cross-turn tracker - Track cross-turn error fact contamination.

When a turn writes an error fact, subsequent turns' intermediate results, historical summaries,
user profiles, and key fact tables may all be contaminated. The cross-turn tracker is responsible for:
- Recording the turn when a fact was written
- Finding the earliest location where an error fact was written
- Identifying contaminated intermediate results, historical summaries, etc.
- Building cross-turn contamination report
"""

import logging
from typing import Any

from xtao.models.backtracking import CrossTurnContamination

logger = logging.getLogger(__name__)


class CrossTurnTracker:
    """Cross-turn tracker.

    Tracks cross-turn error fact contamination, builds contamination report for cross-turn Replan.

    Attributes:
        _fact_sources: Fact source records, key -> [(turn, value)]
    """

    def __init__(self) -> None:
        """Initialize the cross-turn tracker."""
        self._fact_sources: dict[str, list[tuple[int, str]]] = {}

    def record_fact_introduction(
        self, key: str, value: str, turn: int
    ) -> None:
        """Record the turn when a fact was written.

        The same key may be written with different values in multiple turns;
        all are recorded for traceability.

        Args:
            key: Fact key
            value: Fact value
            turn: Turn when written
        """
        if key not in self._fact_sources:
            self._fact_sources[key] = []
        self._fact_sources[key].append((turn, value))
        logger.info("Recorded fact write: key=%s, turn=%d", key, turn)

    def find_error_origin(self, key: str, wrong_value: str) -> int | None:
        """Find the earliest turn where an error fact was written.

        Args:
            key: Fact key
            wrong_value: Wrong value

        Returns:
            Earliest turn where the wrong value was written, or None if not found
        """
        sources = self._fact_sources.get(key, [])
        for turn, value in sources:
            if value == wrong_value:
                return turn
        return None

    def find_affected_results(
        self, key: str, all_facts: dict[str, Any]
    ) -> list[str]:
        """Find all intermediate results that depend on the error fact.

        Simplified implementation: check whether other facts' values reference the error fact's key.

        Args:
            key: Error fact key
            all_facts: All facts dict

        Returns:
            List of affected intermediate result keys
        """
        affected = []
        for fact_key, fact_value in all_facts.items():
            if fact_key == key:
                continue
            # Check whether fact value references the error fact's key
            value_str = str(fact_value)
            if key in value_str:
                affected.append(fact_key)
        return affected

    def find_affected_summaries(
        self, key: str, summaries: list[dict]
    ) -> list[str]:
        """Find contaminated historical summaries.

        Check whether each summary's content references the error fact's key.

        Args:
            key: Error fact key
            summaries: Historical summary list, each summary is a dict (containing content and other fields)

        Returns:
            List of contaminated summary identifiers
        """
        affected = []
        for summary in summaries:
            # Check whether all string values of the summary reference the error fact's key
            for value in summary.values():
                value_str = str(value)
                if key in value_str:
                    # Use the summary's id or content as identifier
                    identifier = summary.get("id", summary.get("content", str(summary)))
                    affected.append(identifier)
                    break
        return affected

    def build_contamination_report(
        self,
        key: str,
        wrong_value: str,
        all_facts: dict[str, Any],
        summaries: list[dict],
    ) -> CrossTurnContamination:
        """Build cross-turn contamination report.

        Comprehensively identify contaminated intermediate results, historical summaries,
        user profiles, and key fact tables.

        Args:
            key: Error fact key
            wrong_value: Wrong value
            all_facts: All facts dict
            summaries: Historical summary list

        Returns:
            Cross-turn contamination report
        """
        # Find the earliest turn where the error fact was written
        introduced_turn = self.find_error_origin(key, wrong_value)
        if introduced_turn is None:
            introduced_turn = 0

        # Find affected intermediate results
        affected_results = self.find_affected_results(key, all_facts)

        # Find contaminated historical summaries
        affected_summaries = self.find_affected_summaries(key, summaries)

        # Identify contaminated user profile fields (simplified: check user_profile related fields in all_facts)
        affected_user_profile = []
        for fact_key in affected_results:
            if "user_profile" in fact_key or "profile" in fact_key:
                affected_user_profile.append(fact_key)

        # Identify contaminated key fact tables (simplified: check fact_table related fields in all_facts)
        affected_fact_table = []
        for fact_key in affected_results:
            if "fact_table" in fact_key or "fact" in fact_key:
                affected_fact_table.append(fact_key)

        report = CrossTurnContamination(
            error_fact_key=key,
            introduced_turn=introduced_turn,
            affected_results=affected_results,
            affected_summaries=affected_summaries,
            affected_user_profile=affected_user_profile,
            affected_fact_table=affected_fact_table,
        )
        logger.info(
            "Built cross-turn contamination report: error fact %s written in turn %d, %d affected results",
            key,
            introduced_turn,
            len(affected_results),
        )
        return report

"""Candidate path manager - Manages candidate paths and failed path tracking at decision nodes.

Maintains candidate path lists for each decision node, supports:
- Registering decision nodes
- Marking paths as failed and recording failure reasons
- Getting the next available candidate path
- Fast path switching
- Failed path recovery detection and retry judgment
"""

import logging

from xplan.models.backtracking import (
    CandidatePath,
    DecisionNode,
    FailurePathRecord,
)

logger = logging.getLogger(__name__)


class CandidatePathManager:
    """Candidate path manager.

    Manages candidate paths of decision nodes, supports failed path tracking and fast switching.

    Attributes:
        _nodes: Decision node storage, key is decision_id
        _failure_records: Failed path record list
    """

    def __init__(self) -> None:
        """Initialize candidate path manager."""
        self._nodes: dict[str, DecisionNode] = {}
        self._failure_records: list[FailurePathRecord] = []

    def register_decision(
        self,
        decision_id: str,
        selected: str,
        candidates: list[CandidatePath],
    ) -> None:
        """Register a decision node.

        Args:
            decision_id: Decision node ID
            selected: Currently selected path
            candidates: Candidate path list
        """
        self._nodes[decision_id] = DecisionNode(
            decision_id=decision_id,
            selected=selected,
            candidates=candidates,
        )
        logger.info(
            "Registered decision node %s, selected path: %s, candidate path count: %d",
            decision_id,
            selected,
            len(candidates),
        )

    def get_decision(self, decision_id: str) -> DecisionNode | None:
        """Get a decision node.

        Args:
            decision_id: Decision node ID

        Returns:
            Decision node, returns None if not found
        """
        return self._nodes.get(decision_id)

    def mark_path_failed(
        self,
        decision_id: str,
        path: str,
        reason: str,
        turn: int = 0,
    ) -> None:
        """Mark a path as failed.

        Updates the candidate path status to failed and records the failure reason.
        Also creates a FailurePathRecord for failed path tracking.

        Args:
            decision_id: Decision node ID
            path: Name of the failed path
            reason: Failure reason
            turn: Turn number when the failure occurred
        """
        node = self._nodes.get(decision_id)
        if node is None:
            logger.warning("Decision node %s does not exist, cannot mark path as failed", decision_id)
            return

        for candidate in node.candidates:
            if candidate.path == path:
                candidate.status = "failed"
                candidate.reason = reason
                break

        # Create failure path record
        failure_record = FailurePathRecord(
            path=path,
            failure_reason=reason,
            failure_turn=turn,
            recovered=False,
        )
        self._failure_records.append(failure_record)
        logger.info(
            "Marked path %s as failed (decision node %s), reason: %s",
            path,
            decision_id,
            reason,
        )

    def get_next_available(
        self, decision_id: str
    ) -> CandidatePath | None:
        """Get the next available candidate path.

        Args:
            decision_id: Decision node ID

        Returns:
            Next available candidate path, returns None if none available
        """
        node = self._nodes.get(decision_id)
        if node is None:
            return None

        for candidate in node.candidates:
            if candidate.status == "available":
                return candidate
        return None

    def switch_path(self, decision_id: str) -> CandidatePath | None:
        """Fast path switching.

        Gets the next available path and marks it as selected.
        If no available path, returns None.

        Args:
            decision_id: Decision node ID

        Returns:
            Switched candidate path, returns None if none available
        """
        node = self._nodes.get(decision_id)
        if node is None:
            logger.warning("Decision node %s does not exist, cannot switch path", decision_id)
            return None

        next_path = self.get_next_available(decision_id)
        if next_path is None:
            logger.info("Decision node %s has no available candidate paths", decision_id)
            return None

        # Mark the originally selected path as tried
        for candidate in node.candidates:
            if candidate.path == node.selected and candidate.status == "available":
                candidate.status = "tried"
                break

        node.selected = next_path.path
        logger.info(
            "Decision node %s switched path to: %s",
            decision_id,
            next_path.path,
        )
        return next_path

    def check_failure_recovered(self, path: str) -> bool:
        """Check whether the failure reason of a failed path has been resolved.

        Simplified implementation: returns False, should be detected externally in practice.

        Args:
            path: Path name

        Returns:
            Whether the failure reason has been resolved
        """
        return False

    def get_failed_paths(self) -> list[FailurePathRecord]:
        """Get all failed path records.

        Returns:
            Failed path record list
        """
        return list(self._failure_records)

    def can_retry_failed_path(self, path: str) -> bool:
        """Determine whether a failed path can be retried.

        A failed path can only be retried when its failure reason has been resolved.

        Args:
            path: Path name

        Returns:
            Whether it can be retried
        """
        for record in self._failure_records:
            if record.path == path:
                return record.recovered
        # Paths without failure records can be retried
        return True

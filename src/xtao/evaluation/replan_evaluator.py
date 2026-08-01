"""Replan effect evaluator - Quantitative evaluation of Replan mechanism performance.

Evaluates around five core metrics of the Replan mechanism:
1. Root cause accuracy: Whether the located root cause step is consistent with the actual root cause
2. Replan start accuracy: Whether the Replan start point is reasonable (not too late or too early)
3. Result reuse rate: Proportion of trusted results that are reused
4. Replan recovery success rate: Whether execution is successfully recovered after Replan
5. Replan oscillation rate: Whether path switching oscillation occurs

Evaluation flow:
- Collect data at runtime via record_event / record_path_switch
- Export test set via export_test_set, import annotations after manual labeling via import_annotations
- Call get_metrics to get five metrics, generate_report to generate evaluation report
"""

from __future__ import annotations

from xtao.models.replan_evaluation import (
    OscillationDetector,
    ReplanEvent,
    ReplanMetrics,
)


class ReplanEvaluator:
    """Replan effect evaluator.

    Collects Replan events and path switching history, calculates five core metrics,
    supports manual annotation import and evaluation report generation.

    Usage:
        evaluator = ReplanEvaluator()
        evaluator.record_event(event)
        evaluator.record_path_switch("plan-1", "path-A")
        metrics = evaluator.get_metrics()
        report = evaluator.generate_report()
    """

    def __init__(self) -> None:
        """Initialize evaluator."""
        # Replan event storage
        self._events: list[ReplanEvent] = []
        # Path switching history: plan_id -> path sequence
        self._path_history: dict[str, list[str]] = {}
        # Oscillation detection window size: detect path pair repeated switching within this window
        self._oscillation_window: int = 5

    # ------------------------------------------------------------------ #
    # Data collection - Record
    # ------------------------------------------------------------------ #

    def record_event(self, event: ReplanEvent) -> None:
        """Record a Replan event.

        If the event already exists (same event_id), updates it; otherwise appends.
        Also merges the event's own path_history into the global path history.

        Args:
            event: Replan event record
        """
        # Find whether an event with the same event_id already exists
        for i, existing in enumerate(self._events):
            if existing.event_id == event.event_id:
                self._events[i] = event
                break
        else:
            self._events.append(event)

        # Merge the event's own path_history into global path history
        if event.path_history:
            plan_id = event.plan_id
            if plan_id not in self._path_history:
                self._path_history[plan_id] = []
            # Append with deduplication, avoid duplicate recording of the same path
            for path in event.path_history:
                history = self._path_history[plan_id]
                if not history or history[-1] != path:
                    history.append(path)

    def record_path_switch(self, plan_id: str, path: str) -> None:
        """Record path switch.

        Maintains the path switching sequence for each Plan, used for oscillation detection.
        Consecutive same paths are deduplicated, only keeping switch actions.

        Args:
            plan_id: Plan identifier
            path: Switched-to path identifier
        """
        if plan_id not in self._path_history:
            self._path_history[plan_id] = []
        history = self._path_history[plan_id]
        # Only record when the path actually changes
        if not history or history[-1] != path:
            history.append(path)

    # ------------------------------------------------------------------ #
    # Metric calculation - Calculate
    # ------------------------------------------------------------------ #

    def calculate_root_cause_accuracy(self) -> float:
        """Calculate root cause accuracy.

        Only counts events with root_cause_correct annotation.
        Accuracy = correct location count / total annotated event count

        Returns:
            Root cause accuracy, returns 0.0 when no annotated events
        """
        annotated = [
            e for e in self._events if e.root_cause_correct is not None
        ]
        if not annotated:
            return 0.0
        correct_count = sum(1 for e in annotated if e.root_cause_correct)
        return correct_count / len(annotated)

    def calculate_replan_start_accuracy(self) -> float:
        """Calculate Replan start accuracy.

        Only counts events with replan_start_correct annotation.
        Annotation judges from two aspects:
        - Whether rollback is too late: kept incorrect results
        - Whether rollback is too early: wasted correct results
        Accuracy = reasonable start count / total annotated event count

        Returns:
            Replan start accuracy, returns 0.0 when no annotated events
        """
        annotated = [
            e for e in self._events if e.replan_start_correct is not None
        ]
        if not annotated:
            return 0.0
        correct_count = sum(1 for e in annotated if e.replan_start_correct)
        return correct_count / len(annotated)

    def calculate_result_reuse_rate(self) -> float:
        """Calculate result reuse rate.

        Overall reuse rate = sum of reused results across all events / sum of trusted results across all events

        Returns:
            Result reuse rate, returns 0.0 when no trusted results
        """
        total_trusted = sum(e.trusted_results for e in self._events)
        total_reused = sum(e.reused_results for e in self._events)
        if total_trusted == 0:
            return 0.0
        return total_reused / total_trusted

    def calculate_recovery_success_rate(self) -> float:
        """Calculate Replan recovery success rate.

        Recovery success rate = recovered count / total Replan count

        Returns:
            Replan recovery success rate, returns 0.0 when no events
        """
        if not self._events:
            return 0.0
        recovered_count = sum(1 for e in self._events if e.recovered)
        return recovered_count / len(self._events)

    def detect_oscillation(self, plan_id: str | None = None) -> OscillationDetector:
        """Detect path oscillation.

        Oscillation definition: Within the window size, the same path pair switches repeatedly >= 2 times.
        For example A->B->A->B is oscillation (path pair [A,B] repeated 2 times).

        Args:
            plan_id: When specified, detects that Plan; when None, detects all Plans.
                     When detecting all Plans, oscillation in any Plan counts as overall oscillation,
                     oscillation count is the sum of oscillation counts across all Plans.

        Returns:
            Oscillation detection result, including whether oscillating, oscillation count and oscillating path pairs
        """
        if plan_id is not None:
            return self._detect_single_plan_oscillation(plan_id)

        # Detect all Plans
        total_count = 0
        all_oscillating_pairs: list[list[str]] = []
        for pid in self._path_history:
            result = self._detect_single_plan_oscillation(pid)
            total_count += result.oscillation_count
            all_oscillating_pairs.extend(result.oscillating_paths)

        return OscillationDetector(
            is_oscillating=total_count > 0,
            oscillation_count=total_count,
            oscillating_paths=all_oscillating_pairs,
        )

    def _detect_single_plan_oscillation(self, plan_id: str) -> OscillationDetector:
        """Detect path oscillation for a single Plan.

        Detects path pair repeated switching via sliding window: if a path pair (X, Y)
        repeats >= 2 times within the window (i.e. X->Y->X->Y pattern), it is judged as oscillation.

        Args:
            plan_id: Plan identifier

        Returns:
            Oscillation detection result
        """
        history = self._path_history.get(plan_id, [])
        if len(history) < 4:
            return OscillationDetector(
                is_oscillating=False, oscillation_count=0
            )

        window = self._oscillation_window
        oscillating_pairs: list[list[str]] = []
        oscillation_count = 0
        seen_pairs: set[tuple[str, str]] = set()

        # Sliding window to detect oscillation pattern
        # Oscillation pattern: X Y X Y (path pair XY repeats within the window)
        for i in range(len(history) - 3):
            # Check whether history[i:i+4] constitutes X Y X Y pattern
            segment = history[i : i + 4]
            if len(segment) < 4:
                break
            if segment[0] == segment[2] and segment[1] == segment[3]:
                pair = (segment[0], segment[1])
                oscillation_count += 1
                pair_list = [segment[0], segment[1]]
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    oscillating_pairs.append(pair_list)

        return OscillationDetector(
            is_oscillating=oscillation_count > 0,
            oscillation_count=oscillation_count,
            oscillating_paths=oscillating_pairs,
        )

    def calculate_oscillation_rate(self) -> float:
        """Calculate Replan oscillation rate.

        Oscillation rate = number of oscillating Plans / total Plan count

        Returns:
            Replan oscillation rate, returns 0.0 when no Plans
        """
        if not self._path_history:
            return 0.0
        oscillating_plan_count = 0
        for plan_id in self._path_history:
            result = self._detect_single_plan_oscillation(plan_id)
            if result.is_oscillating:
                oscillating_plan_count += 1
        return oscillating_plan_count / len(self._path_history)

    # ------------------------------------------------------------------ #
    # Aggregate & Export
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> ReplanMetrics:
        """Get all Replan effect evaluation metrics.

        Returns:
            ReplanMetrics containing five core metrics and basic statistics
        """
        return ReplanMetrics(
            root_cause_accuracy=self.calculate_root_cause_accuracy(),
            replan_start_accuracy=self.calculate_replan_start_accuracy(),
            result_reuse_rate=self.calculate_result_reuse_rate(),
            recovery_success_rate=self.calculate_recovery_success_rate(),
            oscillation_rate=self.calculate_oscillation_rate(),
            total_replan_count=len(self._events),
            total_failure_cases=sum(
                1 for e in self._events if not e.recovered
            ),
        )

    def get_events(self) -> list[ReplanEvent]:
        """Get all event records.

        Returns:
            Event record list (in recording order)
        """
        return list(self._events)

    def export_test_set(self) -> list[dict]:
        """Export test set.

        Exports key fields of all events for manual annotation or fault injection evaluation.
        root_cause_correct and replan_start_correct are set to None for annotation.

        Returns:
            List of test set items to annotate, each item is a dict for one event
        """
        test_set: list[dict] = []
        for event in self._events:
            test_set.append(
                {
                    "event_id": event.event_id,
                    "plan_id": event.plan_id,
                    "trigger": event.trigger,
                    "failure_step_id": event.failure_step_id,
                    "root_cause_step_id": event.root_cause_step_id,
                    "actual_root_cause": event.actual_root_cause,
                    "root_cause_correct": None,
                    "replan_start_step_id": event.replan_start_step_id,
                    "actual_replan_start": event.actual_replan_start,
                    "replan_start_correct": None,
                    "total_results": event.total_results,
                    "trusted_results": event.trusted_results,
                    "reused_results": event.reused_results,
                    "recovered": event.recovered,
                }
            )
        return test_set

    def import_annotations(self, annotations: list[dict]) -> None:
        """Import manual annotation results.

        Matches and updates event annotation fields by event_id.

        Args:
            annotations: Annotation list, each item format is
                {"event_id": "...",
                 "root_cause_correct": true/false,
                 "replan_start_correct": true/false,
                 "actual_root_cause": "...",   # optional
                 "actual_replan_start": "..."}  # optional
        """
        # Build mapping from event_id to event index
        index_map = {
            e.event_id: i for i, e in enumerate(self._events)
        }
        for annotation in annotations:
            event_id = annotation.get("event_id")
            if event_id is None or event_id not in index_map:
                continue
            idx = index_map[event_id]
            event = self._events[idx]
            # Update annotation fields
            if "root_cause_correct" in annotation:
                event.root_cause_correct = annotation["root_cause_correct"]
            if "replan_start_correct" in annotation:
                event.replan_start_correct = annotation["replan_start_correct"]
            if "actual_root_cause" in annotation:
                event.actual_root_cause = annotation["actual_root_cause"]
            if "actual_replan_start" in annotation:
                event.actual_replan_start = annotation["actual_replan_start"]

    def generate_report(self) -> str:
        """Generate evaluation report.

        Aggregates five core metrics and basic statistics, and provides improvement suggestions.

        Returns:
            Evaluation report in text format
        """
        metrics = self.get_metrics()
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("Replan Effect Evaluation Report")
        lines.append("=" * 60)
        lines.append("")
        lines.append("[Core Metrics]")
        lines.append(
            f"  1. Root cause accuracy: {metrics.root_cause_accuracy:.2%}"
        )
        lines.append(
            f"  2. Replan start accuracy: {metrics.replan_start_accuracy:.2%}"
        )
        lines.append(
            f"  3. Result reuse rate: {metrics.result_reuse_rate:.2%}"
        )
        lines.append(
            f"  4. Replan recovery success rate: {metrics.recovery_success_rate:.2%}"
        )
        lines.append(
            f"  5. Replan oscillation rate: {metrics.oscillation_rate:.2%}"
        )
        lines.append("")
        lines.append("[Basic Statistics]")
        lines.append(f"  Total replan count: {metrics.total_replan_count}")
        lines.append(f"  Total failure cases: {metrics.total_failure_cases}")
        lines.append("")

        # Improvement suggestions
        lines.append("[Improvement Suggestions]")
        suggestions: list[str] = []
        if metrics.root_cause_accuracy < 0.8:
            suggestions.append(
                "Root cause accuracy is low, suggest enhancing root cause analysis prompts, "
                "introducing more context evidence to assist location"
            )
        if metrics.replan_start_accuracy < 0.8:
            suggestions.append(
                "Replan start accuracy is low, suggest optimizing backtracking strategy, "
                "avoiding rollback too late (keeping incorrect results) or too early (wasting correct results)"
            )
        if metrics.result_reuse_rate < 0.5:
            suggestions.append(
                "Result reuse rate is low, suggest strengthening trusted result identification and reuse mechanism, "
                "reducing redundant computation"
            )
        if metrics.recovery_success_rate < 0.7:
            suggestions.append(
                "Replan recovery success rate is low, suggest checking replan granularity selection strategy, "
                "prioritizing minimum granularity replan"
            )
        if metrics.oscillation_rate > 0.2:
            suggestions.append(
                "Replan oscillation rate is high, suggest introducing oscillation detection and cooldown mechanism, "
                "avoiding repeated path switching"
            )
        if not suggestions:
            suggestions.append("All metrics meet standards, Replan mechanism is running well")
        for i, suggestion in enumerate(suggestions, 1):
            lines.append(f"  {i}. {suggestion}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

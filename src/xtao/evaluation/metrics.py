"""Online monitoring metrics - Prometheus-based Plan quality metrics collection.

Implements the online monitoring part of the offline + online dual-track system,
indirectly evaluating Plan quality through Prometheus metrics, including:
Plan completion rate, step success rate, replan trigger rate,
user correction rate, final task success rate, average iteration count.

Metric system:
- Counter: Cumulative count (plan_started/completed, step_success/failure, etc.)
- Gauge: Current ratio (completion_rate, success_rate, etc.)
- Histogram: Iteration count distribution
"""

from __future__ import annotations

from prometheus_client import REGISTRY, Counter, Gauge, Histogram


class PlanMetrics:
    """Plan online monitoring metrics collector.

    Uses Prometheus Counter/Gauge/Histogram to collect key metrics during Plan execution.
    When enabled=False, all methods become no-ops, for use in environments without monitoring.

    Metric descriptions:
        - plan_started_total / plan_completed_total: Plan started/completed count
        - step_success_total / step_failure_total: Step success/failure count
        - replan_total: Replan trigger count
        - user_correction_total: User correction count
        - task_success_total / task_failure_total: Final task success/failure count
        - current_*_rate: Current ratios (Gauge)
        - iteration_count: Iteration count distribution (Histogram)
    """

    def __init__(self, enabled: bool = True):
        """Initialize Prometheus metrics.

        Args:
            enabled: Whether to enable metrics collection. When False, all methods become no-ops.
        """
        self.enabled = enabled

        # Internal counters are always initialized to ensure get methods return safely when enabled=False
        self._started_count: int = 0
        self._completed_count: int = 0
        self._step_success_count: int = 0
        self._step_failure_count: int = 0
        self._replan_count: int = 0
        self._user_correction_count: int = 0
        self._task_success_count: int = 0
        self._task_failure_count: int = 0
        self._iteration_sum: int = 0
        self._iteration_samples_count: int = 0

        if not enabled:
            return

        # Counter metrics - cumulative count
        self._plan_started = self._get_or_create_counter(
            "plan_started_total", "Total number of started Plans", ["plan_id"]
        )
        self._plan_completed = self._get_or_create_counter(
            "plan_completed_total", "Total number of completed Plans", ["plan_id"]
        )
        self._step_success = self._get_or_create_counter(
            "step_success_total", "Total number of successful steps", ["plan_id", "step_id"]
        )
        self._step_failure = self._get_or_create_counter(
            "step_failure_total", "Total number of failed steps", ["plan_id", "step_id"]
        )
        self._replan = self._get_or_create_counter(
            "replan_total", "Total number of replan triggers", ["plan_id"]
        )
        self._user_correction = self._get_or_create_counter(
            "user_correction_total", "Total number of user corrections", ["plan_id"]
        )
        self._task_success = self._get_or_create_counter(
            "task_success_total", "Total number of successful final tasks", ["plan_id"]
        )
        self._task_failure = self._get_or_create_counter(
            "task_failure_total", "Total number of failed final tasks", ["plan_id"]
        )

        # Gauge metrics - current ratios
        self._plan_completion_rate_gauge = self._get_or_create_gauge(
            "current_plan_completion_rate", "Current Plan completion rate"
        )
        self._step_success_rate_gauge = self._get_or_create_gauge(
            "current_step_success_rate", "Current step success rate"
        )
        self._replan_rate_gauge = self._get_or_create_gauge(
            "current_replan_rate", "Current replan trigger rate"
        )
        self._user_correction_rate_gauge = self._get_or_create_gauge(
            "current_user_correction_rate", "Current user correction rate"
        )
        self._task_success_rate_gauge = self._get_or_create_gauge(
            "current_task_success_rate", "Current final task success rate"
        )

        # Histogram metrics - iteration count distribution
        self._iteration_count = self._get_or_create_histogram(
            "iteration_count", "Iteration count distribution", ["plan_id"]
        )

    # ------------------------------------------------------------------ #
    # Metric creation helper methods
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_or_create_metric(
        metric_cls: type, name: str, description: str, labels: list[str] | None = None
    ) -> Counter | Gauge | Histogram:
        """Get or create a Prometheus metric, avoiding duplicate registration errors.

        prometheus_client raises ValueError when registering a metric with the same name
        in the same process. This method retrieves the existing metric from the global
        REGISTRY when it detects a duplicate registration.

        Args:
            metric_cls: Metric type (Counter/Gauge/Histogram)
            name: Metric name
            description: Metric description
            labels: Label list, optional

        Returns:
            Prometheus metric instance
        """
        try:
            if labels:
                return metric_cls(name, description, labels)
            return metric_cls(name, description)
        except ValueError:
            # Metric already registered, get existing instance from global REGISTRY
            collector = REGISTRY._names_to_collectors.get(name)
            if collector is None:
                raise
            return collector

    def _get_or_create_counter(
        self, name: str, description: str, labels: list[str] | None = None
    ) -> Counter:
        """Get or create a Counter metric."""
        return self._get_or_create_metric(Counter, name, description, labels)  # type: ignore[return-value]

    def _get_or_create_gauge(
        self, name: str, description: str, labels: list[str] | None = None
    ) -> Gauge:
        """Get or create a Gauge metric."""
        return self._get_or_create_metric(Gauge, name, description, labels)  # type: ignore[return-value]

    def _get_or_create_histogram(
        self, name: str, description: str, labels: list[str] | None = None
    ) -> Histogram:
        """Get or create a Histogram metric."""
        return self._get_or_create_metric(Histogram, name, description, labels)  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Record methods - Record
    # ------------------------------------------------------------------ #

    def record_plan_started(self, plan_id: str) -> None:
        """Record Plan start.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._plan_started.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._started_count += 1
        self._update_plan_completion_rate()
        self._update_replan_rate()
        self._update_user_correction_rate()

    def record_plan_completed(self, plan_id: str) -> None:
        """Record Plan completion.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._plan_completed.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._completed_count += 1
        self._update_plan_completion_rate()

    def record_step_success(self, plan_id: str, step_id: str) -> None:
        """Record step success.

        Args:
            plan_id: Plan identifier
            step_id: Step identifier
        """
        if not self.enabled:
            return
        self._step_success.labels(plan_id=plan_id, step_id=step_id).inc()  # type: ignore[union-attr]
        self._step_success_count += 1
        self._update_step_success_rate()

    def record_step_failure(self, plan_id: str, step_id: str) -> None:
        """Record step failure.

        Args:
            plan_id: Plan identifier
            step_id: Step identifier
        """
        if not self.enabled:
            return
        self._step_failure.labels(plan_id=plan_id, step_id=step_id).inc()  # type: ignore[union-attr]
        self._step_failure_count += 1
        self._update_step_success_rate()

    def record_replan(self, plan_id: str) -> None:
        """Record replan trigger.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._replan.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._replan_count += 1
        self._update_replan_rate()

    def record_user_correction(self, plan_id: str) -> None:
        """Record user correction.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._user_correction.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._user_correction_count += 1
        self._update_user_correction_rate()

    def record_task_success(self, plan_id: str) -> None:
        """Record final task success.

        Note: Plan completion does not equal task success; this metric is tracked independently.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._task_success.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._task_success_count += 1
        self._update_task_success_rate()

    def record_task_failure(self, plan_id: str) -> None:
        """Record final task failure.

        Args:
            plan_id: Plan identifier
        """
        if not self.enabled:
            return
        self._task_failure.labels(plan_id=plan_id).inc()  # type: ignore[union-attr]
        self._task_failure_count += 1
        self._update_task_success_rate()

    def record_iteration_count(self, plan_id: str, count: int) -> None:
        """Record iteration count.

        Args:
            plan_id: Plan identifier
            count: Iteration count
        """
        if not self.enabled:
            return
        self._iteration_count.labels(plan_id=plan_id).observe(count)  # type: ignore[union-attr]
        self._iteration_sum += count
        self._iteration_samples_count += 1

    # ------------------------------------------------------------------ #
    # Rate update methods - internal use
    # ------------------------------------------------------------------ #

    def _update_plan_completion_rate(self) -> None:
        """Update Plan completion rate Gauge."""
        rate = self._completed_count / self._started_count if self._started_count > 0 else 0.0
        self._plan_completion_rate_gauge.set(rate)  # type: ignore[union-attr]

    def _update_step_success_rate(self) -> None:
        """Update step success rate Gauge."""
        total = self._step_success_count + self._step_failure_count
        rate = self._step_success_count / total if total > 0 else 0.0
        self._step_success_rate_gauge.set(rate)  # type: ignore[union-attr]

    def _update_replan_rate(self) -> None:
        """Update replan trigger rate Gauge."""
        rate = self._replan_count / self._started_count if self._started_count > 0 else 0.0
        self._replan_rate_gauge.set(rate)  # type: ignore[union-attr]

    def _update_user_correction_rate(self) -> None:
        """Update user correction rate Gauge."""
        rate = (
            self._user_correction_count / self._started_count
            if self._started_count > 0
            else 0.0
        )
        self._user_correction_rate_gauge.set(rate)  # type: ignore[union-attr]

    def _update_task_success_rate(self) -> None:
        """Update final task success rate Gauge."""
        total = self._task_success_count + self._task_failure_count
        rate = self._task_success_count / total if total > 0 else 0.0
        self._task_success_rate_gauge.set(rate)  # type: ignore[union-attr]

    # ------------------------------------------------------------------ #
    # Query methods - Get
    # ------------------------------------------------------------------ #

    def get_plan_completion_rate(self) -> float:
        """Get Plan completion rate.

        Returns:
            Plan completion rate (completed / started), returns 0.0 when no data
        """
        if self._started_count == 0:
            return 0.0
        return self._completed_count / self._started_count

    def get_step_success_rate(self) -> float:
        """Get step success rate.

        Returns:
            Step success rate (success / total step executions), returns 0.0 when no data
        """
        total = self._step_success_count + self._step_failure_count
        if total == 0:
            return 0.0
        return self._step_success_count / total

    def get_replan_rate(self) -> float:
        """Get replan trigger rate.

        Returns:
            Replan trigger rate (replan count / started Plan count), returns 0.0 when no data
        """
        if self._started_count == 0:
            return 0.0
        return self._replan_count / self._started_count

    def get_user_correction_rate(self) -> float:
        """Get user correction rate.

        Returns:
            User correction rate (correction count / started Plan count), returns 0.0 when no data
        """
        if self._started_count == 0:
            return 0.0
        return self._user_correction_count / self._started_count

    def get_task_success_rate(self) -> float:
        """Get final task success rate.

        Note: Plan completion rate and final task success rate are independent metrics;
        Plan completion does not equal task success.

        Returns:
            Final task success rate (success / total task outcomes), returns 0.0 when no data
        """
        total = self._task_success_count + self._task_failure_count
        if total == 0:
            return 0.0
        return self._task_success_count / total

    def get_average_iteration_count(self) -> float:
        """Get average iteration count.

        Returns:
            Average iteration count, returns 0.0 when no data
        """
        if self._iteration_samples_count == 0:
            return 0.0
        return self._iteration_sum / self._iteration_samples_count

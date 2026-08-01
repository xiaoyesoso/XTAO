"""TAO evaluation engine - metrics collection, LLM-as-judge and reporting.

Collects structured evaluation events from TAO runs and computes four layers
of metrics: Think, Action, Observation and Overall. Supports both code-based
metrics (when golden answers are available) and LLM-as-judge scoring.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from xtao.models.tao import (
    ActionRecord,
    ActionStatus,
    ExecutionStatus,
    FactCategory,
    Observation,
    TAOResult,
    TAOState,
    ThinkResult,
)
from xtao.models.tao_evaluation import (
    ActionMetrics,
    ActionRoundEvaluation,
    GoldenAnswer,
    JudgeSource,
    LLMJudgeRequest,
    LLMJudgeResult,
    ObservationMetrics,
    ObservationRoundEvaluation,
    OverallMetrics,
    TAOEvaluationEvent,
    TAOEvaluationMetrics,
    TAOEvaluationReport,
    TAOEvaluationSuggestion,
    ThinkMetrics,
    ThinkRoundEvaluation,
)

logger = logging.getLogger(__name__)


def _safe_mean(values: list[float]) -> float:
    """Return mean of values, or 0.0 for empty list."""
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    """Return percentile of a list of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * percentile
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def _extract_json(text: str) -> Any:
    """Extract JSON from an LLM response (markdown block or bare JSON)."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class TAOEvaluator:
    """Evaluator for TAO quality metrics and reports.

    Attributes:
        llm_service: Optional LLM service for LLM-as-judge scoring
        events: In-memory store of TAO evaluation events
        golden_answers: In-memory store of human annotations keyed by event_id
        judge_results: In-memory store of LLM/human judge results
    """

    def __init__(self, llm_service: Any | None = None) -> None:
        """Initialize the evaluator.

        Args:
            llm_service: Optional LLM service for LLM-as-judge evaluation
        """
        self.llm_service = llm_service
        self.events: dict[str, TAOEvaluationEvent] = {}
        self.golden_answers: dict[str, GoldenAnswer] = {}
        self.judge_results: list[LLMJudgeResult] = []

    # ── Event recording (task 11.1-11.4) ──────────────────────

    def record_event(self, event: TAOEvaluationEvent) -> None:
        """Record or update a TAO evaluation event."""
        self.events[event.event_id] = event

    def record_from_result(
        self,
        result: TAOResult,
        task_id: str = "",
        user_input: str = "",
        duration_ms: int = 0,
    ) -> TAOEvaluationEvent:
        """Build a TAOEvaluationEvent from a TAOResult and store it.

        This is the primary integration point: after a TAO run completes, the
        result is converted into a structured evaluation event that captures
        Think / Action / Observation data for every round.
        """
        state = result.state
        if state is None:
            state = TAOState(goal_state={"final_goal": user_input})

        think_rounds: list[ThinkRoundEvaluation] = []
        action_rounds: list[ActionRoundEvaluation] = []
        observation_rounds: list[ObservationRoundEvaluation] = []

        max_rounds = max(len(state.actions), len(state.observations))
        for idx in range(1, max_rounds + 1):
            action = state.actions[idx - 1] if idx <= len(state.actions) else None
            observation = (
                state.observations[idx - 1] if idx <= len(state.observations) else None
            )
            think = self._find_think_for_round(state, idx)

            if think:
                think_rounds.append(self._build_think_eval(idx, think))
            if action:
                action_rounds.append(self._build_action_eval(idx, action))
            if observation:
                observation_rounds.append(self._build_observation_eval(idx, observation))

        token_usage: dict[str, int] = {}
        for tr in think_rounds:
            for model, tokens in tr.token_usage.items():
                token_usage[model] = token_usage.get(model, 0) + tokens
        for obs in observation_rounds:
            for model, tokens in obs.token_usage.items():
                token_usage[model] = token_usage.get(model, 0) + tokens

        event = TAOEvaluationEvent(
            task_id=task_id,
            user_input=user_input,
            final_exit=result.exit_type.value,
            used_loops=result.used_loops,
            total_actions=result.total_actions,
            success=result.exit_type.value == "finish",
            duration_ms=duration_ms,
            think_rounds=think_rounds,
            action_rounds=action_rounds,
            observation_rounds=observation_rounds,
            token_usage=token_usage,
        )
        self.record_event(event)
        return event

    @staticmethod
    def _find_think_for_round(state: TAOState, round_index: int) -> ThinkResult | None:
        """Best-effort Think result lookup from state metadata if available."""
        # ThinkResult objects are not stored on TAOState by default; subclasses
        # or integrations can attach them via state metadata.
        meta = getattr(state, "metadata", None)
        if isinstance(meta, dict):
            thinks = meta.get("think_results", [])
            if 0 <= round_index - 1 < len(thinks):
                raw = thinks[round_index - 1]
                if isinstance(raw, ThinkResult):
                    return raw
                if isinstance(raw, dict):
                    return ThinkResult.model_validate(raw)
        return None

    @staticmethod
    def _build_think_eval(idx: int, think: ThinkResult) -> ThinkRoundEvaluation:
        return ThinkRoundEvaluation(
            round_index=idx,
            current_goal=think.current_goal,
            selected_action=think.selected_action,
            action_params=think.action_params,
            exit_decision=think.exit_decision.value,
            missing_slots=list(think.missing_slots),
            risk_level=think.risk_level.value,
            reason=think.reason,
        )

    @staticmethod
    def _build_action_eval(idx: int, action: ActionRecord) -> ActionRoundEvaluation:
        return ActionRoundEvaluation(
            round_index=idx,
            action_id=action.action_id,
            action_name=action.name,
            tool_name=action.tool_name,
            status=action.status.value,
            duration_ms=action.duration_ms or 0,
            error=action.error,
        )

    @staticmethod
    def _build_observation_eval(idx: int, obs: Observation) -> ObservationRoundEvaluation:
        return ObservationRoundEvaluation(
            round_index=idx,
            observation_id=obs.observation_id,
            execution_status=obs.execution_status.value,
            new_facts=[f.model_dump() for f in obs.new_facts],
            missing_information=list(obs.missing_information),
            anomalies=list(obs.anomalies),
            progress=obs.progress,
            information_gain=obs.information_gain.value,
            summary=obs.summary,
        )

    def get_events(self) -> list[TAOEvaluationEvent]:
        """Return all recorded events."""
        return list(self.events.values())

    # ── Golden answer import (task 11.6) ──────────────────────

    def import_golden_answers(self, annotations: list[dict[str, Any]]) -> int:
        """Import human annotations and match them to events by event_id."""
        count = 0
        for raw in annotations:
            try:
                golden = GoldenAnswer.model_validate(raw)
                self.golden_answers[golden.event_id] = golden
                count += 1
            except Exception as e:
                logger.warning("Failed to import golden answer: %s", e)
        return count

    def add_golden_answer(self, golden: GoldenAnswer) -> None:
        """Add or update a single golden answer."""
        self.golden_answers[golden.event_id] = golden

    # ── Metric computation (task 11.1-11.4) ───────────────────

    def get_metrics(self) -> TAOEvaluationMetrics:
        """Compute aggregated metrics across all recorded events."""
        events = self.get_events()
        return TAOEvaluationMetrics(
            think=self._compute_think_metrics(events),
            action=self._compute_action_metrics(events),
            observation=self._compute_observation_metrics(events),
            overall=self._compute_overall_metrics(events),
        )

    def _compute_think_metrics(self, events: list[TAOEvaluationEvent]) -> ThinkMetrics:
        """Compute Think-phase metrics.

        Code-based metrics compare Think outputs to golden answers when
        available; otherwise they fall back to simple heuristics.
        """
        correct_action = 0
        correct_params = 0
        correct_goal = 0
        correct_missing = 0
        constraint_violations = 0
        correct_stop = 0
        total = 0

        for event in events:
            golden = self.golden_answers.get(event.event_id)
            for think in event.think_rounds:
                total += 1
                if golden and golden.optimal_action:
                    if think.selected_action == golden.optimal_action:
                        correct_action += 1
                    if self._params_match(think.action_params, golden.optimal_params or {}):
                        correct_params += 1
                else:
                    # Fallback heuristic: selection is plausible if non-empty
                    if think.selected_action:
                        correct_action += 1
                    if think.action_params is not None:
                        correct_params += 1

                if golden and golden.expected_missing_slots is not None:
                    if set(think.missing_slots) == set(golden.expected_missing_slots):
                        correct_missing += 1
                else:
                    if think.missing_slots:
                        correct_missing += 1

                if think.risk_level == "high":
                    constraint_violations += 1

                if think.exit_decision:
                    if golden and golden.should_stop is not None:
                        if (think.exit_decision == "finish") == golden.should_stop:
                            correct_stop += 1
                    else:
                        correct_stop += 1

                if think.current_goal:
                    correct_goal += 1

        return ThinkMetrics(
            action_selection_accuracy=correct_action / total if total else 0.0,
            action_param_accuracy=correct_params / total if total else 0.0,
            goal_judgment_accuracy=correct_goal / total if total else 0.0,
            missing_slot_accuracy=correct_missing / total if total else 0.0,
            constraint_violation_rate=constraint_violations / total if total else 0.0,
            stop_judgment_accuracy=correct_stop / total if total else 0.0,
            sample_count=total,
        )

    @staticmethod
    def _params_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
        """Compare two parameter dicts loosely."""
        if not a and not b:
            return True
        shared = {k for k in a if k in b}
        if not shared:
            return False
        return all(a[k] == b[k] for k in shared)

    def _compute_action_metrics(self, events: list[TAOEvaluationEvent]) -> ActionMetrics:
        """Compute Action execution metrics."""
        durations: list[float] = []
        success = 0
        failure = 0
        by_tool: dict[str, dict[str, Any]] = {}

        for event in events:
            for action in event.action_rounds:
                durations.append(float(action.duration_ms))
                tool = action.tool_name or action.action_name or "unknown"
                if action.status == ActionStatus.DONE.value:
                    success += 1
                    by_tool.setdefault(tool, {"success": 0, "failure": 0})
                    by_tool[tool]["success"] += 1
                else:
                    failure += 1
                    by_tool.setdefault(tool, {"success": 0, "failure": 0})
                    by_tool[tool]["failure"] += 1

        total = success + failure
        by_tool_summary: dict[str, dict[str, float]] = {}
        for tool, counts in by_tool.items():
            tool_total = counts["success"] + counts["failure"]
            by_tool_summary[tool] = {
                "success_rate": counts["success"] / tool_total if tool_total else 0.0,
                "count": float(tool_total),
            }

        return ActionMetrics(
            success_rate=success / total if total else 0.0,
            average_response_time_ms=_safe_mean(durations),
            p95_response_time_ms=_percentile(durations, 0.95),
            failure_count=failure,
            success_count=success,
            sample_count=total,
            by_tool=by_tool_summary,
        )

    def _compute_observation_metrics(self, events: list[TAOEvaluationEvent]) -> ObservationMetrics:
        """Compute Observation interpretation metrics."""
        tp = 0  # true positives
        fp = 0  # false positives
        fn = 0  # false negatives
        evidence_bound = 0
        total_facts = 0
        misreads = 0
        anomaly_correct = 0
        anomaly_total = 0
        missing_update_correct = 0
        missing_update_total = 0

        for event in events:
            golden = self.golden_answers.get(event.event_id)
            for obs in event.observation_rounds:
                # Evidence binding: every fact should have evidence
                for fact in obs.new_facts:
                    total_facts += 1
                    if fact.get("evidence"):
                        evidence_bound += 1

                # Fact extraction against golden set
                if golden and golden.expected_facts:
                    obs_keys = {f.get("key") for f in obs.new_facts if f.get("key")}
                    golden_keys = {f.get("key") for f in golden.expected_facts if f.get("key")}
                    tp += len(obs_keys & golden_keys)
                    fp += len(obs_keys - golden_keys)
                    fn += len(golden_keys - obs_keys)
                else:
                    # Fallback: count any non-empty fact as correct
                    tp += len(obs.new_facts)

                # Misread detection: execution marked success but anomalies present
                if (
                    obs.execution_status == ExecutionStatus.SUCCESS.value
                    and obs.anomalies
                ):
                    misreads += 1

                # Anomaly detection accuracy
                anomaly_total += 1
                if obs.anomalies:
                    anomaly_correct += 1

                # Missing info update accuracy
                missing_update_total += 1
                if obs.missing_information:
                    missing_update_correct += 1

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        return ObservationMetrics(
            fact_extraction_precision=precision,
            fact_extraction_recall=recall,
            fact_extraction_f1=f1,
            evidence_binding_accuracy=evidence_bound / total_facts if total_facts else 0.0,
            misread_rate=misreads / len(events) if events else 0.0,
            anomaly_detection_accuracy=anomaly_correct / anomaly_total if anomaly_total else 0.0,
            missing_info_update_accuracy=missing_update_correct / missing_update_total
            if missing_update_total
            else 0.0,
            sample_count=len(events),
        )

    def _compute_overall_metrics(self, events: list[TAOEvaluationEvent]) -> OverallMetrics:
        """Compute overall task-level metrics."""
        if not events:
            return OverallMetrics()

        success = sum(1 for e in events if e.success)
        loops = [e.used_loops for e in events]
        actions = [e.total_actions for e in events]
        tokens = [sum(e.token_usage.values()) for e in events]
        durations = [e.duration_ms for e in events]

        return OverallMetrics(
            task_success_rate=success / len(events),
            average_loops=_safe_mean(loops),
            average_actions=_safe_mean(actions),
            average_tokens=_safe_mean(tokens),
            average_duration_ms=_safe_mean(durations),
            sample_count=len(events),
        )

    # ── LLM-as-judge (task 11.5) ──────────────────────────────

    async def llm_judge(self, request: LLMJudgeRequest) -> LLMJudgeResult:
        """Score a single TAO round using an independent LLM judge."""
        if self.llm_service is None:
            return LLMJudgeResult(
                event_id=request.event_id,
                round_index=request.round_index,
                source=JudgeSource.CODE,
                scores={},
                reasoning="No LLM service configured for judge",
            )

        system_prompt = (
            "You are an expert evaluator for an Agent TAO (Think-Action-Observation) loop. "
            "Score the following round on a scale of 0.0 to 1.0 across the relevant metrics. "
            "Respond with a JSON object containing exactly two keys: "
            "'scores' (object with metric names as keys and float values) and 'reasoning' (string)."
        )
        user_prompt = self._build_judge_prompt(request)

        try:
            raw = await self.llm_service.chat(
                system_prompt,
                user_prompt,
                response_format={"type": "json_object"},
            )
            data = _extract_json(raw)
            scores = {str(k): float(v) for k, v in data.get("scores", {}).items()}
            reasoning = str(data.get("reasoning", ""))
            result = LLMJudgeResult(
                event_id=request.event_id,
                round_index=request.round_index,
                source=JudgeSource.LLM,
                scores=scores,
                reasoning=reasoning,
            )
        except Exception as e:
            logger.warning("LLM judge failed: %s", e)
            result = LLMJudgeResult(
                event_id=request.event_id,
                round_index=request.round_index,
                source=JudgeSource.CODE,
                scores={},
                reasoning=f"LLM judge error: {e}",
            )

        self.judge_results.append(result)
        return result

    @staticmethod
    def _build_judge_prompt(request: LLMJudgeRequest) -> str:
        parts = [
            f"User goal: {request.user_input}",
            f"Context summary: {request.context_summary}",
        ]
        if request.golden:
            parts.append(f"Golden answer: {request.golden.model_dump_json()}")
        if request.think_output:
            parts.append(f"Think output: {request.think_output.model_dump_json()}")
        if request.action_output:
            parts.append(f"Action output: {request.action_output.model_dump_json()}")
        if request.observation_output:
            parts.append(f"Observation output: {request.observation_output.model_dump_json()}")
        parts.append(
            "Score these metrics when applicable: action_selection, action_params, "
            "goal_judgment, missing_slots, stop_judgment, risk_assessment, "
            "fact_extraction, evidence_binding, misread_detection, anomaly_detection."
        )
        return "\n\n".join(parts)

    # ── Report generation (task 11.7-11.8) ────────────────────

    def generate_report(self) -> TAOEvaluationReport:
        """Generate a TAO evaluation report with metrics and suggestions."""
        metrics = self.get_metrics()
        suggestions: list[TAOEvaluationSuggestion] = []
        abnormal: list[str] = []

        # Think suggestions
        if metrics.think.action_selection_accuracy < 0.7:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="think",
                    metric="action_selection_accuracy",
                    value=metrics.think.action_selection_accuracy,
                    threshold=0.7,
                    suggestion=(
                        "Action selection accuracy is low. Consider tightening the "
                        "candidate-space coarse filter or adding business-spec descriptions."
                    ),
                )
            )
        if metrics.think.stop_judgment_accuracy < 0.7:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="think",
                    metric="stop_judgment_accuracy",
                    value=metrics.think.stop_judgment_accuracy,
                    threshold=0.7,
                    suggestion=(
                        "Stop judgment is unreliable. Review the success criteria and "
                        "consider tightening ControlState limits."
                    ),
                )
            )
        if metrics.think.constraint_violation_rate > 0.1:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="think",
                    metric="constraint_violation_rate",
                    value=metrics.think.constraint_violation_rate,
                    threshold=0.1,
                    suggestion=(
                        "High constraint violation rate. Inject hard constraints more "
                        "explicitly into the Think prompt and reject high-risk actions."
                    ),
                )
            )

        # Action suggestions
        if metrics.action.success_rate < 0.8:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="action",
                    metric="success_rate",
                    value=metrics.action.success_rate,
                    threshold=0.8,
                    suggestion=(
                        "Action success rate is below target. Review failing tools, "
                        "add retries for transient errors, or improve precondition checks."
                    ),
                )
            )
        if metrics.action.average_response_time_ms > 2000:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="action",
                    metric="average_response_time_ms",
                    value=metrics.action.average_response_time_ms,
                    threshold=2000.0,
                    suggestion=(
                        "Average action latency is high. Consider caching, async "
                        "execution, or replacing slow tools."
                    ),
                )
            )

        # Observation suggestions
        if metrics.observation.fact_extraction_f1 < 0.7:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="observation",
                    metric="fact_extraction_f1",
                    value=metrics.observation.fact_extraction_f1,
                    threshold=0.7,
                    suggestion=(
                        "Observation fact extraction is weak. Provide few-shot examples "
                        "or tighten the expected fact schema in the prompt."
                    ),
                )
            )
        if metrics.observation.misread_rate > 0.1:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="observation",
                    metric="misread_rate",
                    value=metrics.observation.misread_rate,
                    threshold=0.1,
                    suggestion=(
                        "Tool-result misread rate is high. Add code-side anomaly checks "
                        "before semantic interpretation."
                    ),
                )
            )
        if metrics.observation.evidence_binding_accuracy < 0.9:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="observation",
                    metric="evidence_binding_accuracy",
                    value=metrics.observation.evidence_binding_accuracy,
                    threshold=0.9,
                    suggestion=(
                        "Facts lack evidence binding. Enforce evidence fields in the "
                        "Observation prompt and validation."
                    ),
                )
            )

        # Overall suggestions
        if metrics.overall.average_loops > 8:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="overall",
                    metric="average_loops",
                    value=metrics.overall.average_loops,
                    threshold=8.0,
                    suggestion=(
                        "Average TAO loop count is high. Tighten stop conditions, "
                        "shorten the outer supervisor interval, or reduce max_loops."
                    ),
                )
            )
        if metrics.overall.task_success_rate < 0.7:
            suggestions.append(
                TAOEvaluationSuggestion(
                    category="overall",
                    metric="task_success_rate",
                    value=metrics.overall.task_success_rate,
                    threshold=0.7,
                    suggestion=(
                        "Overall task success rate is low. Review Think/Action/Observation "
                        "metrics above and prioritize the weakest layer."
                    ),
                )
            )

        # Identify abnormal samples
        for event in self.get_events():
            if event.used_loops > metrics.overall.average_loops * 2:
                abnormal.append(event.event_id)
            elif not event.success and metrics.overall.task_success_rate > 0.5:
                abnormal.append(event.event_id)

        summary = (
            f"Evaluated {metrics.overall.sample_count} TAO runs. "
            f"Task success rate: {metrics.overall.task_success_rate:.2%}, "
            f"average loops: {metrics.overall.average_loops:.1f}, "
            f"action success rate: {metrics.action.success_rate:.2%}. "
            f"Generated {len(suggestions)} optimization suggestions."
        )

        return TAOEvaluationReport(
            metrics=metrics,
            suggestions=suggestions,
            abnormal_samples=abnormal,
            summary=summary,
        )

    def export_test_set(self) -> list[dict[str, Any]]:
        """Export a test set for human annotation.

        Each entry contains event metadata with golden-answer fields left empty.
        """
        test_set: list[dict[str, Any]] = []
        for event in self.get_events():
            test_set.append(
                {
                    "event_id": event.event_id,
                    "user_input": event.user_input,
                    "final_exit": event.final_exit,
                    "used_loops": event.used_loops,
                    "total_actions": event.total_actions,
                    "duration_ms": event.duration_ms,
                    "optimal_action": None,
                    "optimal_params": None,
                    "expected_facts": [],
                    "expected_missing_slots": [],
                    "should_stop": None,
                    "task_success": None,
                    "notes": "",
                }
            )
        return test_set

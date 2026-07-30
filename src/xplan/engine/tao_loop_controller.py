"""TAO loop exit controller - deterministic exit selection with six exits.

Every TAO loop round ends in exactly one of six exits:
continue / finish / clarify / retry / replan / interrupt.

The controller combines the ThinkResult's exit_decision with Control State
limits and the boundary rules (code-side overrides take precedence):
- max_loops / max_time exceeded => forced interrupt
- success criteria satisfied => forced finish (never keep looping)
- retry budget exhausted => upgrade retry to replan/clarify
- no progress possible => clarify / replan / interrupt instead of idle looping
"""

import logging
from typing import Any

from xplan.models.tao import (
    ActionStatus,
    RiskLevel,
    TAOExit,
    TAOExitRecord,
    TAOState,
    ThinkResult,
)

logger = logging.getLogger(__name__)


class TAOLoopController:
    """Exit controller for the TAO loop.

    Attributes:
        max_action_retries: Retry threshold per action
        dead_loop_threshold: Consecutive selections of the same action before dead loop
        stagnation_window: Number of recent rounds checked for stagnation
    """

    def __init__(
        self,
        max_action_retries: int = 2,
        dead_loop_threshold: int = 3,
        stagnation_window: int | None = None,
    ) -> None:
        """Initialize the exit controller.

        Args:
            max_action_retries: Retry threshold per action
            dead_loop_threshold: Consecutive selections of the same action before dead loop
            stagnation_window: Number of recent rounds checked for stagnation;
                defaults to dead_loop_threshold + 1
        """
        self.max_action_retries = max_action_retries
        self.dead_loop_threshold = dead_loop_threshold
        self.stagnation_window = stagnation_window or (dead_loop_threshold + 1)

    def decide(self, state: TAOState, think: ThinkResult) -> TAOExitRecord:
        """Decide the exit for the current round.

        Priority order (code rules override the LLM decision):
        1. Control limits exceeded => interrupt
        2. Success criteria satisfied => finish
        3. Dead loop / stagnation detected => clarify / replan
        4. High-risk action violating hard constraints => clarify/replan
        5. LLM-proposed retry with exhausted budget => replan
        6. No candidate action can advance => clarify
        7. LLM exit decision (validated)

        Args:
            state: Current TAO state
            think: ThinkResult of this round

        Returns:
            Structured TAOExitRecord
        """
        overridden = False
        exit_type = think.exit_decision
        reason = think.reason

        # Rule 1: control state limits (task 6.3 / 6.6)
        forced = self._check_control_limits(state)
        if forced is not None:
            exit_type, reason, overridden = forced[0], forced[1], exit_type != forced[0]
            return self._record(state, exit_type, reason, overridden)

        # Rule 2: success criteria satisfied => forced finish (task 8.4)
        if think.success_criteria_satisfied and not think.missing_slots:
            if exit_type != TAOExit.FINISH:
                overridden = True
                reason = (
                    "Success criteria satisfied; overriding "
                    f"'{exit_type.value}' to finish (no looping for its own sake)"
                )
                exit_type = TAOExit.FINISH
            return self._record(state, exit_type, reason or think.reason, overridden)

        # Rule 3: dead loop / stagnation detection (task 6.3 / 6.4 / 6.5)
        loop_check = self._check_dead_loop(state, think)
        if loop_check is not None:
            exit_type, reason = loop_check
            overridden = exit_type != think.exit_decision
            return self._record(state, exit_type, reason, overridden)

        stagnation_check = self._check_stagnation(state)
        if stagnation_check is not None:
            exit_type, reason = stagnation_check
            overridden = exit_type != think.exit_decision
            return self._record(state, exit_type, reason, overridden)

        # Rule 4: high risk => prefer clarify / replan (task 3.7 linkage)
        if think.risk_level == RiskLevel.HIGH and exit_type in (TAOExit.CONTINUE, TAOExit.RETRY):
            overridden = True
            exit_type = TAOExit.CLARIFY
            reason = (
                f"Selected action is high risk ({think.risk_reason}); "
                "switching to clarify instead of executing"
            )
            return self._record(state, exit_type, reason, overridden)

        # Rule 5: retry budget control (task 6.4)
        if exit_type == TAOExit.RETRY:
            last_action = state.last_action()
            if last_action is not None and last_action.status == ActionStatus.FAILED:
                if last_action.retry_count >= self.max_action_retries:
                    overridden = True
                    exit_type = TAOExit.REPLAN
                    reason = (
                        f"Action '{last_action.name}' retried {last_action.retry_count} times "
                        "and still failed; upgrading retry to replan"
                    )
                    return self._record(state, exit_type, reason, overridden)
            else:
                # Nothing to retry: the last action did not fail
                overridden = True
                exit_type = TAOExit.CONTINUE
                reason = "Retry requested but last action did not fail; continuing instead"
                return self._record(state, exit_type, reason, overridden)

        # Rule 6: continue requires at least one advanceable candidate (task 6.2)
        if exit_type == TAOExit.CONTINUE and not state.candidate_actions:
            overridden = True
            exit_type = TAOExit.CLARIFY
            reason = (
                "No candidate action can advance the goal; "
                "choosing clarify instead of idle looping"
            )
            return self._record(state, exit_type, reason, overridden)

        return self._record(state, exit_type, reason, overridden)

    def _check_control_limits(self, state: TAOState) -> tuple[TAOExit, str] | None:
        """Check Control State limits; return forced interrupt when exceeded."""
        if state.control.loops_exceeded():
            return (
                TAOExit.INTERRUPT,
                f"max_loops_exceeded: used {state.control.used_loops}/{state.control.max_loops}",
            )
        if state.control.time_exceeded():
            return (
                TAOExit.INTERRUPT,
                f"max_time_exceeded: exceeded {state.control.max_time}s budget",
            )
        return None

    def _check_dead_loop(
        self, state: TAOState, think: ThinkResult
    ) -> tuple[TAOExit, str] | None:
        """Detect repeated selection of the same action without new information."""
        selected = think.selected_action
        if not selected or think.exit_decision not in (TAOExit.CONTINUE, TAOExit.RETRY):
            return None

        consecutive = 0
        for record in reversed(state.actions):
            if record.name == selected:
                consecutive += 1
            else:
                break

        if consecutive >= self.dead_loop_threshold:
            return (
                TAOExit.CLARIFY,
                (
                    f"Action '{selected}' selected {consecutive} consecutive times; "
                    "treating as a dead loop"
                ),
            )
        return None

    def _check_stagnation(self, state: TAOState) -> tuple[TAOExit, str] | None:
        """Detect lack of real progress over recent rounds."""
        window = self.stagnation_window
        recent_observations = state.observations[-window:]
        if len(recent_observations) < window:
            return None

        any_progress = any(
            obs.progress
            or obs.information_gain.value in ("medium", "high")
            or bool(obs.new_facts)
            or bool(obs.state_changes)
            for obs in recent_observations
        )
        if not any_progress:
            return (
                TAOExit.CLARIFY,
                f"No real progress in the last {window} rounds; requesting clarification",
            )
        return None

    def _record(
        self,
        state: TAOState,
        exit_type: TAOExit,
        reason: str,
        overridden: bool,
    ) -> TAOExitRecord:
        """Build a structured exit record (task 6.8)."""
        last_action = state.last_action()
        last_obs = state.last_observation()
        return TAOExitRecord(
            exit_type=exit_type,
            reason=reason,
            used_loops=state.control.used_loops,
            action_id=last_action.action_id if last_action else "",
            observation_summary=last_obs.summary if last_obs else "",
            overridden=overridden,
        )

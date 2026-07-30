"""TAO engine - main controlled state loop (Think -> Action -> Observation -> update).

The TAO engine drives step-level execution. The Plan defines the macro path;
TAO decides how each concrete step moves forward and interprets feedback.

Structure:
- Inner loop: Think -> Action -> Observation -> state update -> exit decision
- Outer loop (optional, double-layer): supervises goal drift, constraint
  violations and stagnation every N inner rounds (sync) or independently on
  a timer (async)

Exit linkage with XPlan:
- retry: re-execute the failed action via the Action runtime
- replan: delegate to ReplanEngine for the replan exit
- clarify: produce a clarify message (Correction clarify strategy)
- interrupt: mark the run as interrupted (Plan failed/aborted linkage upstream)
"""

import asyncio
import json
import logging
import re
from typing import Any

from xplan.models.plan import Plan
from xplan.models.tao import (
    ActionCandidate,
    ActionStatus,
    InterventionType,
    SupervisorReview,
    TAOExit,
    TAOExitRecord,
    TAOResult,
    TAOState,
    ThinkResult,
)
from xplan.prompts.tao_prompt import (
    build_tao_supervisor_system_prompt,
    build_tao_supervisor_user_prompt,
)
from xplan.engine.tao_action_runtime import (
    IllegalActionError,
    PreconditionError,
    TAOActionRuntime,
)
from xplan.engine.tao_loop_controller import TAOLoopController
from xplan.engine.tao_observation_interpreter import TAOObservationInterpreter
from xplan.engine.tao_think_engine import TAOThinkEngine
from xplan.services.tao_state_manager import TAOStateManager

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Extract JSON from an LLM response (markdown block or bare JSON)."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class TAOEngine:
    """Main TAO execution engine with optional double-layer loop.

    Attributes:
        think_engine: Think decision engine
        action_runtime: Action execution runtime
        observation_interpreter: Observation interpretation engine
        state_manager: TAO state manager
        loop_controller: Exit controller
        replan_engine: Optional ReplanEngine for the replan exit
        llm_service: LLM service (used by the outer supervisor loop)
        supervisor_interval: Trigger the outer loop every N inner rounds (0 disables it)
        supervisor_interval_seconds: Trigger the outer loop asynchronously every N
            seconds; 0 disables async mode
    """

    def __init__(
        self,
        llm_service: Any,
        think_engine: TAOThinkEngine | None = None,
        action_runtime: TAOActionRuntime | None = None,
        observation_interpreter: TAOObservationInterpreter | None = None,
        state_manager: TAOStateManager | None = None,
        loop_controller: TAOLoopController | None = None,
        replan_engine: Any = None,
        constraint_manager: Any = None,
        supervisor_interval: int = 3,
        supervisor_interval_seconds: float = 0.0,
    ) -> None:
        """Initialize the TAO engine.

        Args:
            llm_service: LLM service
            think_engine: Optional Think engine (created when omitted)
            action_runtime: Optional Action runtime (created when omitted)
            observation_interpreter: Optional Observation interpreter (created when omitted)
            state_manager: Optional TAO state manager (created when omitted)
            loop_controller: Optional exit controller (created when omitted)
            replan_engine: Optional ReplanEngine for the replan exit
            constraint_manager: Optional constraint manager
            supervisor_interval: Outer-loop trigger interval in inner rounds;
                0 disables the synchronous outer loop
            supervisor_interval_seconds: Outer-loop trigger interval in seconds
                for asynchronous supervision; 0 disables async mode
        """
        self.llm_service = llm_service
        self.constraint_manager = constraint_manager
        self.think_engine = think_engine or TAOThinkEngine(llm_service, constraint_manager)
        self.action_runtime = action_runtime or TAOActionRuntime()
        self.observation_interpreter = observation_interpreter or TAOObservationInterpreter(llm_service)
        self.state_manager = state_manager or TAOStateManager()
        self.loop_controller = loop_controller or TAOLoopController(
            self.action_runtime.max_retries
        )
        self.replan_engine = replan_engine
        self.supervisor_interval = supervisor_interval
        self.supervisor_interval_seconds = supervisor_interval_seconds
        self.supervisor_reviews: list[SupervisorReview] = []
        self._pending_intervention: asyncio.Queue[SupervisorReview] = asyncio.Queue()
        self._supervisor_task: asyncio.Task[Any] | None = None
        self._supervisor_stop_event: asyncio.Event | None = None

    # ── Main entry ────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        plan: Plan | None = None,
        candidate_actions: list[ActionCandidate] | None = None,
        max_loops: int = 10,
        max_time: float = 300.0,
        supervisor_interval: int | None = None,
        supervisor_interval_seconds: float | None = None,
        action_runtime: TAOActionRuntime | None = None,
    ) -> TAOResult:
        """Run the full TAO loop until an exit other than continue/retry is taken.

        Args:
            user_input: User's goal/request
            plan: Optional G4C Plan providing goal/context anchoring
            candidate_actions: Full candidate action space (coarse-filtered inside)
            max_loops: Maximum inner loop rounds
            max_time: Maximum execution time in seconds
            supervisor_interval: Override the synchronous outer-loop interval
                in inner rounds; uses the engine default when None
            supervisor_interval_seconds: Override the asynchronous outer-loop
                interval in seconds; uses the engine default when None
            action_runtime: Optional per-run Action runtime (uses the engine
                default when None). Useful when each step needs its own
                executor registrations.

        Returns:
            TAOResult with final exit, output and exit history
        """
        runtime = action_runtime or self.action_runtime
        previous_interval = self.supervisor_interval
        previous_interval_seconds = self.supervisor_interval_seconds
        if supervisor_interval is not None:
            self.supervisor_interval = supervisor_interval
        if supervisor_interval_seconds is not None:
            self.supervisor_interval_seconds = supervisor_interval_seconds
        # Exclude actions that failed earlier in this step and are not repeatable
        filtered_candidates = self._exclude_failed_actions(candidate_actions or [])
        state = self.state_manager.initialize(
            user_input=user_input,
            plan=plan,
            candidate_actions=runtime.coarse_filter(
                filtered_candidates, plan=plan
            ),
            max_loops=max_loops,
            max_time=max_time,
        )

        # Store the runtime for this run (used by _execute_round)
        self._current_runtime = runtime
        exit_history: list[TAOExitRecord] = []
        self._start_async_supervisor(state)

        try:
            while True:
                self.state_manager.increment_loop(state)

                # ── Inner loop: Think -> Action -> Observation ────
                think = await self.think_engine.think(state)
                exit_record = self.loop_controller.decide(state, think)
                exit_history.append(exit_record)
                logger.info(
                    "TAO loop %d: exit=%s (overridden=%s), reason=%s",
                    state.control.used_loops,
                    exit_record.exit_type.value,
                    exit_record.overridden,
                    exit_record.reason[:80],
                )

                # ── Execute action when continuing or retrying ────
                if exit_record.exit_type in (TAOExit.CONTINUE, TAOExit.RETRY):
                    await self._execute_round(state, think, exit_record)
                    # Re-decide after execution if the action round itself forced an exit
                    if exit_record.exit_type in (
                        TAOExit.FINISH,
                        TAOExit.CLARIFY,
                        TAOExit.REPLAN,
                        TAOExit.INTERRUPT,
                    ):
                        break
                else:
                    break

                # ── Outer loop supervision (task 7.3, sync trigger) ─
                if (
                    self.supervisor_interval > 0
                    and state.control.used_loops % self.supervisor_interval == 0
                ):
                    review = await self.supervise(state)
                    self.supervisor_reviews.append(review)
                    if review.intervention != InterventionType.NONE:
                        intervention_exit = self._map_intervention(review)
                        exit_history.append(
                            TAOExitRecord(
                                exit_type=intervention_exit,
                                reason=f"Outer loop intervention: {review.reason}",
                                used_loops=state.control.used_loops,
                                overridden=True,
                            )
                        )
                        self.state_manager.set_exit_reason(state, review.reason)
                        return self._build_result(
                            state, intervention_exit, exit_history, think
                        )

                # ── Async outer-loop intervention (task 7.4) ──────
                async_review = self._pop_pending_intervention()
                if async_review is not None:
                    self.supervisor_reviews.append(async_review)
                    intervention_exit = self._map_intervention(async_review)
                    exit_history.append(
                        TAOExitRecord(
                            exit_type=intervention_exit,
                            reason=f"Async outer loop intervention: {async_review.reason}",
                            used_loops=state.control.used_loops,
                            overridden=True,
                        )
                    )
                    self.state_manager.set_exit_reason(state, async_review.reason)
                    return self._build_result(
                        state, intervention_exit, exit_history, think
                    )

            final_exit = exit_history[-1].exit_type
            self.state_manager.set_exit_reason(state, exit_history[-1].reason)
            return self._build_result(state, final_exit, exit_history, think)
        finally:
            self._current_runtime = None
            await self._stop_async_supervisor()
            self.supervisor_interval = previous_interval
            self.supervisor_interval_seconds = previous_interval_seconds

    def _exclude_failed_actions(
        self, candidates: list[ActionCandidate]
    ) -> list[ActionCandidate]:
        """Remove actions that already failed in this step unless repeatable.

        The current implementation tracks failures within the ongoing TAO run
        via the action runtime's availability records. Actions marked as
        disabled by the circuit breaker, or actions explicitly recorded as
        failed and not marked ``repeatable_on_retry``, are excluded from the
        initial candidate space.
        """
        runtime = getattr(self, "_current_runtime", None) or self.action_runtime
        kept: list[ActionCandidate] = []
        for candidate in candidates:
            av = runtime.availability_of(candidate.name)
            if av.disabled:
                continue
            if (
                av.consecutive_failures > 0
                and not candidate.repeatable_on_retry
            ):
                continue
            kept.append(candidate)
        return kept

    # ── Single round execution (task 7.1) ─────────────────────

    async def _execute_round(
        self,
        state: TAOState,
        think: ThinkResult,
        exit_record: TAOExitRecord,
    ) -> None:
        """Execute one Action -> Observation round and update the state.

        Mutates exit_record in place when the round itself forces an exit.
        """
        candidate = next(
            (c for c in state.candidate_actions if c.name == think.selected_action),
            None,
        )
        if candidate is None:
            # Illegal action: reject and force clarify (task 4.8 linkage)
            exit_record.exit_type = TAOExit.CLARIFY
            exit_record.reason = (
                f"Selected action '{think.selected_action}' not in candidate space; "
                "requesting clarification"
            )
            exit_record.overridden = True
            return

        retry_of = state.last_action() if exit_record.exit_type == TAOExit.RETRY else None

        try:
            runtime = getattr(self, "_current_runtime", None) or self.action_runtime
            record = await runtime.execute(
                candidate, think.action_params, state, retry_of=retry_of
            )
        except (IllegalActionError, PreconditionError) as e:
            exit_record.exit_type = TAOExit.CLARIFY
            exit_record.reason = str(e)
            exit_record.overridden = True
            return

        self.state_manager.record_action(state, record)
        exit_record.action_id = record.action_id

        # Interpret the raw output (task 5.x)
        observation = await self.observation_interpreter.interpret(state, record)
        self.state_manager.record_observation(state, observation)
        # Write extracted facts into Fact State (task 5.6)
        self.state_manager.apply_observation_facts(state, observation)
        exit_record.observation_summary = observation.summary

        # Retry exit: the retried action ran; downgrade to continue for the next round
        if exit_record.exit_type == TAOExit.RETRY:
            exit_record.exit_type = TAOExit.CONTINUE

        # Goal progress bookkeeping
        if think.current_goal_completed:
            self.state_manager.mark_current_goal_completed(state)

    # ── Outer loop supervision (tasks 7.2, 7.5) ───────────────

    async def supervise(self, state: TAOState) -> SupervisorReview:
        """Run one outer-loop supervision review.

        Checks goal drift, constraint violations, stagnation and cascading
        errors. Falls back to a code-only stagnation check when the LLM call
        fails.

        Args:
            state: Current TAO state

        Returns:
            SupervisorReview
        """
        hard: list[str] = []
        if self.constraint_manager is not None:
            try:
                hard = list(self.constraint_manager.get_hard_constraints())
            except AttributeError:
                hard = []

        try:
            raw = await self.llm_service.chat(
                build_tao_supervisor_system_prompt(hard),
                build_tao_supervisor_user_prompt(state),
                response_format={"type": "json_object"},
            )
            data = _extract_json(raw)
            intervention_raw = str(data.get("intervention", "none")).lower()
            try:
                intervention = InterventionType(intervention_raw)
            except ValueError:
                intervention = InterventionType.NONE
            return SupervisorReview(
                goal_drift=bool(data.get("goal_drift", False)),
                drift_explanation=str(data.get("drift_explanation", "")),
                constraint_violations=[
                    str(v) for v in data.get("constraint_violations", []) or []
                ],
                stagnation=bool(data.get("stagnation", False)),
                intervention=intervention,
                reason=str(data.get("reason", "")),
                raw_response=raw,
            )
        except Exception as e:
            logger.warning("Supervisor LLM review failed, using code-only check: %s", e)
            stagnation = self.observation_interpreter.detect_stagnation(state)
            return SupervisorReview(
                stagnation=stagnation,
                intervention=InterventionType.REPLAN if stagnation else InterventionType.NONE,
                reason=(
                    "Code-only stagnation check: no progress in recent rounds"
                    if stagnation
                    else f"Supervisor unavailable ({e}); no intervention"
                ),
            )

    @staticmethod
    def _map_intervention(review: SupervisorReview) -> TAOExit:
        """Map an outer-loop intervention to a TAO exit."""
        mapping = {
            InterventionType.REPLAN: TAOExit.REPLAN,
            InterventionType.CLARIFY: TAOExit.CLARIFY,
            InterventionType.INTERRUPT: TAOExit.INTERRUPT,
        }
        return mapping.get(review.intervention, TAOExit.INTERRUPT)

    # ── Async outer-loop supervision (task 7.4) ───────────────

    def _start_async_supervisor(self, state: TAOState) -> None:
        """Start the asynchronous outer-loop supervisor task if configured.

        The supervisor runs independently of the inner loop and posts
        intervention decisions to ``_pending_intervention``.
        """
        if self.supervisor_interval_seconds <= 0:
            return
        self._supervisor_stop_event = asyncio.Event()
        self._supervisor_task = asyncio.create_task(
            self._async_supervisor_loop(state)
        )
        logger.info(
            "Started async TAO supervisor (interval=%.1fs)",
            self.supervisor_interval_seconds,
        )

    async def _stop_async_supervisor(self) -> None:
        """Stop and clean up the asynchronous supervisor task."""
        if self._supervisor_stop_event is not None:
            self._supervisor_stop_event.set()
        if self._supervisor_task is not None and not self._supervisor_task.done():
            try:
                self._supervisor_task.cancel()
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:  # pragma: no cover - defensive cleanup
                logger.warning("Error stopping async supervisor: %s", e)
        self._supervisor_task = None
        self._supervisor_stop_event = None

    async def _async_supervisor_loop(self, state: TAOState) -> None:
        """Independent supervisor loop that periodically reviews the state.

        Uses a snapshot of the current state so the review itself does not
        block or mutate the running inner loop. Interventions are queued for
        the inner loop to consume between rounds.
        """
        stop_event = self._supervisor_stop_event
        assert stop_event is not None
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.supervisor_interval_seconds
                )
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break

            try:
                review = await self.supervise(state)
                self.supervisor_reviews.append(review)
                if review.intervention != InterventionType.NONE:
                    await self._pending_intervention.put(review)
                    logger.info(
                        "Async supervisor queued intervention: %s", review.intervention.value
                    )
                    break
            except Exception as e:
                logger.warning("Async supervisor review failed: %s", e)

    def _pop_pending_intervention(self) -> SupervisorReview | None:
        """Non-blocking check for an asynchronously queued intervention."""
        if self._pending_intervention.empty():
            return None
        try:
            return self._pending_intervention.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ── Result building ───────────────────────────────────────

    def _build_result(
        self,
        state: TAOState,
        final_exit: TAOExit,
        exit_history: list[TAOExitRecord],
        think: ThinkResult,
    ) -> TAOResult:
        """Build the final TAOResult."""
        final_output = ""
        clarify_message = ""

        if final_exit == TAOExit.FINISH:
            last_obs = state.last_observation()
            final_output = (
                last_obs.summary
                if last_obs and last_obs.summary
                else f"Goal achieved: {state.goal_state.final_goal}"
            )
        elif final_exit == TAOExit.CLARIFY:
            missing = think.missing_slots or state.missing_slots()
            clarify_message = think.reason or (
                f"Missing critical information: {', '.join(missing)}"
                if missing
                else "Clarification needed to proceed"
            )

        return TAOResult(
            exit_type=final_exit,
            final_output=final_output,
            clarify_message=clarify_message,
            exit_reason=exit_history[-1].reason if exit_history else "",
            used_loops=state.control.used_loops,
            total_actions=len(state.actions),
            exit_history=exit_history,
            state=state,
        )

"""Plan orchestrator - Main orchestration engine for the full plan lifecycle.

This is the main entry point that coordinates all G4C subsystems:

    ┌─────────────────────────────────────────────────────────────────┐
    │                    POST /api/plan/run                           │
    │                      PlanOrchestrator                          │
    │                                                                 │
    │  Phase 1: Generate Plan                                         │
    │    ├── PlanGenerator.generate()          [G4C generation]       │
    │    └── IterationLoop.run()              [generate-verify-correct]│
    │                                                                 │
    │  Phase 2: Verify Plan (optional)                                │
    │    └── PlanVerifier.verify()            [G4C 5-dimension score] │
    │                                                                 │
    │  Phase 3: Execute Plan (step by step)                          │
    │    for each step:                                               │
    │      ├── PlanExecutor.execute_step()    [execute step]          │
    │      ├── PlanExecutor.run_checkpoint()  [verify output]         │
    │      │   if checkpoint FAILS:                                   │
    │      │     ├── FailureTracer.trace()    [find root cause]       │
    │      │     ├── TrustStateManager         [mark Invalid/Dirty]   │
    │      │     ├── BacktrackingEngine        [progressive expand]   │
    │      │     │   ├── action: retry                               │
    │      │     │   ├── step: switch candidate path                 │
    │      │     │   ├── stage: rollback                             │
    │      │     │   └── global: ReplanEngine / TCCReplan             │
    │      │     └── ReplanEvaluator.record() [record event]         │
    │      └── (continue or abort)                                   │
    │                                                                 │
    │  Phase 4: Return OrchestratorResult                            │
    └─────────────────────────────────────────────────────────────────┘
"""

import time
import logging
from typing import Any, Callable

from xtao.models import Plan
from xtao.models.plan import PlanStatus
from xtao.models.orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    StepExecutionRecord,
)
from xtao.engine.plan_generator import PlanGenerator
from xtao.engine.plan_verifier import PlanVerifier
from xtao.engine.plan_executor import PlanExecutor
from xtao.engine.iteration_loop import IterationLoop
from xtao.engine.correction_handler import CorrectionHandler
from xtao.engine.replan_engine import ReplanEngine
from xtao.engine.failure_tracer import FailureTracer
from xtao.engine.backtracking_engine import BacktrackingEngine
from xtao.services.trust_state_manager import TrustStateManager
from xtao.services.candidate_path_manager import CandidatePathManager

logger = logging.getLogger(__name__)


class PlanOrchestrator:
    """Main orchestration engine for the full plan lifecycle.

    Coordinates all G4C subsystems: generation, verification, execution,
    failure tracing, trust state management, backtracking, replan, and evaluation.

    This is the single entry point that ties together all individual modules.
    """

    def __init__(
        self,
        llm_service: Any,
        rag_service: Any = None,
        constraint_manager: Any = None,
        replan_engine: Any = None,
        tcc_replan: Any = None,
        failure_tracer: Any = None,
        backtracking_engine: Any = None,
        trust_state_manager: Any = None,
        candidate_path_manager: Any = None,
        replan_evaluator: Any = None,
        tao_engine: Any = None,
    ):
        """Initialize the orchestrator with all subsystem dependencies.

        Args:
            llm_service: LLM service for all LLM calls
            rag_service: RAG service for knowledge retrieval (optional)
            constraint_manager: Constraint manager for hard/soft constraints
            replan_engine: Replan engine for controlled correction
            tcc_replan: TCC Replan engine for high-risk scenarios
            failure_tracer: Failure tracer for root cause localization
            backtracking_engine: Backtracking engine for progressive expansion
            trust_state_manager: Trust state manager for intermediate results
            candidate_path_manager: Candidate path manager for path switching
            replan_evaluator: Replan evaluator for effectiveness metrics
            tao_engine: TAO engine for step-level state-loop execution (optional)
        """
        self.llm_service = llm_service
        self.constraint_manager = constraint_manager
        self.replan_engine = replan_engine
        self.tcc_replan = tcc_replan
        self.failure_tracer = failure_tracer
        self.backtracking_engine = backtracking_engine
        self.trust_state_manager = trust_state_manager
        self.candidate_path_manager = candidate_path_manager
        self.replan_evaluator = replan_evaluator
        self.tao_engine = tao_engine

        # Create internal engine instances (with shared LLM service)
        self.plan_generator = PlanGenerator(llm_service, rag_service)
        self.plan_verifier = PlanVerifier(llm_service)
        self.plan_executor = PlanExecutor(llm_service, constraint_manager)
        self.correction_handler = CorrectionHandler(
            llm_service,
            plan_generator=self.plan_generator,
            replan_engine=replan_engine,
        )

    @staticmethod
    def _emit(on_progress: Callable[[dict], None] | None, event: dict) -> None:
        """Safely emit a progress event to the callback (no-op if absent)."""
        if on_progress is not None:
            try:
                on_progress(event)
            except Exception:
                logger.debug("progress callback failed", exc_info=True)

    async def run(
        self,
        user_input: str,
        conversation_history: str = "",
        config: OrchestratorConfig | None = None,
        on_progress: Callable[[dict], None] | None = None,
    ) -> OrchestratorResult:
        """Run the full plan lifecycle: generate -> verify -> execute -> correct.

        This is the main orchestration method that ties together all subsystems.

        Args:
            user_input: User's goal/request
            conversation_history: Conversation history for context
            config: Orchestration configuration (uses defaults if None)
            on_progress: Optional sync callback receiving progress events
                (phase / plan_generated / step_* / checkpoint / replan / done / error).
                Used by the streaming endpoint to push SSE events to the client.

        Returns:
            OrchestratorResult with final plan, execution trace, and metrics
        """
        if config is None:
            config = OrchestratorConfig()

        errors: list[str] = []
        start_time = time.time()
        timings: dict[str, int] = {}

        try:
            # ── Phase 1: Generate Plan ──────────────────────────────
            logger.info("Phase 1: Generating Plan")
            t0 = time.time()
            self._emit(on_progress, {"type": "phase", "phase": "generate", "message": "正在生成 Plan…"})
            plan, verification_results = await self._generate_plan(
                user_input, conversation_history, config, on_progress=on_progress
            )
            gen_ms = int((time.time() - t0) * 1000)
            timings["generate_ms"] = gen_ms
            self._emit(on_progress, {"type": "plan_generated", "plan": plan.model_dump(), "elapsed_ms": gen_ms})

            iteration_count = plan.iteration_count
            verification_score = None
            verification_passed = None

            # ── Phase 2: Verify Plan (optional) ─────────────────────
            if config.verify_before_execute and verification_results:
                logger.info("Phase 2: Verifying Plan")
                t1 = time.time()
                last_result = verification_results[-1]
                verification_score = last_result.score if hasattr(last_result, "score") else None
                verification_passed = (
                    self.plan_verifier.is_passing(last_result, config.verification_threshold)
                    if verification_score is not None
                    else None
                )
                verify_ms = int((time.time() - t1) * 1000)
                timings["verify_ms"] = verify_ms
                self._emit(on_progress, {
                    "type": "phase",
                    "phase": "verify",
                    "score": verification_score,
                    "passed": verification_passed,
                    "elapsed_ms": verify_ms,
                })

                if verification_passed is False:
                    logger.warning("Plan verification failed (score=%.2f), proceeding anyway", verification_score)

            # ── Phase 3: Execute Plan ───────────────────────────────
            logger.info("Phase 3: Executing Plan")
            total_steps = len(plan.choice.steps)
            t2 = time.time()
            self._emit(on_progress, {"type": "phase", "phase": "execute", "total_steps": total_steps})
            step_records: list[StepExecutionRecord] = []
            replan_count = 0

            try:
                plan, step_records, replan_count = await self._execute_with_correction(
                    plan, config, errors, on_progress=on_progress
                )
            except Exception as e:
                errors.append(f"Execution error: {e}")
                plan.status = PlanStatus.FAILED

            timings["execute_ms"] = int((time.time() - t2) * 1000)

            # ── Phase 4: Build result ───────────────────────────────
            duration_ms = int((time.time() - start_time) * 1000)

            # Determine final status and extract clarify message from step records
            clarify_message: str | None = None
            if plan.status == PlanStatus.COMPLETED:
                final_status = "completed"
            elif plan.status == PlanStatus.ABORTED:
                final_status = "aborted"
            elif plan.status == PlanStatus.FAILED:
                final_status = "failed"
            else:
                final_status = "failed"

            # Extract clarify message from the first clarify-type step record
            if final_status == "failed" and step_records:
                for rec in step_records:
                    if rec.correction_applied == "clarify" and rec.output:
                        clarify_message = rec.output
                        final_status = "clarify_needed"
                        break

            result = OrchestratorResult(
                plan=plan,
                status=final_status,
                step_records=step_records,
                replan_count=replan_count,
                iteration_count=iteration_count,
                verification_score=verification_score,
                verification_passed=verification_passed,
                errors=errors,
                clarify_message=clarify_message,
            )

            logger.info(
                "Orchestration complete: status=%s, steps=%d, replans=%d, duration=%dms, timings=%s",
                final_status, len(step_records), replan_count, duration_ms, timings,
            )
            self._emit(on_progress, {"type": "done", "result": result.model_dump(), "timings": timings, "total_ms": duration_ms})
            return result
        except Exception as e:
            self._emit(on_progress, {"type": "error", "message": str(e)})
            raise

    async def _generate_plan(
        self,
        user_input: str,
        conversation_history: str,
        config: OrchestratorConfig,
        on_progress: Callable[[dict], None] | None = None,
    ) -> tuple[Plan, list]:
        """Phase 1: Generate Plan using G4C methodology.

        If use_iteration is enabled, uses the generate-verify-correct loop.
        Otherwise, generates a single plan directly.

        Returns:
            Tuple of (Plan, list of verification results)
        """
        if config.use_iteration:
            loop = IterationLoop(
                self.plan_generator,
                self.plan_verifier,
                max_iterations=config.max_iterations,
            )
            plan, results = await loop.run(user_input, conversation_history)
            return plan, results
        else:
            plan = await self.plan_generator.generate(
                user_input, conversation_history, on_progress=on_progress
            )
            return plan, []

    async def _execute_with_correction(
        self,
        plan: Plan,
        config: OrchestratorConfig,
        errors: list[str],
        on_progress: Callable[[dict], None] | None = None,
    ) -> tuple[Plan, list[StepExecutionRecord], int]:
        """Phase 3: Execute plan step by step with full correction pipeline.

        For each step:
        1. Execute the step
        2. Run checkpoint
        3. If checkpoint fails:
           a. Trace failure (find root cause) - FailureTracer
           b. Update trust states - TrustStateManager
           c. Progressive backtracking - BacktrackingEngine
           d. If global replan needed, execute ReplanEngine or TCCReplan
           e. Record replan event for evaluation

        Returns:
            Tuple of (final Plan, step records, replan count)
        """
        plan.status = PlanStatus.RUNNING
        step_records: list[StepExecutionRecord] = []
        replan_count = 0
        max_replans = config.max_replan_count

        i = 0
        while i < len(plan.choice.steps):
            step = plan.choice.steps[i]
            plan.current_step_index = i
            step.status = "running"
            step_t0 = time.time()

            record = StepExecutionRecord(
                step_id=step.id,
                step_objective=step.objective,
                status="running",
            )
            self._emit(on_progress, {
                "type": "step_start",
                "index": i,
                "total": len(plan.choice.steps),
                "step_id": step.id,
                "objective": step.objective,
                "tao": bool(config.use_tao and self.tao_engine is not None),
            })

            # Execute step (via TAO loop when enabled)
            tao_result = None
            try:
                exec_t0 = time.time()
                if config.use_tao and self.tao_engine is not None:
                    record.tao_used = True
                    output, tao_result = await self._execute_step_via_tao(step, plan, config)
                    record.tao_loops = tao_result.used_loops
                    record.tao_exit = tao_result.exit_type.value
                elif on_progress is not None:
                    # Streaming path: yield token deltas to the client as the
                    # LLM generates the step output, then keep the full text.
                    content_chunks: list[str] = []
                    async for chunk in self.plan_executor.execute_step_stream(step, plan):
                        kind = chunk.get("type", "content")
                        text = chunk.get("text", "")
                        if kind == "reasoning":
                            self._emit(on_progress, {
                                "type": "step_reasoning_delta",
                                "step_id": step.id,
                                "delta": text,
                            })
                        else:
                            content_chunks.append(text)
                            self._emit(on_progress, {
                                "type": "step_output_delta",
                                "step_id": step.id,
                                "delta": text,
                            })
                    output = "".join(content_chunks)
                else:
                    output = await self.plan_executor.execute_step(step, plan)
                exec_ms = int((time.time() - exec_t0) * 1000)
                record.output = output[:4000]  # Truncate for storage
                self._emit(on_progress, {
                    "type": "step_output",
                    "step_id": step.id,
                    "output": record.output,
                    "tao_used": record.tao_used,
                    "tao_loops": record.tao_loops,
                    "elapsed_ms": exec_ms,
                })
            except Exception as e:
                errors.append(f"Step {step.id} execution error: {e}")
                record.status = "failed"
                record.output = str(e)[:200]
                step.status = "failed"
                step_records.append(record)

                # Treat execution error as checkpoint failure
                if replan_count < max_replans:
                    plan, replan_count = await self._handle_failure(
                        plan, step, record, str(e), config, errors, replan_count
                    )
                    if plan.status in (PlanStatus.ABORTED, PlanStatus.FAILED):
                        return plan, step_records, replan_count
                    # After replan, restart from beginning of new plan
                    i = 0
                    continue
                else:
                    plan.status = PlanStatus.FAILED
                    return plan, step_records, replan_count

            # ── TAO exit handling (task 9.5) ──────────────────
            if tao_result is not None:
                from xtao.models.tao import TAOExit

                if tao_result.exit_type == TAOExit.REPLAN:
                    # TAO found the need to replan; delegate to ReplanEngine
                    previous_count = replan_count
                    plan, replan_count = await self._handle_failure(
                        plan, step, record,
                        tao_result.exit_reason or "TAO requested replan",
                        config, errors, replan_count,
                    )
                    if replan_count > previous_count:
                        record.replan_triggered = True
                    if plan.status in (PlanStatus.ABORTED, PlanStatus.FAILED):
                        step_records.append(record)
                        return plan, step_records, replan_count
                    step.status = "done"
                    record.status = "done"
                    step_records.append(record)
                    i = 0
                    continue

                if tao_result.exit_type == TAOExit.CLARIFY:
                    # Map to the clarify correction strategy
                    plan.status = PlanStatus.FAILED
                    record.status = "failed"
                    record.correction_applied = "clarify"
                    record.output = tao_result.clarify_message[:500]
                    errors.append(f"Step {step.id} needs clarification: {tao_result.clarify_message[:200]}")
                    step_records.append(record)
                    return plan, step_records, replan_count

                if tao_result.exit_type == TAOExit.INTERRUPT:
                    record.status = "failed"
                    step.status = "failed"
                    step_records.append(record)
                    if replan_count < max_replans:
                        plan, replan_count = await self._handle_failure(
                            plan, step, record,
                            tao_result.exit_reason or "TAO interrupted",
                            config, errors, replan_count,
                        )
                        if plan.status in (PlanStatus.ABORTED, PlanStatus.FAILED):
                            return plan, step_records, replan_count
                        i = 0
                        continue
                    plan.status = PlanStatus.FAILED
                    return plan, step_records, replan_count

            # Run checkpoint (skippable for faster execution)
            checkpoint = None if config.skip_checkpoint else self.plan_executor._find_checkpoint(plan, step.id)
            if checkpoint:
                ck_t0 = time.time()
                try:
                    results = await self.plan_executor.run_checkpoint(checkpoint, output, plan)
                    plan.check_results.extend(results)
                    record.checkpoint_results = [r.model_dump() for r in results]
                    record.checkpoint_passed = all(r.passed for r in results)
                except Exception as e:
                    errors.append(f"Step {step.id} checkpoint error: {e}")
                    record.checkpoint_passed = False
                    record.checkpoint_results = [{"error": str(e)[:200]}]
                    results = []

                ck_ms = int((time.time() - ck_t0) * 1000)
                self._emit(on_progress, {
                    "type": "checkpoint",
                    "step_id": step.id,
                    "passed": record.checkpoint_passed,
                    "elapsed_ms": ck_ms,
                })

                # Handle checkpoint failure
                if not record.checkpoint_passed:
                    # Find matching correction rule
                    correction = await self.plan_executor._find_matching_correction(plan, results)

                    if correction:
                        record.correction_applied = correction.action.type.value

                        # ── Failure Tracing ──────────────────────────
                        if config.enable_failure_tracing and self.failure_tracer:
                            try:
                                trace_result = await self.failure_tracer.trace(
                                    plan=plan,
                                    failure_step_id=step.id,
                                    failure_info=record.output[:200],
                                    step_records=[],
                                )
                                record.failure_traced = True
                                if trace_result.root_cause_point:
                                    record.root_cause_step_id = trace_result.root_cause_point.step_id
                                logger.info(
                                    "Failure traced: failure=%s, root_cause=%s",
                                    step.id,
                                    record.root_cause_step_id,
                                )
                            except Exception as e:
                                errors.append(f"Failure tracing error: {e}")

                        # ── Trust State Update ───────────────────────
                        if config.enable_trust_state and self.trust_state_manager:
                            try:
                                # Mark the failed step's output as invalid
                                fact_key = f"step_{step.id}_output"
                                if self.trust_state_manager.get_fact(fact_key):
                                    self.trust_state_manager.update_trust_state(
                                        fact_key, "invalid", f"Checkpoint failed at step {step.id}"
                                    )
                                    logger.info("Marked %s as INVALID (cascade marking)", fact_key)
                            except Exception as e:
                                errors.append(f"Trust state update error: {e}")

                        # ── Progressive Backtracking ─────────────────
                        if config.enable_progressive_backtracking and self.backtracking_engine:
                            try:
                                bt_result = await self.backtracking_engine.progressive_expansion(
                                    plan, Exception(record.output[:200]), None
                                )
                                if bt_result:
                                    record.backtracking_level = bt_result.level.value
                                    logger.info("Backtracking level: %s", bt_result.level.value)
                            except Exception as e:
                                errors.append(f"Backtracking error: {e}")

                        # ── Execute Correction ───────────────────────
                        if replan_count < max_replans:
                            plan, did_replan = await self._execute_correction(
                                plan, correction, record, config, errors
                            )
                            if did_replan:
                                replan_count += 1
                                record.replan_triggered = True
                                self._emit(on_progress, {
                                    "type": "replan",
                                    "step_id": step.id,
                                    "count": replan_count,
                                    "correction": record.correction_applied,
                                })

                                # ── Record Replan Event ──────────────────
                                if self.replan_evaluator:
                                    self._record_replan_event(plan, step, record, replan_count)

                                if plan.status in (PlanStatus.ABORTED, PlanStatus.FAILED):
                                    step_records.append(record)
                                    return plan, step_records, replan_count

                                # Restart from beginning after replan
                                step.status = "done"
                                step_records.append(record)
                                i = 0
                                continue
                        else:
                            errors.append(f"Max replan count ({max_replans}) reached, aborting")
                            plan.status = PlanStatus.FAILED
                            step.status = "failed"
                            record.status = "failed"
                            step_records.append(record)
                            return plan, step_records, replan_count

                    else:
                        # No matching correction rule
                        errors.append(f"No matching correction rule for step {step.id}")
                        step.status = "failed"
                        record.status = "failed"
                        plan.status = PlanStatus.FAILED
                        step_records.append(record)
                        return plan, step_records, replan_count

            # Step completed successfully
            step.status = "done"
            record.status = "done"
            step_records.append(record)
            self._emit(on_progress, {
                "type": "step_done",
                "step_id": step.id,
                "status": "done",
                "checkpoint_passed": record.checkpoint_passed,
                "elapsed_ms": int((time.time() - step_t0) * 1000),
            })

            # ── Trust State: mark step output as available ───────
            if config.enable_trust_state and self.trust_state_manager:
                try:
                    self.trust_state_manager.add_fact(
                        key=f"step_{step.id}_output",
                        value=output[:200],
                        evidence=f"checkpoint_passed: {record.checkpoint_passed}",
                        source_step_id=step.id,
                    )
                except Exception:
                    pass  # Non-critical

            i += 1

        # All steps completed
        plan.status = PlanStatus.COMPLETED
        plan.current_step_index = len(plan.choice.steps) - 1
        return plan, step_records, replan_count

    async def _execute_step_via_tao(
        self,
        step: Any,
        plan: Plan,
        config: OrchestratorConfig,
    ) -> tuple[str, Any]:
        """Execute a Plan step via the TAO controlled state loop.

        The Plan step objective becomes the TAO current goal; a default
        candidate space is built around an `execute_step` action whose executor
        delegates to the standard PlanExecutor logic.

        Args:
            step: Plan step to execute
            plan: Current Plan
            config: Orchestrator configuration with TAO settings

        Returns:
            Tuple of (step output text, TAOResult)
        """
        from xtao.models.tao import ActionCandidate, ActionType, TAOExit
        from xtao.engine.tao_action_runtime import TAOActionRuntime

        async def _execute_step(params: dict) -> str:
            return await self.plan_executor.execute_step(step, plan)

        # Create a fresh runtime per step to avoid executor name collisions
        # across steps and to keep preconditions isolated.
        runtime = TAOActionRuntime()
        runtime.register_executor("execute_step", _execute_step)
        # Copy user interaction handler from the shared engine runtime so
        # ask_user works when a handler is registered on the engine.
        if self.tao_engine.action_runtime._user_handler is not None:
            runtime.register_user_interaction_handler(
                self.tao_engine.action_runtime._user_handler
            )

        candidates = [
            ActionCandidate(
                name="execute_step",
                type=ActionType.TOOL_CALL,
                description=f"Execute plan step '{step.id}': {step.objective}",
                rollbackable=True,
            ),
        ]
        # Only offer ask_user when an interaction handler is registered
        if runtime._user_handler is not None:
            candidates.append(
                ActionCandidate(
                    name="ask_user",
                    type=ActionType.USER_INTERACTION,
                    description="Ask the user for missing information",
                    rollbackable=True,
                )
            )

        # Create a per-step TAOEngine that uses the fresh runtime so executor
        # registrations do not leak across steps.
        from xtao.engine.tao_engine import TAOEngine
        step_engine = TAOEngine(
            llm_service=self.tao_engine.llm_service,
            think_engine=self.tao_engine.think_engine,
            action_runtime=runtime,
            observation_interpreter=self.tao_engine.observation_interpreter,
            state_manager=self.tao_engine.state_manager,
            loop_controller=self.tao_engine.loop_controller,
            replan_engine=self.tao_engine.replan_engine,
            constraint_manager=self.tao_engine.constraint_manager,
            supervisor_interval=0,  # per-step supervisor handled by orchestrator
            supervisor_interval_seconds=0,
        )
        tao_result = await step_engine.run(
            user_input=step.objective,
            plan=plan,
            candidate_actions=candidates,
            max_loops=config.tao_max_loops,
            max_time=config.tao_max_time,
        )

        if tao_result.exit_type == TAOExit.FINISH:
            output = tao_result.final_output
        else:
            # Surface the exit reason as output for upstream handling
            last_action = tao_result.state.last_action() if tao_result.state else None
            if last_action is not None and last_action.output is not None:
                output = str(last_action.output)
            else:
                output = tao_result.exit_reason
        return output, tao_result

    async def _execute_correction(
        self,
        plan: Plan,
        correction: Any,
        record: StepExecutionRecord,
        config: OrchestratorConfig,
        errors: list[str],
    ) -> tuple[Plan, bool]:
        """Execute a correction action.

        Delegates to CorrectionHandler for standard corrections (retry/clarify/rollback/abort).
        For REPLAN, uses ReplanEngine or TCCReplan if available.

        Returns:
            Tuple of (updated Plan, whether replan was triggered)
        """
        from xtao.models import CorrectionType

        # For REPLAN, prefer ReplanEngine or TCCReplan
        if correction.action.type == CorrectionType.REPLAN:
            error_info = correction.action.message or "checkpoint failed"

            # Use TCC Replan for high-risk scenarios
            if config.enable_tcc_replan and self.tcc_replan:
                try:
                    tcc_result = await self.tcc_replan.run(plan)
                    if tcc_result.new_plan:
                        logger.info("TCC Replan successful, new plan generated")
                        return tcc_result.new_plan, True
                    elif tcc_result.phase == "cancel":
                        logger.warning("TCC Replan cancelled, falling back to standard replan")
                except Exception as e:
                    errors.append(f"TCC Replan error: {e}")

            # Use ReplanEngine for controlled correction
            if self.replan_engine:
                try:
                    new_plan = await self.replan_engine.run(
                        plan=plan,
                        error=Exception(error_info),
                        user_input="",
                        conversation_history="",
                    )
                    new_plan.status = PlanStatus.RUNNING
                    return new_plan, True
                except Exception as e:
                    errors.append(f"Replan engine error: {e}")

            # Fall back to CorrectionHandler
            plan = await self.correction_handler.handle(correction, plan)
            return plan, True

        else:
            # Standard correction: retry/clarify/rollback/abort
            plan = await self.correction_handler.handle(correction, plan)
            return plan, False

    async def _handle_failure(
        self,
        plan: Plan,
        step: Any,
        record: StepExecutionRecord,
        error_msg: str,
        config: OrchestratorConfig,
        errors: list[str],
        replan_count: int,
    ) -> tuple[Plan, int]:
        """Handle a step execution failure (not checkpoint failure).

        When a step itself throws an error, this method decides whether to
        retry, replan, or abort.

        Returns:
            Tuple of (updated Plan, updated replan count)
        """
        from xtao.models import Correction, CorrectionAction, CorrectionType

        # Create a replan correction
        correction = Correction(
            condition=f"Step {step.id} execution failed: {error_msg[:100]}",
            action=CorrectionAction(
                type=CorrectionType.REPLAN,
                message=error_msg[:200],
            ),
        )
        record.correction_applied = "replan"

        plan, did_replan = await self._execute_correction(plan, correction, record, config, errors)
        if did_replan:
            replan_count += 1
            record.replan_triggered = True

            if self.replan_evaluator:
                self._record_replan_event(plan, step, record, replan_count)

        return plan, replan_count

    def _record_replan_event(self, plan: Plan, step: Any, record: StepExecutionRecord, replan_count: int):
        """Record a replan event for effectiveness evaluation."""
        if not self.replan_evaluator:
            return

        from xtao.models import ReplanEvent

        event = ReplanEvent(
            event_id=f"replan-{replan_count}-{step.id}",
            timestamp="",
            plan_id=getattr(plan, "id", "unknown"),
            trigger="checkpoint_failure",
            failure_step_id=step.id,
            root_cause_step_id=record.root_cause_step_id or step.id,
            replan_start_step_id=step.id,
            total_results=len(plan.check_results),
            trusted_results=len([r for r in plan.check_results if r.passed]),
            reused_results=0,
            recovered=False,
            path_history=[],
        )
        self.replan_evaluator.record_event(event)
        logger.info("Recorded replan event: %s", event.event_id)

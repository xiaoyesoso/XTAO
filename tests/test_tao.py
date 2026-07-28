"""TAO / ReAct unit and integration tests.

Covers:
- TAO data models (12.1)
- Think engine with mocked LLM (12.2)
- Action runtime with mocked executors (12.3)
- Observation interpreter with mocked LLM (12.4)
- Loop exit controller (12.5)
- Double-layer TAO loop including async supervisor (12.6)
- TAO + PlanExecutor integration (12.7)
"""

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

from xplan.models import (
    ActionCandidate,
    ActionRecord,
    ActionStatus,
    ActionType,
    ControlState,
    ExecutionStatus,
    FactCategory,
    FactItem,
    GoalState,
    InformationGain,
    Observation,
    ObservationFact,
    Plan,
    RiskLevel,
    TAOExit,
    TAOExitRecord,
    TAOResult,
    TAOState,
    ThinkResult,
)
from xplan.models.choice import Choice, Step
from xplan.models.goal import Goal
from xplan.engine.tao_engine import TAOEngine
from xplan.engine.tao_think_engine import TAOThinkEngine
from xplan.engine.tao_action_runtime import (
    IllegalActionError,
    PreconditionError,
    TAOActionRuntime,
)
from xplan.engine.tao_observation_interpreter import TAOObservationInterpreter
from xplan.engine.tao_loop_controller import TAOLoopController
from xplan.services.tao_state_manager import TAOStateManager


# ── Helpers ─────────────────────────────────────────────────


class FakeLLMService:
    """Deterministic fake LLM service for tests."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[str, str]] = []
        self.index = 0

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.index < len(self.responses):
            response = self.responses[self.index]
            self.index += 1
            return response
        return "{}"


def build_think_response(
    selected_action: str = "read_report",
    exit_decision: str = "continue",
    risk_level: str = "low",
    missing_slots: list[str] | None = None,
    reason: str = "test reason",
) -> str:
    return json.dumps(
        {
            "current_goal": "read report",
            "success_criteria_satisfied": False,
            "current_goal_completed": False,
            "facts_sufficient": False,
            "missing_slots": missing_slots or [],
            "unverified_assumptions": [],
            "fact_conflicts": [],
            "selected_action": selected_action,
            "action_params": {},
            "should_stop": exit_decision != "continue",
            "exit_decision": exit_decision,
            "reason": reason,
            "risk_level": risk_level,
            "risk_reason": "",
        }
    )


def build_observation_response(
    status: str = "success",
    progress: bool = True,
    facts: list[dict[str, Any]] | None = None,
) -> str:
    return json.dumps(
        {
            "execution_status": status,
            "new_facts": facts or [],
            "missing_information": [],
            "state_changes": ["report loaded"],
            "anomalies": [],
            "suggested_next_action": "",
            "progress": progress,
            "information_gain": "high",
            "summary": "observation summary",
        }
    )


# ── 12.1 TAO data model tests ───────────────────────────────


class TestTAOModels:
    """TAO data model tests."""

    def test_goal_state(self):
        """GoalState tracks final goal, current goal and success criteria."""
        gs = GoalState(
            final_goal="optimize resume",
            current_goal="read resume",
            success_criteria=["quantified results"],
        )
        assert gs.final_goal == "optimize resume"
        assert not gs.current_goal_completed

    def test_control_state_limits(self):
        """ControlState detects loop and time limits."""
        cs = ControlState(max_loops=2, max_time=1.0)
        cs.used_loops = 2
        assert cs.loops_exceeded()
        cs.used_loops = 1
        assert not cs.loops_exceeded()

    def test_tao_state_last_action_and_observation(self):
        """TAOState exposes last action and observation helpers."""
        action = ActionRecord(name="a1", status=ActionStatus.DONE)
        obs = Observation(action_id=action.action_id)
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            actions=[action],
            observations=[obs],
        )
        assert state.last_action() is action
        assert state.last_observation() is obs

    def test_tao_exit_record(self):
        """TAOExitRecord captures exit metadata."""
        record = TAOExitRecord(exit_type=TAOExit.FINISH, reason="done")
        assert record.exit_type == TAOExit.FINISH
        assert not record.overridden

    def test_think_result_validation(self):
        """ThinkResult validates exit and risk enums."""
        tr = ThinkResult(exit_decision=TAOExit.RETRY, risk_level=RiskLevel.MEDIUM)
        assert tr.exit_decision == TAOExit.RETRY
        assert tr.risk_level == RiskLevel.MEDIUM

    def test_fact_categories(self):
        """FactState supports five fact categories."""
        categories = [
            FactCategory.CONFIRMED,
            FactCategory.USER_APPROVED,
            FactCategory.SPECULATIVE,
            FactCategory.REJECTED,
            FactCategory.MISSING,
        ]
        state = TAOState(goal_state=GoalState(final_goal="test"))
        for cat in categories:
            state.facts[cat.value] = FactItem(key=cat.value, value="v", category=cat)
        assert len(state.facts_by_category(FactCategory.CONFIRMED)) == 1


# ── 12.2 Think engine tests ─────────────────────────────────


@pytest.mark.asyncio
class TestThinkEngine:
    """Think engine tests with mocked LLM."""

    async def test_think_parses_structured_output(self):
        """Think engine parses valid structured output."""
        llm = FakeLLMService([build_think_response()])
        engine = TAOThinkEngine(llm)
        state = TAOState(
            goal_state=GoalState(final_goal="test", current_goal="read report"),
            candidate_actions=[
                ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)
            ],
        )
        result = await engine.think(state)
        assert result.selected_action == "read_report"
        assert result.exit_decision == TAOExit.CONTINUE
        assert result.risk_level == RiskLevel.LOW

    async def test_think_rejects_invalid_action(self):
        """Think engine rejects action outside candidate space."""
        llm = FakeLLMService(
            [
                build_think_response(selected_action="unknown_action"),
                build_think_response(selected_action="read_report"),
            ]
        )
        engine = TAOThinkEngine(llm, max_output_retries=1)
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            candidate_actions=[
                ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)
            ],
        )
        result = await engine.think(state)
        assert result.selected_action == "read_report"

    async def test_think_falls_back_to_interrupt(self):
        """Think engine falls back to interrupt after retries."""
        llm = FakeLLMService(["not json", "also not json"])
        engine = TAOThinkEngine(llm, max_output_retries=1)
        state = TAOState(goal_state=GoalState(final_goal="test"))
        result = await engine.think(state)
        assert result.exit_decision == TAOExit.INTERRUPT
        assert result.risk_level == RiskLevel.HIGH


# ── 12.3 Action runtime tests ─────────────────────────────────


@pytest.mark.asyncio
class TestActionRuntime:
    """Action runtime tests with mocked executors."""

    async def test_execute_registered_tool(self):
        """Runtime executes a registered tool and records result."""
        runtime = TAOActionRuntime()

        async def read_report(params: dict[str, Any]) -> str:
            return f"content for {params.get('path')}"

        runtime.register_executor("read_report", read_report)
        candidate = ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            candidate_actions=[candidate],
        )
        record = await runtime.execute(candidate, {"path": "resume.md"}, state)
        assert record.status == ActionStatus.DONE
        assert record.output == "content for resume.md"
        assert record.duration_ms is not None

    async def test_illegal_action_rejected(self):
        """Actions outside candidate space are rejected."""
        runtime = TAOActionRuntime()
        candidate = ActionCandidate(name="bad_action", type=ActionType.TOOL_CALL)
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            candidate_actions=[
                ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)
            ],
        )
        with pytest.raises(IllegalActionError):
            await runtime.execute(candidate, {}, state)

    async def test_precondition_check(self):
        """Hard preconditions are enforced."""
        runtime = TAOActionRuntime()
        runtime.register_executor("send_email", lambda p: "sent")
        candidate = ActionCandidate(
            name="send_email",
            type=ActionType.TOOL_CALL,
            preconditions=["user_email"],
        )
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            candidate_actions=[candidate],
        )
        with pytest.raises(PreconditionError):
            await runtime.execute(candidate, {}, state)

        state.facts["user_email"] = FactItem(
            key="user_email", value="a@b.com", category=FactCategory.CONFIRMED
        )
        record = await runtime.execute(candidate, {}, state)
        assert record.status == ActionStatus.DONE

    async def test_user_interaction_action(self):
        """User interaction actions use registered handler."""
        runtime = TAOActionRuntime()

        async def handler(question: str) -> str:
            return "answer"

        runtime.register_user_interaction_handler(handler)
        candidate = ActionCandidate(name="ask_user", type=ActionType.USER_INTERACTION)
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            candidate_actions=[candidate],
        )
        record = await runtime.execute(candidate, {"question": "what?"}, state)
        assert record.status == ActionStatus.DONE
        assert record.output == {"question": "what?", "reply": "answer"}

    async def test_coarse_filter_by_plan_node(self):
        """Coarse filter excludes actions not whitelisted for current step."""
        runtime = TAOActionRuntime()
        plan = Plan(
            goal=Goal(user_goal="test"),
            choice=Choice(
                selected_path="p",
                reason="r",
                steps=[Step(id="s1", objective="step1", reason="r")],
            ),
            current_step_index=0,
        )
        candidates = [
            ActionCandidate(name="a1", metadata={"plan_nodes": ["s1"]}),
            ActionCandidate(name="a2", metadata={"plan_nodes": ["s2"]}),
        ]
        filtered = runtime.coarse_filter(candidates, plan=plan)
        assert [c.name for c in filtered] == ["a1"]

    async def test_coarse_filter_by_precondition(self):
        """Coarse filter excludes actions with unsatisfied preconditions."""
        runtime = TAOActionRuntime()
        state = TAOState(goal_state=GoalState(final_goal="test"))
        candidates = [
            ActionCandidate(name="a1", preconditions=["ready"]),
            ActionCandidate(name="a2"),
        ]
        filtered = runtime.coarse_filter(candidates, state=state)
        assert [c.name for c in filtered] == ["a2"]


# ── 12.4 Observation interpreter tests ───────────────────────


@pytest.mark.asyncio
class TestObservationInterpreter:
    """Observation interpreter tests with mocked LLM."""

    async def test_interpret_success(self):
        """Interpreter produces structured Observation for successful output."""
        llm = FakeLLMService(
            [
                build_observation_response(
                    facts=[
                        {
                            "key": "growth",
                            "value": "12%",
                            "category": "confirmed",
                            "evidence": "act-1",
                        }
                    ]
                )
            ]
        )
        interpreter = TAOObservationInterpreter(llm)
        state = TAOState(goal_state=GoalState(final_goal="test"))
        record = ActionRecord(
            name="read_report",
            status=ActionStatus.DONE,
            output="Q3 sales grew 12%",
        )
        obs = await interpreter.interpret(state, record)
        assert obs.execution_status == ExecutionStatus.SUCCESS
        assert obs.progress is True
        assert len(obs.new_facts) == 1
        assert obs.new_facts[0].key == "growth"

    async def test_code_override_failed_action(self):
        """Code override marks observation failed when action failed."""
        llm = FakeLLMService(
            [build_observation_response(status="success", progress=True)]
        )
        interpreter = TAOObservationInterpreter(llm)
        state = TAOState(goal_state=GoalState(final_goal="test"))
        record = ActionRecord(
            name="read_report",
            status=ActionStatus.FAILED,
            output="",
            error="timeout",
        )
        obs = await interpreter.interpret(state, record)
        assert obs.execution_status == ExecutionStatus.FAILED
        assert obs.anomalies

    async def test_detect_empty_result(self):
        """Interpreter detects empty successful-looking output."""
        llm = FakeLLMService(
            [build_observation_response(status="success", progress=True)]
        )
        interpreter = TAOObservationInterpreter(llm)
        state = TAOState(goal_state=GoalState(final_goal="test"))
        record = ActionRecord(
            name="read_report",
            status=ActionStatus.DONE,
            output={"data": ""},
        )
        obs = await interpreter.interpret(state, record)
        assert obs.execution_status == ExecutionStatus.PARTIAL_SUCCESS
        assert obs.anomalies


# ── 12.5 Loop controller tests ───────────────────────────────


class TestLoopController:
    """TAO loop exit controller tests."""

    def _state(self) -> TAOState:
        return TAOState(
            goal_state=GoalState(final_goal="test"),
            control=ControlState(max_loops=3),
            candidate_actions=[
                ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)
            ],
        )

    def test_forced_finish_when_success(self):
        """Controller forces finish when success criteria satisfied."""
        ctrl = TAOLoopController()
        state = self._state()
        think = ThinkResult(
            success_criteria_satisfied=True,
            exit_decision=TAOExit.CONTINUE,
        )
        record = ctrl.decide(state, think)
        assert record.exit_type == TAOExit.FINISH
        assert record.overridden

    def test_high_risk_overridden_to_clarify(self):
        """High-risk continue is overridden to clarify."""
        ctrl = TAOLoopController()
        state = self._state()
        think = ThinkResult(
            exit_decision=TAOExit.CONTINUE,
            risk_level=RiskLevel.HIGH,
            risk_reason="violates hard constraint",
        )
        record = ctrl.decide(state, think)
        assert record.exit_type == TAOExit.CLARIFY
        assert record.overridden

    def test_retry_exhausted_becomes_replan(self):
        """Retry with exhausted budget becomes replan."""
        ctrl = TAOLoopController(max_action_retries=1)
        state = self._state()
        state.actions.append(
            ActionRecord(name="read_report", status=ActionStatus.FAILED, retry_count=1)
        )
        think = ThinkResult(exit_decision=TAOExit.RETRY)
        record = ctrl.decide(state, think)
        assert record.exit_type == TAOExit.REPLAN
        assert record.overridden

    def test_no_candidate_forces_clarify(self):
        """Continue without candidates forces clarify."""
        ctrl = TAOLoopController()
        state = TAOState(goal_state=GoalState(final_goal="test"))
        think = ThinkResult(exit_decision=TAOExit.CONTINUE)
        record = ctrl.decide(state, think)
        assert record.exit_type == TAOExit.CLARIFY
        assert record.overridden

    def test_max_loops_interrupt(self):
        """Max loops exceeded forces interrupt."""
        ctrl = TAOLoopController()
        state = self._state()
        state.control.used_loops = 3
        think = ThinkResult(exit_decision=TAOExit.CONTINUE)
        record = ctrl.decide(state, think)
        assert record.exit_type == TAOExit.INTERRUPT
        assert record.overridden


# ── 12.6 Double-layer TAO loop tests ─────────────────────────


@pytest.mark.asyncio
class TestTAOEngine:
    """TAO engine tests including double-layer supervision."""

    async def test_run_finish_path(self):
        """TAO loop finishes when Think returns finish."""
        llm = FakeLLMService(
            [
                build_think_response(exit_decision="finish"),
            ]
        )
        engine = TAOEngine(llm, supervisor_interval=0)
        result = await engine.run("test")
        assert result.exit_type == TAOExit.FINISH
        assert result.used_loops == 1

    async def test_run_continue_then_finish(self):
        """TAO loop executes action and continues until finish."""
        llm = FakeLLMService(
            [
                build_think_response(),
                build_observation_response(
                    facts=[{"key": "k", "value": "v", "category": "confirmed"}]
                ),
                build_think_response(exit_decision="finish"),
            ]
        )
        runtime = TAOActionRuntime()
        runtime.register_executor("read_report", lambda p: "data")
        engine = TAOEngine(llm, action_runtime=runtime, supervisor_interval=0)
        candidates = [ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)]
        result = await engine.run("test", candidate_actions=candidates)
        assert result.exit_type == TAOExit.FINISH
        assert result.total_actions == 1

    async def test_run_clarify_exit(self):
        """TAO loop returns clarify when Think selects clarify."""
        llm = FakeLLMService([build_think_response(exit_decision="clarify")])
        engine = TAOEngine(llm, supervisor_interval=0)
        result = await engine.run("test")
        assert result.exit_type == TAOExit.CLARIFY

    async def test_sync_supervisor_intervention(self):
        """Synchronous outer supervisor triggers replan."""
        llm = FakeLLMService(
            [
                build_think_response(),  # round 1: continue
                build_observation_response(),
                build_think_response(),  # round 2: continue
                build_observation_response(),
                build_think_response(),  # round 3: continue
                build_observation_response(),
                json.dumps(  # supervisor review
                    {
                        "goal_drift": True,
                        "drift_explanation": "drift",
                        "constraint_violations": [],
                        "stagnation": False,
                        "intervention": "replan",
                        "reason": "goal drift detected",
                    }
                ),
            ]
        )
        runtime = TAOActionRuntime()
        runtime.register_executor("read_report", lambda p: "data")
        engine = TAOEngine(
            llm,
            action_runtime=runtime,
            supervisor_interval=3,
            supervisor_interval_seconds=0,
        )
        candidates = [ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)]
        result = await engine.run("test", candidate_actions=candidates, max_loops=5)
        assert result.exit_type == TAOExit.REPLAN
        assert len(engine.supervisor_reviews) == 1

    async def test_async_supervisor_intervention(self):
        """Asynchronous outer supervisor sends intervention signal."""
        llm = FakeLLMService(
            [
                # Inner loop will wait on think; async supervisor fires quickly
                build_think_response(exit_decision="finish"),
                json.dumps(
                    {
                        "goal_drift": False,
                        "drift_explanation": "",
                        "constraint_violations": [],
                        "stagnation": True,
                        "intervention": "replan",
                        "reason": "stagnation",
                    }
                ),
            ]
        )
        engine = TAOEngine(
            llm,
            supervisor_interval=0,
            supervisor_interval_seconds=0.05,
        )
        # Delay think so async supervisor has time to intervene
        original_chat = engine.think_engine.llm_service.chat

        async def slow_chat(system, user, response_format=None):
            await asyncio.sleep(0.15)
            return await original_chat(system, user, response_format)

        engine.think_engine.llm_service.chat = slow_chat

        candidates = [ActionCandidate(name="read_report", type=ActionType.TOOL_CALL)]
        result = await engine.run("test", candidate_actions=candidates)
        # Either async supervisor intervenes before finish, or finish happens first
        assert result.exit_type in (TAOExit.FINISH, TAOExit.REPLAN)


# ── 12.7 TAO + PlanExecutor integration tests ────────────────


@pytest.mark.asyncio
class TestTAOIntegration:
    """TAO integration with PlanOrchestrator / PlanExecutor."""

    async def test_orchestrator_use_tao(self):
        """Orchestrator can execute a Plan step via TAO."""
        from xplan.engine.orchestrator import PlanOrchestrator
        from xplan.models.orchestrator import OrchestratorConfig

        plan_json = json.dumps(
            {
                "goal": {
                    "user_goal": "test",
                    "success_criteria": ["done"],
                    "adjective_standards": {},
                },
                "context": {
                    "known_facts": [],
                    "missing_info": [],
                    "constraints": {"hard": [], "soft": []},
                },
                "choice": {
                    "selected_path": "p",
                    "reason": "r",
                    "candidate_paths": [],
                    "steps": [
                        {
                            "id": "s1",
                            "objective": "do something",
                            "reason": "r",
                            "status": "pending",
                        }
                    ],
                },
                "checkpoint": [],
                "correction": [],
                "mode": "linear",
                "status": "draft",
                "dag": None,
                "check_results": [],
                "current_step_index": 0,
                "iteration_count": 0,
            }
        )
        llm = FakeLLMService(
            [
                plan_json,  # plan generation
                build_think_response(exit_decision="finish"),  # TAO think
            ]
        )
        runtime = TAOActionRuntime()
        runtime.register_executor("execute_step", lambda p: "step output")
        tao_engine = TAOEngine(llm, action_runtime=runtime)
        orchestrator = PlanOrchestrator(
            llm_service=llm,
            tao_engine=tao_engine,
        )

        config = OrchestratorConfig(
            use_iteration=False,
            verify_before_execute=False,
            use_tao=True,
            tao_max_loops=3,
            tao_supervisor_interval=0,
        )
        result = await orchestrator.run("test", config=config)
        assert result.status in ("completed", "failed")
        assert len(result.step_records) == 1
        assert result.step_records[0].tao_used is True


# ── TAO evaluator tests ─────────────────────────────────────


class TestTAOEvaluator:
    """TAO evaluation metrics and report tests."""

    def test_record_event_from_result(self):
        """Evaluator builds an event from a TAOResult."""
        from xplan.evaluation import TAOEvaluator

        evaluator = TAOEvaluator()
        state = TAOState(
            goal_state=GoalState(final_goal="test"),
            actions=[ActionRecord(name="read", status=ActionStatus.DONE)],
            observations=[
                Observation(
                    action_id="act-1",
                    execution_status=ExecutionStatus.SUCCESS,
                    new_facts=[ObservationFact(key="k", value="v", evidence="act-1")],
                    progress=True,
                )
            ],
        )
        result = TAOResult(
            exit_type=TAOExit.FINISH,
            used_loops=1,
            total_actions=1,
            state=state,
        )
        event = evaluator.record_from_result(result, task_id="t1", user_input="test")
        assert event.success is True
        assert event.used_loops == 1
        assert len(event.action_rounds) == 1
        assert len(event.observation_rounds) == 1

    def test_metrics_with_golden_answer(self):
        """Metrics incorporate golden answer comparisons."""
        from xplan.evaluation import TAOEvaluator
        from xplan.models.tao_evaluation import GoldenAnswer, ThinkRoundEvaluation

        evaluator = TAOEvaluator()
        event = evaluator.record_from_result(
            TAOResult(exit_type=TAOExit.FINISH, used_loops=1, total_actions=0),
            task_id="t1",
            user_input="test",
        )
        evaluator.add_golden_answer(
            GoldenAnswer(
                event_id=event.event_id,
                optimal_action="read_report",
                expected_missing_slots=["qps"],
            )
        )
        # Inject a think round manually
        event.think_rounds.append(
            ThinkRoundEvaluation(
                round_index=1,
                selected_action="read_report",
                missing_slots=["qps"],
            )
        )
        evaluator.record_event(event)

        metrics = evaluator.get_metrics()
        assert metrics.think.action_selection_accuracy == 1.0
        assert metrics.think.missing_slot_accuracy == 1.0

    def test_report_suggests_optimizations(self):
        """Report generates suggestions when metrics are below thresholds."""
        from xplan.evaluation import TAOEvaluator

        evaluator = TAOEvaluator()
        # Record a failing event with many loops to trigger suggestions
        result = TAOResult(
            exit_type=TAOExit.INTERRUPT,
            used_loops=20,
            total_actions=0,
        )
        evaluator.record_from_result(result, task_id="t1", user_input="test")
        report = evaluator.generate_report()
        assert report.metrics.overall.average_loops == 20.0
        assert any(s.metric == "average_loops" for s in report.suggestions)

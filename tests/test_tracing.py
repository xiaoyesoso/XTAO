"""失败回溯与根因定位模块验证测试。"""
import pytest

from xplan.models import (
    TracingPoint,
    FailureTracingResult,
    StepRecord,
    Plan,
    Goal,
    Context,
    Choice,
    Step,
    Checkpoint,
    PlanMode,
)
from xplan.prompts import (
    build_tracing_system_prompt,
    build_tracing_user_prompt,
)
from xplan.engine import FailureTracer


class TestTracingModels:
    """回溯数据模型测试。"""

    def test_tracing_point_creation(self):
        """TracingPoint 基本创建。"""
        tp = TracingPoint(step_id="s1", reason="测试", action="act", error="err")
        assert tp.step_id == "s1"
        assert tp.reason == "测试"
        assert tp.action == "act"
        assert tp.error == "err"
        assert tp.checkpoint_id is None

    def test_failure_tracing_result_defaults(self):
        """FailureTracingResult 默认值。"""
        fp = TracingPoint(step_id="s1")
        result = FailureTracingResult(failure_point=fp)
        assert result.failure_point.step_id == "s1"
        assert result.root_cause_point is None
        assert result.rollback_point is None
        assert result.replan_start_point is None
        assert result.tracing_chain == []
        assert result.checkpoint_reliable is True

    def test_step_record_defaults(self):
        """StepRecord 默认值。"""
        sr = StepRecord(step_id="s1")
        assert sr.step_id == "s1"
        assert sr.input == {}
        assert sr.output == {}
        assert sr.context_used == []
        assert sr.facts_used == []
        assert sr.assumptions == []
        assert sr.tool_name == ""
        assert sr.tool_input == {}
        assert sr.tool_output == {}
        assert sr.checkpoint_result is None
        assert sr.snapshot == {}
        assert sr.timestamp == ""


class TestTracingPrompts:
    """回溯提示词测试。"""

    def test_system_prompt_content(self):
        """系统提示词包含关键概念。"""
        prompt = build_tracing_system_prompt()
        assert "失败点" in prompt
        assert "根因点" in prompt
        assert "回滚点" in prompt
        assert "Replan 起点" in prompt
        assert "反向排查清单" in prompt
        assert "Checkpoint 可靠性" in prompt

    def test_user_prompt_content(self):
        """用户提示词包含输入信息。"""
        prompt = build_tracing_user_prompt(
            plan_json='{"goal": {}}',
            failure_info="步骤 s3 执行失败",
            step_records_json='[{"step_id": "s3"}]',
        )
        assert "步骤 s3 执行失败" in prompt
        assert "失败回溯" in prompt


class TestFailureTracer:
    """失败回溯引擎测试。"""

    @pytest.fixture
    def linear_plan(self):
        """线性 Plan fixture。"""
        return Plan(
            goal=Goal(user_goal="测试目标", success_criteria=["标准1"]),
            context=Context(known_facts=["事实1"]),
            choice=Choice(
                selected_path="路径",
                reason="理由",
                steps=[
                    Step(id="s1", objective="步骤1"),
                    Step(id="s2", objective="步骤2"),
                    Step(id="s3", objective="步骤3"),
                ],
            ),
            checkpoint=[Checkpoint(step_id="s1", checks=["检查1"])],
        )

    def test_find_upstream_steps_linear(self, linear_plan):
        """线性模式上游步骤查找。"""
        tracer = FailureTracer(llm_service=None)
        upstream = tracer.find_upstream_steps(linear_plan, "s3")
        assert upstream == ["s1", "s2"]

    def test_find_downstream_steps_linear(self, linear_plan):
        """线性模式下游步骤查找。"""
        tracer = FailureTracer(llm_service=None)
        downstream = tracer.find_downstream_steps(linear_plan, "s1")
        assert downstream == ["s2", "s3"]

    def test_find_nearest_checkpoint(self, linear_plan):
        """查找最近 Checkpoint。"""
        tracer = FailureTracer(llm_service=None)
        nearest = tracer.find_nearest_checkpoint(linear_plan, "s3")
        assert nearest == "s1"

    def test_find_nearest_checkpoint_none(self, linear_plan):
        """无 Checkpoint 时返回 None。"""
        plan = Plan(
            goal=Goal(user_goal="测试", success_criteria=["c"]),
            context=Context(),
            choice=Choice(
                selected_path="p",
                reason="r",
                steps=[Step(id="s1", objective="o")],
            ),
        )
        tracer = FailureTracer(llm_service=None)
        assert tracer.find_nearest_checkpoint(plan, "s1") is None

    def test_check_circular_dependency_linear(self, linear_plan):
        """线性模式无循环依赖。"""
        tracer = FailureTracer(llm_service=None)
        assert tracer.check_circular_dependency(linear_plan, "s1") is False

    def test_build_tracing_chain(self, linear_plan):
        """构建反向排查链路。"""
        tracer = FailureTracer(llm_service=None)
        records = [
            StepRecord(step_id="s1", tool_name="tool1"),
            StepRecord(step_id="s2", tool_name="tool2"),
            StepRecord(
                step_id="s3",
                tool_name="tool3",
                tool_output={"error": "执行失败"},
            ),
        ]
        chain = tracer.build_tracing_chain(linear_plan, "s3", records)
        assert len(chain) == 3
        assert chain[0].step_id == "s3"
        assert "失败点" in chain[0].reason
        assert chain[0].error == "执行失败"
        assert chain[0].action == "tool3"

    def test_review_checkpoint_reliability_no_checkpoint(self):
        """无 Checkpoint 时不可信。"""
        tracer = FailureTracer(llm_service=None)
        plan = Plan(
            goal=Goal(user_goal="测试", success_criteria=["c"]),
            context=Context(),
            choice=Choice(
                selected_path="p",
                reason="r",
                steps=[Step(id="s1", objective="o")],
            ),
        )
        result = FailureTracingResult(
            failure_point=TracingPoint(step_id="s1"),
        )
        assert tracer.review_checkpoint_reliability(plan, result, []) is False

    def test_review_checkpoint_reliability_close_failure(self, linear_plan):
        """失败点离 Checkpoint 很近时不可信。"""
        tracer = FailureTracer(llm_service=None)
        records = [
            StepRecord(
                step_id="s1",
                tool_name="tool1",
                checkpoint_result={"passed": True},
            ),
            StepRecord(
                step_id="s2",
                tool_name="tool2",
                tool_output={"error": "失败"},
            ),
        ]
        result = FailureTracingResult(
            failure_point=TracingPoint(step_id="s2"),
        )
        # s2 距离 s1（Checkpoint）仅 1 步，应不可信
        reliable = tracer.review_checkpoint_reliability(linear_plan, result, records)
        assert reliable is False

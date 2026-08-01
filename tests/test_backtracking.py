"""回溯模块基本功能测试。"""
import pytest

from xtao.models import (
    BacktrackingLevel,
    BacktrackingResult,
    CandidatePath,
    CrossTurnContamination,
    DecisionNode,
    FailurePathRecord,
    JumpRule,
)
from xtao.services import CandidatePathManager
from xtao.engine import BacktrackingEngine, CrossTurnTracker


class TestBacktrackingModels:
    """回溯数据模型测试。"""

    def test_backtracking_level_enum(self):
        """回溯层级枚举。"""
        assert BacktrackingLevel.ACTION == "action"
        assert BacktrackingLevel.STEP == "step"
        assert BacktrackingLevel.STAGE == "stage"
        assert BacktrackingLevel.GLOBAL == "global"
        assert BacktrackingLevel.CROSS_TURN == "cross_turn"

    def test_candidate_path(self):
        """候选路径模型。"""
        cp = CandidatePath(path="path_a")
        assert cp.status == "available"
        assert cp.reason == ""

    def test_decision_node(self):
        """决策节点模型。"""
        node = DecisionNode(
            decision_id="d1",
            selected="path_a",
            candidates=[CandidatePath(path="path_a"), CandidatePath(path="path_b")],
        )
        assert node.decision_id == "d1"
        assert len(node.candidates) == 2

    def test_failure_path_record(self):
        """失败路径记录模型。"""
        record = FailurePathRecord(
            path="path_a", failure_reason="timeout", failure_turn=1
        )
        assert record.recovered is False
        assert record.failure_turn == 1

    def test_cross_turn_contamination(self):
        """跨轮次污染记录模型。"""
        ct = CrossTurnContamination(
            error_fact_key="qps", introduced_turn=2
        )
        assert ct.affected_results == []
        assert ct.affected_summaries == []

    def test_backtracking_result(self):
        """回溯结果模型。"""
        result = BacktrackingResult(level=BacktrackingLevel.ACTION)
        assert result.success is False
        assert result.expanded is False
        assert result.next_level is None

    def test_jump_rule(self):
        """跳跃式回溯规则模型。"""
        rule = JumpRule(error_pattern="timeout", rollback_position="step_1")
        assert rule.similarity_threshold == 0.8


class TestCandidatePathManager:
    """候选路径管理器测试。"""

    def test_register_and_get_decision(self):
        """注册并获取决策节点。"""
        cpm = CandidatePathManager()
        cpm.register_decision(
            "d1", "path_a", [CandidatePath(path="path_a")]
        )
        node = cpm.get_decision("d1")
        assert node is not None
        assert node.selected == "path_a"

    def test_mark_path_failed(self):
        """标记路径失败。"""
        cpm = CandidatePathManager()
        cpm.register_decision(
            "d1",
            "path_a",
            [CandidatePath(path="path_a"), CandidatePath(path="path_b")],
        )
        cpm.mark_path_failed("d1", "path_a", "timeout", turn=1)
        failed = cpm.get_failed_paths()
        assert len(failed) == 1
        assert failed[0].path == "path_a"
        assert failed[0].failure_reason == "timeout"

    def test_get_next_available(self):
        """获取下一条可用路径。"""
        cpm = CandidatePathManager()
        cpm.register_decision(
            "d1",
            "path_a",
            [
                CandidatePath(path="path_a"),
                CandidatePath(path="path_b"),
                CandidatePath(path="path_c"),
            ],
        )
        cpm.mark_path_failed("d1", "path_a", "timeout")
        next_path = cpm.get_next_available("d1")
        assert next_path is not None
        assert next_path.path == "path_b"

    def test_switch_path(self):
        """快速路径切换。"""
        cpm = CandidatePathManager()
        cpm.register_decision(
            "d1",
            "path_a",
            [
                CandidatePath(path="path_a"),
                CandidatePath(path="path_b"),
            ],
        )
        cpm.mark_path_failed("d1", "path_a", "timeout")
        switched = cpm.switch_path("d1")
        assert switched is not None
        assert switched.path == "path_b"
        node = cpm.get_decision("d1")
        assert node.selected == "path_b"

    def test_switch_path_no_available(self):
        """无可用路径时切换返回 None。"""
        cpm = CandidatePathManager()
        cpm.register_decision("d1", "path_a", [CandidatePath(path="path_a")])
        cpm.mark_path_failed("d1", "path_a", "timeout")
        assert cpm.switch_path("d1") is None

    def test_can_retry_failed_path(self):
        """判断失败路径是否可重试。"""
        cpm = CandidatePathManager()
        cpm.register_decision("d1", "path_a", [CandidatePath(path="path_a")])
        cpm.mark_path_failed("d1", "path_a", "timeout")
        assert cpm.can_retry_failed_path("path_a") is False
        assert cpm.can_retry_failed_path("unknown") is True


class TestCrossTurnTracker:
    """跨轮次追踪器测试。"""

    def test_record_and_find_origin(self):
        """记录事实写入并找到错误来源。"""
        tracker = CrossTurnTracker()
        tracker.record_fact_introduction("qps", "1000", turn=1)
        tracker.record_fact_introduction("qps", "2000", turn=2)
        assert tracker.find_error_origin("qps", "2000") == 2
        assert tracker.find_error_origin("qps", "9999") is None

    def test_find_affected_results(self):
        """找到受影响的中间结果。"""
        tracker = CrossTurnTracker()
        all_facts = {
            "qps": "2000",
            "latency": "depends on qps",
            "unrelated": "no dependency",
        }
        affected = tracker.find_affected_results("qps", all_facts)
        assert "latency" in affected
        assert "unrelated" not in affected

    def test_find_affected_summaries(self):
        """找到受污染的历史摘要。"""
        tracker = CrossTurnTracker()
        summaries = [
            {"id": "s1", "content": "qps is relevant"},
            {"id": "s2", "content": "no dependency"},
        ]
        affected = tracker.find_affected_summaries("qps", summaries)
        assert "s1" in affected

    def test_build_contamination_report(self):
        """构建跨轮次污染报告。"""
        tracker = CrossTurnTracker()
        tracker.record_fact_introduction("qps", "2000", turn=2)
        all_facts = {"qps": "2000", "latency": "depends on qps"}
        summaries = [{"id": "s1", "content": "qps is relevant"}]
        report = tracker.build_contamination_report(
            "qps", "2000", all_facts, summaries
        )
        assert report.error_fact_key == "qps"
        assert report.introduced_turn == 2
        assert "latency" in report.affected_results


class TestBacktrackingEngine:
    """回溯引擎测试。"""

    def test_determine_level_timeout(self):
        """偶发性错误判定为 ACTION 级。"""
        cpm = CandidatePathManager()
        engine = BacktrackingEngine(
            llm_service=None, candidate_path_manager=cpm
        )
        level = engine.determine_level(TimeoutError("test"), None, None)
        assert level == BacktrackingLevel.ACTION

    def test_determine_level_no_error_no_plan(self):
        """无错误且无检查结果时判定为 GLOBAL 级。"""
        engine = BacktrackingEngine(llm_service=None)
        level = engine.determine_level(None, None, None)
        assert level == BacktrackingLevel.GLOBAL

    @pytest.mark.asyncio
    async def test_action_level_retry(self):
        """动作级回溯（重试）。"""
        engine = BacktrackingEngine(llm_service=None)
        result = await engine.action_level_retry(None, "step_1", None)
        assert result.level == BacktrackingLevel.ACTION
        assert result.success is True
        assert result.rollback_to == "step_1"

    @pytest.mark.asyncio
    async def test_jump_backtracking_no_rules(self):
        """无规则时跳跃式回溯返回 None。"""
        engine = BacktrackingEngine(llm_service=None)
        result = await engine.jump_backtracking("timeout_error", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_jump_backtracking_matched(self):
        """匹配规则时跳跃式回溯返回结果。"""
        engine = BacktrackingEngine(llm_service=None)
        rules = [JumpRule(error_pattern="timeout", rollback_position="step_1")]
        result = await engine.jump_backtracking("timeout_error", rules)
        assert result is not None
        assert result.rollback_to == "step_1"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_vector_jump_backtracking_no_client(self):
        """无向量数据库客户端时返回 None。"""
        engine = BacktrackingEngine(llm_service=None)
        result = await engine.vector_jump_backtracking("error context", None)
        assert result is None

"""端到端集成测试：简历优化场景验证 G4C 全流程。

验证 Plan 的生成、评估、执行、检查点、纠偏、DAG 验证等核心流程。
"""

import pytest

from xplan.models import (
    Plan,
    PlanMode,
    PlanStatus,
    Goal,
    Context,
    Constraints,
    Choice,
    Step,
    Checkpoint,
    CheckResult,
    CheckEvidence,
    Correction,
    CorrectionAction,
    CorrectionType,
    DAGNode,
    DAGEdge,
    DAGPlan,
)
from xplan.engine import DAGValidator
from xplan.evaluation import OfflineAnalyzer


# ── G4C 数据模型测试 ───────────────────────────────────────


class TestG4CModels:
    """G4C 五要素数据模型测试。"""

    def test_goal_with_success_criteria(self):
        """Goal 包含 user_goal 与 success_criteria。"""
        goal = Goal(
            user_goal="优化项目经历，使其适合阿里 Java 后端面试",
            success_criteria=[
                "体现技术复杂度",
                "体现个人贡献",
                "不虚构用户没有做过的内容",
            ],
        )
        assert goal.user_goal != ""
        assert len(goal.success_criteria) == 3

    def test_goal_with_adjective_standards(self):
        """Goal 支持形容词标准定义。"""
        goal = Goal(
            user_goal="优化项目经历",
            success_criteria=["体现技术复杂度"],
            adjective_standards={
                "技术复杂度": "至少涉及分布式、高并发或海量数据处理",
            },
        )
        assert "技术复杂度" in goal.adjective_standards

    def test_context_with_constraints(self):
        """Context 包含 known_facts、missing_info 和约束。"""
        ctx = Context(
            known_facts=["用户认为项目偏 CRUD", "目标岗位是 Java 后端"],
            missing_info=["项目背景", "技术栈", "业务规模"],
            constraints=Constraints(
                hard=["不能虚构项目事实"],
                soft=["尽量量化结果"],
            ),
        )
        assert len(ctx.known_facts) == 2
        assert len(ctx.missing_info) == 3
        assert len(ctx.constraints.hard) == 1
        assert len(ctx.constraints.soft) == 1

    def test_choice_with_steps_and_reasons(self):
        """Choice 包含 selected_path、reason 和带 reason 的 steps。"""
        choice = Choice(
            selected_path="先抽取事实，再生成亮点",
            reason="如果直接包装，容易违反不能虚构的要求",
            candidate_paths=["先抽取事实，再生成亮点", "先生成粗稿，再迭代"],
            steps=[
                Step(
                    id="extract_facts",
                    objective="抽取已有项目事实",
                    reason="需要区分事实与推测，为后续提供基础",
                ),
                Step(
                    id="generate_highlights",
                    objective="生成项目亮点",
                    reason="基于事实生成亮点，避免虚构",
                ),
            ],
        )
        assert choice.reason != ""
        assert len(choice.steps) == 2
        assert all(s.reason for s in choice.steps)

    def test_checkpoint_with_checks(self):
        """Checkpoint 包含 step_id 和 checks 列表。"""
        cp = Checkpoint(
            step_id="extract_facts",
            checks=["是否区分事实和推测", "是否识别出缺失信息", "是否保留用户硬约束"],
        )
        assert cp.step_id == "extract_facts"
        assert len(cp.checks) == 3

    def test_correction_with_structured_action(self):
        """Correction 支持结构化 action。"""
        corr = Correction(
            condition="缺少关键项目信息",
            action=CorrectionAction(
                type=CorrectionType.CLARIFY,
                message="向用户澄清缺失的项目信息",
                params={"missing_fields": ["项目背景", "技术栈"]},
            ),
        )
        assert corr.action.type == CorrectionType.CLARIFY
        assert "missing_fields" in corr.action.params

    def test_correction_all_types(self):
        """Correction 支持五种纠偏策略。"""
        for ct in CorrectionType:
            corr = Correction(
                condition=f"condition for {ct.value}",
                action=CorrectionAction(type=ct),
            )
            assert corr.action.type == ct

    def test_plan_composite_object(self):
        """Plan 是包含 G4C 五要素的复合对象。"""
        plan = Plan(
            goal=Goal(user_goal="优化项目", success_criteria=["体现技术复杂度"]),
            context=Context(
                constraints=Constraints(hard=["不能虚构"]),
            ),
            choice=Choice(
                selected_path="先抽取事实",
                reason="避免虚构",
                steps=[Step(id="s1", objective="抽取", reason="基础")],
            ),
            checkpoint=[Checkpoint(step_id="s1", checks=["是否区分事实"])],
            correction=[
                Correction(
                    condition="信息不足",
                    action=CorrectionAction(type=CorrectionType.CLARIFY),
                )
            ],
        )
        assert plan.mode == PlanMode.LINEAR
        assert plan.status == PlanStatus.DRAFT
        assert len(plan.choice.steps) == 1
        assert len(plan.checkpoint) == 1
        assert len(plan.correction) == 1

    def test_plan_with_dag_mode(self):
        """Plan 支持 DAG 模式。"""
        plan = Plan(
            mode=PlanMode.DAG,
            goal=Goal(user_goal="面试准备"),
            choice=Choice(
                selected_path="DAG 模式",
                reason="需要并行处理",
                steps=[],
            ),
            dag=DAGPlan(
                nodes=[
                    DAGNode(id="a", objective="步骤A"),
                    DAGNode(id="b", objective="步骤B", depends_on=["a"]),
                ],
            ),
        )
        assert plan.mode == PlanMode.DAG
        assert plan.dag is not None
        assert len(plan.dag.nodes) == 2


# ── DAG 验证器测试 ─────────────────────────────────────────


class TestDAGValidator:
    """DAG 验证器测试。"""

    def test_valid_dag(self):
        """有效 DAG 通过验证。"""
        dag = DAGPlan(
            nodes=[
                DAGNode(id="a", objective="A"),
                DAGNode(id="b", objective="B", depends_on=["a"]),
                DAGNode(id="c", objective="C", depends_on=["b"]),
            ]
        )
        validator = DAGValidator()
        errors = validator.validate(dag)
        assert errors == []

    def test_cycle_detection(self):
        """检测循环依赖。"""
        dag = DAGPlan(
            nodes=[
                DAGNode(id="a", objective="A", depends_on=["c"]),
                DAGNode(id="b", objective="B", depends_on=["a"]),
                DAGNode(id="c", objective="C", depends_on=["b"]),
            ]
        )
        validator = DAGValidator()
        cycles = validator.detect_cycles(dag)
        assert len(cycles) > 0

    def test_invalid_node_reference(self):
        """检测无效节点引用。"""
        dag = DAGPlan(
            nodes=[
                DAGNode(id="a", objective="A", depends_on=["nonexistent"]),
            ]
        )
        validator = DAGValidator()
        errors = validator.validate(dag)
        assert len(errors) > 0

    def test_topological_order(self):
        """拓扑排序正确。"""
        dag = DAGPlan(
            nodes=[
                DAGNode(id="c", objective="C", depends_on=["b"]),
                DAGNode(id="a", objective="A"),
                DAGNode(id="b", objective="B", depends_on=["a"]),
            ]
        )
        validator = DAGValidator()
        order = validator.get_topological_order(dag)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_get_ready_nodes(self):
        """获取就绪节点。"""
        dag = DAGPlan(
            nodes=[
                DAGNode(id="a", objective="A"),
                DAGNode(id="b", objective="B", depends_on=["a"]),
                DAGNode(id="c", objective="C", depends_on=["a"]),
            ]
        )
        validator = DAGValidator()
        ready = validator.get_ready_nodes(dag, completed=set())
        assert "a" in ready
        assert "b" not in ready

        ready_after_a = validator.get_ready_nodes(dag, completed={"a"})
        assert "b" in ready_after_a
        assert "c" in ready_after_a


# ── 离线分析测试 ───────────────────────────────────────────


class TestOfflineAnalyzer:
    """离线分析器测试。"""

    async def test_analyze_good_plan(self):
        """分析高质量 Plan。"""
        plan = Plan(
            goal=Goal(
                user_goal="优化项目经历",
                success_criteria=["体现技术复杂度", "体现业务价值"],
                adjective_standards={"技术复杂度": "涉及分布式系统"},
            ),
            context=Context(
                known_facts=["项目偏 CRUD"],
                missing_info=["技术栈"],
                constraints=Constraints(hard=["不能虚构"]),
            ),
            choice=Choice(
                selected_path="先抽取事实",
                reason="避免虚构",
                candidate_paths=["先抽取事实", "先生成粗稿"],
                steps=[
                    Step(id="s1", objective="抽取", reason="基础"),
                    Step(id="s2", objective="生成", reason="基于事实"),
                    Step(id="s3", objective="追问", reason="补充信息"),
                ],
            ),
            checkpoint=[
                Checkpoint(step_id="s1", checks=["是否区分事实"]),
                Checkpoint(step_id="s2", checks=["是否有量化结果"]),
            ],
            correction=[
                Correction(
                    condition="信息不足",
                    action=CorrectionAction(type=CorrectionType.CLARIFY),
                ),
                Correction(
                    condition="格式错误",
                    action=CorrectionAction(type=CorrectionType.RETRY),
                ),
            ],
        )
        analyzer = OfflineAnalyzer()
        result = await analyzer.analyze(plan)
        assert result is not None
        assert result.score > 0.5

    def test_checkpoint_sufficiency(self):
        """检查点充分性评估。"""
        analyzer = OfflineAnalyzer()
        plan = Plan(
            goal=Goal(user_goal="test", success_criteria=["c1"]),
            choice=Choice(
                selected_path="p",
                reason="r",
                steps=[
                    Step(id=f"s{i}", objective=f"step {i}", reason="r")
                    for i in range(6)
                ],
            ),
            checkpoint=[
                Checkpoint(step_id="s0", checks=["check1"]),
                Checkpoint(step_id="s3", checks=["check2"]),
            ],
        )
        sufficient, msg = analyzer.check_checkpoint_sufficiency(plan)
        # 6 steps, 2 checkpoints, 2 >= 6/3=2, should be sufficient
        assert sufficient is True

    def test_constraint_violation_detection(self):
        """约束违反检测。"""
        analyzer = OfflineAnalyzer()
        plan = Plan(
            goal=Goal(user_goal="优化", success_criteria=["c1"]),
            context=Context(
                constraints=Constraints(hard=["不能虚构项目事实"]),
            ),
            choice=Choice(
                selected_path="直接虚构项目事实",
                reason="快速完成",
                steps=[
                    Step(id="s1", objective="虚构项目事实", reason="快速"),
                ],
            ),
        )
        violations = analyzer.check_constraint_violations(plan)
        assert len(violations) > 0


# ── CheckResult 测试 ───────────────────────────────────────


class TestCheckResult:
    """检查点执行结果测试。"""

    def test_check_result_with_evidence(self):
        """检查结果包含证据。"""
        result = CheckResult(
            step_id="extract_facts",
            check_point="是否区分事实和推测",
            passed=True,
            result="所有内容均区分了事实与推测",
            evidences=[
                CheckEvidence(
                    description="项目背景部分明确标注为用户提供",
                    source="用户输入",
                ),
            ],
        )
        assert result.passed is True
        assert len(result.evidences) == 1

    def test_check_result_failed(self):
        """检查未通过的结果。"""
        result = CheckResult(
            step_id="rewrite",
            check_point="是否存在虚构内容",
            passed=False,
            result="发现 2 处虚构内容",
            evidences=[],
        )
        assert result.passed is False


# ── DAG Edge 测试 ──────────────────────────────────────────


class TestDAGEdge:
    """DAG 边测试。"""

    def test_edge_with_attrs(self):
        """边支持属性。"""
        edge = DAGEdge(
            src="extract_facts",
            dst="generate_highlights",
            attrs={"type": "data_dependency", "weight": 0.8},
        )
        assert edge.src == "extract_facts"
        assert edge.dst == "generate_highlights"
        assert edge.attrs["type"] == "data_dependency"

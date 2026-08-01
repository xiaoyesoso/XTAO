"""Failure backtracking and root cause localization engine.

Core concept: failure point != root cause point. When execution fails, the location where
the error is exposed (failure point) is usually not the location where the error was originally
introduced (root cause point). This engine performs reverse tracing from the failure point,
checking layer by layer upstream to find the true root cause point, and provides rollback point
and replan start point suggestions.

Complete backtracking flow:
1. Code builds reverse tracing chain (build_tracing_chain)
2. Code finds nearest checkpoint (find_nearest_checkpoint)
3. Code checks circular dependency (check_circular_dependency)
4. LLM performs semantic root cause localization (llm_trace_root_cause)
5. Merge code and LLM results, return FailureTracingResult

Division of labor between code and LLM:
- Code: upstream/downstream step traversal, checkpoint localization, circular dependency detection, preliminary tracing chain construction
- LLM: semantic root cause judgment, goal change judgment, constraint impact analysis, result reusability analysis
"""

import json
import logging
import re
from typing import Any

from xtao.models import Plan, PlanMode
from xtao.models.tracing import FailureTracingResult, StepRecord, TracingPoint
from xtao.prompts.tracing_prompt import (
    build_tracing_system_prompt,
    build_tracing_user_prompt,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response.

    Supports both markdown code block wrapped and bare JSON formats.

    Args:
        text: LLM response text

    Returns:
        Parsed JSON object

    Raises:
        json.JSONDecodeError: When unable to parse as JSON
    """
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class FailureTracer:
    """Failure backtracking engine, implements root cause localization mechanism.

    Complete flow: build_tracing_chain -> find_nearest_checkpoint ->
    check_circular_dependency -> llm_trace_root_cause -> merge results.

    Attributes:
        llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
        dag_validator: DAG validator (optional), used to traverse dependency chains
    """

    def __init__(
        self,
        llm_service: Any,
        dag_validator: Any = None,
    ) -> None:
        """Initialize the failure backtracking engine.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            dag_validator: DAG validator (optional), used to traverse dependency chains
        """
        self.llm_service = llm_service
        self.dag_validator = dag_validator

    def find_upstream_steps(self, plan: Plan, step_id: str) -> list[str]:
        """Find all upstream dependency steps of the specified step.

        Code method. Selects lookup strategy based on Plan mode:
        - DAG mode: Find direct upstream via plan.dag.edges and node depends_on
        - Linear mode: Return all steps before step_id

        Args:
            plan: Current Plan
            step_id: Target step ID

        Returns:
            List of upstream step IDs (excluding step_id itself)
        """
        if plan.mode == PlanMode.DAG and plan.dag is not None:
            # DAG mode: Find direct upstream via edges and depends_on
            upstream: set[str] = set()
            # Find via edges: in src -> dst, dst depends on src, so dst's upstream includes src
            for edge in plan.dag.edges:
                if edge.dst == step_id:
                    upstream.add(edge.src)
            # Find via node depends_on
            for node in plan.dag.nodes:
                if node.id == step_id:
                    upstream.update(node.depends_on)
            # Recursively find indirect upstream (transitive closure)
            all_upstream: set[str] = set()
            frontier = list(upstream)
            while frontier:
                current = frontier.pop()
                if current in all_upstream:
                    continue
                all_upstream.add(current)
                # Find current's upstream
                for edge in plan.dag.edges:
                    if edge.dst == current and edge.src not in all_upstream:
                        frontier.append(edge.src)
                for node in plan.dag.nodes:
                    if node.id == current:
                        for dep in node.depends_on:
                            if dep not in all_upstream:
                                frontier.append(dep)
            return list(all_upstream)

        # Linear mode: return all steps before step_id
        step_ids = [s.id for s in plan.choice.steps]
        if step_id not in step_ids:
            return []
        idx = step_ids.index(step_id)
        return step_ids[:idx]

    def find_downstream_steps(self, plan: Plan, step_id: str) -> list[str]:
        """Find all downstream steps of the specified step.

        Code method. Selects lookup strategy based on Plan mode:
        - DAG mode: Find direct downstream via plan.dag.edges (recursive transitive closure)
        - Linear mode: Return all steps after step_id

        Args:
            plan: Current Plan
            step_id: Target step ID

        Returns:
            List of downstream step IDs (excluding step_id itself)
        """
        if plan.mode == PlanMode.DAG and plan.dag is not None:
            # DAG mode: Find direct downstream via edges (src -> dst, dst is src's downstream)
            downstream: set[str] = set()
            frontier: list[str] = []
            for edge in plan.dag.edges:
                if edge.src == step_id:
                    frontier.append(edge.dst)
            while frontier:
                current = frontier.pop()
                if current in downstream:
                    continue
                downstream.add(current)
                for edge in plan.dag.edges:
                    if edge.src == current and edge.dst not in downstream:
                        frontier.append(edge.dst)
            return list(downstream)

        # Linear mode: return all steps after step_id
        step_ids = [s.id for s in plan.choice.steps]
        if step_id not in step_ids:
            return []
        idx = step_ids.index(step_id)
        return step_ids[idx + 1 :]

    def find_nearest_checkpoint(self, plan: Plan, step_id: str) -> str | None:
        """Find the step_id of the nearest Checkpoint before the specified step.

        Code method. In linear mode, traverses the Checkpoint list to find the nearest
        Checkpoint-associated step at or before step_id.

        Args:
            plan: Current Plan
            step_id: Target step ID

        Returns:
            step_id associated with the nearest Checkpoint, or None if not found
        """
        if not plan.checkpoint:
            return None

        step_ids = [s.id for s in plan.choice.steps]
        if step_id not in step_ids:
            return None
        target_idx = step_ids.index(step_id)

        # Collect all Checkpoint-associated steps and their indices
        checkpoint_indices: list[tuple[int, str]] = []
        for cp in plan.checkpoint:
            if cp.step_id in step_ids:
                cp_idx = step_ids.index(cp.step_id)
                checkpoint_indices.append((cp_idx, cp.step_id))

        if not checkpoint_indices:
            return None

        # Find the nearest Checkpoint at or before step_id
        nearest: str | None = None
        nearest_idx = -1
        for cp_idx, cp_step_id in checkpoint_indices:
            if cp_idx <= target_idx and cp_idx > nearest_idx:
                nearest_idx = cp_idx
                nearest = cp_step_id

        return nearest

    def check_circular_dependency(self, plan: Plan, step_id: str) -> bool:
        """Check whether the dependency chain involving step_id has circular dependencies.

        Code method. In DAG mode, uses DAGValidator to detect cycles;
        in linear mode, circular dependencies are impossible, returns False directly.

        Args:
            plan: Current Plan
            step_id: Target step ID

        Returns:
            True means circular dependency exists, False means none
        """
        if plan.mode != PlanMode.DAG or plan.dag is None:
            # Linear mode cannot have circular dependencies
            return False

        if self.dag_validator is not None:
            cycles = self.dag_validator.detect_cycles(plan.dag)
        else:
            # When no DAGValidator, use internal simple detection
            cycles = self._detect_cycles_simple(plan)

        # Check whether any cycle includes step_id
        for cycle in cycles:
            if step_id in cycle:
                return True
        return len(cycles) > 0

    def _detect_cycles_simple(self, plan: Plan) -> list[list[str]]:
        """Simple circular dependency detection (used when no DAGValidator).

        Uses DFS three-color marking.

        Args:
            plan: Current Plan

        Returns:
            List of cycle paths
        """
        if plan.dag is None:
            return []

        node_ids = {node.id for node in plan.dag.nodes}
        graph: dict[str, list[str]] = {node.id: [] for node in plan.dag.nodes}
        for node in plan.dag.nodes:
            for dep in node.depends_on:
                if dep in node_ids:
                    graph[node.id].append(dep)
        for edge in plan.dag.edges:
            if edge.src in node_ids and edge.dst in node_ids:
                graph[edge.dst].append(edge.src)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in graph}
        cycles: list[list[str]] = []

        def _dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            path.append(node)
            for dep in graph.get(node, []):
                if color.get(dep, BLACK) == GRAY:
                    cycle_start = path.index(dep)
                    cycles.append(path[cycle_start:] + [dep])
                elif color.get(dep, BLACK) == WHITE:
                    _dfs(dep, path)
            path.pop()
            color[node] = BLACK

        for node_id in graph:
            if color[node_id] == WHITE:
                _dfs(node_id, [])

        return cycles

    def build_tracing_chain(
        self,
        plan: Plan,
        failure_step_id: str,
        step_records: list[StepRecord],
    ) -> list[TracingPoint]:
        """Build reverse tracing chain.

        Code method. Starts from the failure point, checks each upstream step in turn,
        returns a list of TracingPoint, each point annotated with preliminary judgment
        (based on objective info from execution records).

        Preliminary judgment rules:
        - Failure point: annotate action and error (extracted from execution record)
        - Upstream steps: check whether their checkpoint_result passed, whether tool_output is abnormal
        - Annotate associated Checkpoint ID

        Args:
            plan: Current Plan
            failure_step_id: Failure step ID
            step_records: Step execution record list

        Returns:
            List of TracingPoint, arranged from failure point upstream
        """
        # Build execution record index
        record_map: dict[str, StepRecord] = {
            r.step_id: r for r in step_records
        }

        # Build Checkpoint index: step_id -> checkpoint_id
        cp_index: dict[str, str] = {}
        for i, cp in enumerate(plan.checkpoint):
            cp_index[cp.step_id] = f"checkpoint_{i}"

        chain: list[TracingPoint] = []

        # Failure point
        failure_record = record_map.get(failure_step_id)
        failure_point = TracingPoint(
            step_id=failure_step_id,
            reason="Failure point: error exposure location",
            checkpoint_id=cp_index.get(failure_step_id),
            action=(
                failure_record.tool_name if failure_record else ""
            ),
            error=self._extract_error_from_record(failure_record),
        )
        chain.append(failure_point)

        # Upstream steps (reverse order: closest to failure point first)
        upstream_ids = self.find_upstream_steps(plan, failure_step_id)
        step_ids = [s.id for s in plan.choice.steps]
        # Arrange in reverse linear order (DAG mode also tries to maintain stable order)
        upstream_ordered = [
            sid for sid in reversed(step_ids) if sid in upstream_ids
        ]

        for sid in upstream_ordered:
            record = record_map.get(sid)
            reason = self._preliminary_judge(record, sid)
            chain.append(
                TracingPoint(
                    step_id=sid,
                    reason=reason,
                    checkpoint_id=cp_index.get(sid),
                    action=record.tool_name if record else "",
                    error="",
                )
            )

        return chain

    def _extract_error_from_record(
        self, record: StepRecord | None
    ) -> str:
        """Extract error info from execution record.

        Args:
            record: Step execution record

        Returns:
            Error info string
        """
        if record is None:
            return "No execution record"
        # Prefer extracting error from tool_output
        tool_output = record.tool_output
        if isinstance(tool_output, dict):
            for key in ("error", "exception", "message"):
                val = tool_output.get(key)
                if isinstance(val, str) and val:
                    return val
        # Then extract from output
        output = record.output
        if isinstance(output, dict):
            for key in ("error", "exception", "message"):
                val = output.get(key)
                if isinstance(val, str) and val:
                    return val
        return "Error info not recorded"

    def _preliminary_judge(
        self, record: StepRecord | None, step_id: str
    ) -> str:
        """Preliminary judgment of upstream steps (based on objective info from execution records).

        Args:
            record: Step execution record
            step_id: Step ID

        Returns:
            Preliminary judgment description
        """
        if record is None:
            return f"Step {step_id} has no execution record, cannot judge"

        parts: list[str] = []

        # Check Checkpoint result
        cp_result = record.checkpoint_result
        if cp_result is not None:
            if isinstance(cp_result, dict):
                passed = cp_result.get("passed")
                if passed is False:
                    parts.append("Checkpoint not passed")
                elif passed is True:
                    parts.append("Checkpoint passed")

        # Check whether tool_output has error markers
        tool_output = record.tool_output
        if isinstance(tool_output, dict):
            for key in ("error", "exception"):
                val = tool_output.get(key)
                if isinstance(val, str) and val:
                    parts.append(f"Tool output contains error: {val[:100]}")
                    break

        # Check dependent assumptions
        if record.assumptions:
            parts.append(f"Depends on {len(record.assumptions)} assumptions")

        if not parts:
            return f"Step {step_id} execution record has no abnormal markers"

        return "; ".join(parts)

    async def llm_trace_root_cause(
        self,
        plan: Plan,
        failure_info: str,
        step_records: list[StepRecord],
    ) -> FailureTracingResult:
        """LLM performs semantic root cause localization.

        Build prompt, call LLM for root cause localization. Includes:
        - Business root cause judgment
        - Goal change judgment
        - Constraint impact analysis
        - Result reusability analysis

        Returns complete FailureTracingResult (with four-point definition).
        Retries 3 times on JSON parse failure.

        Args:
            plan: Current Plan
            failure_info: Failure info description
            step_records: Step execution record list

        Returns:
            FailureTracingResult failure backtracking result
        """
        system_prompt = build_tracing_system_prompt()

        step_records_json = json.dumps(
            [r.model_dump() for r in step_records], ensure_ascii=False
        ) if step_records else ""

        user_prompt = build_tracing_user_prompt(
            plan.model_dump_json(),
            failure_info,
            step_records_json,
        )

        # Call LLM and parse, retry 3 times on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                return self._parse_tracing_result(data)
            except Exception as e:
                last_error = e
                logger.warning("Failure backtracking LLM call or parse failed: %s", e)

        # Parse failure fallback: return result containing only failure point
        logger.error(
            "Failure backtracking LLM parse failed, using fallback strategy. Last error: %s",
            last_error,
        )
        return self._build_fallback_result(plan, failure_info, step_records)

    def _parse_tracing_result(self, data: Any) -> FailureTracingResult:
        """Parse failure backtracking result returned by LLM.

        Args:
            data: Parsed JSON data

        Returns:
            FailureTracingResult failure backtracking result
        """
        # Parse failure point
        failure_point = TracingPoint.model_validate(data["failure_point"])

        # Parse root cause point (optional)
        root_cause_point = None
        if data.get("root_cause_point") is not None:
            root_cause_point = TracingPoint.model_validate(
                data["root_cause_point"]
            )

        # Parse rollback point (optional)
        rollback_point = None
        if data.get("rollback_point") is not None:
            rollback_point = TracingPoint.model_validate(
                data["rollback_point"]
            )

        # Parse replan start point (optional)
        replan_start_point = None
        if data.get("replan_start_point") is not None:
            replan_start_point = TracingPoint.model_validate(
                data["replan_start_point"]
            )

        # Parse reverse tracing chain
        tracing_chain = [
            TracingPoint.model_validate(tp)
            for tp in data.get("tracing_chain", [])
        ]

        # Parse checkpoint reliability
        checkpoint_reliable = data.get("checkpoint_reliable", True)

        return FailureTracingResult(
            failure_point=failure_point,
            root_cause_point=root_cause_point,
            rollback_point=rollback_point,
            replan_start_point=replan_start_point,
            tracing_chain=tracing_chain,
            checkpoint_reliable=checkpoint_reliable,
        )

    def _build_fallback_result(
        self,
        plan: Plan,
        failure_info: str,
        step_records: list[StepRecord],
    ) -> FailureTracingResult:
        """Build fallback failure backtracking result (used when LLM parse fails).

        Contains only the failure point; root cause point defaults to the failure point.

        Args:
            plan: Current Plan
            failure_info: Failure info description
            step_records: Step execution record list

        Returns:
            Fallback FailureTracingResult
        """
        # Try to parse failure step ID from failure_info
        failure_step_id = ""
        action = ""
        error = failure_info
        try:
            info_data = json.loads(failure_info)
            if isinstance(info_data, dict):
                failure_step_id = info_data.get("step_id", "")
                action = info_data.get("action", "")
                error = info_data.get("error", failure_info)
        except (json.JSONDecodeError, TypeError):
            pass

        # If no step_id parsed, try to take the last one from execution records
        if not failure_step_id and step_records:
            failure_step_id = step_records[-1].step_id
            record = step_records[-1]
            action = record.tool_name
            error = self._extract_error_from_record(record)

        # If still not found, use the first step of the Plan
        if not failure_step_id and plan.choice.steps:
            failure_step_id = plan.choice.steps[0].id

        failure_point = TracingPoint(
            step_id=failure_step_id,
            reason="LLM parse failed, fallback marked as failure point",
            action=action,
            error=error,
        )

        return FailureTracingResult(
            failure_point=failure_point,
            root_cause_point=None,
            rollback_point=None,
            replan_start_point=None,
            tracing_chain=[failure_point],
            checkpoint_reliable=False,
        )

    async def trace(
        self,
        plan: Plan,
        failure_step_id: str,
        failure_info: str,
        step_records: list[StepRecord],
    ) -> FailureTracingResult:
        """Complete backtracking flow.

        Flow:
        1. Code builds reverse tracing chain (build_tracing_chain)
        2. Code finds nearest Checkpoint (find_nearest_checkpoint)
        3. Code checks circular dependency (check_circular_dependency)
        4. LLM performs semantic root cause localization (llm_trace_root_cause)
        5. Merge code and LLM results, return FailureTracingResult

        Args:
            plan: Current Plan
            failure_step_id: Failure step ID
            failure_info: Failure info description
            step_records: Step execution record list

        Returns:
            FailureTracingResult failure backtracking result
        """
        # 1. Code builds reverse tracing chain
        tracing_chain = self.build_tracing_chain(
            plan, failure_step_id, step_records
        )
        logger.info(
            "Reverse tracing chain built, %d nodes total", len(tracing_chain)
        )

        # 2. Code finds nearest Checkpoint
        nearest_cp_step_id = self.find_nearest_checkpoint(
            plan, failure_step_id
        )
        if nearest_cp_step_id:
            logger.info(
                "Nearest Checkpoint-associated step: %s", nearest_cp_step_id
            )

        # 3. Code checks circular dependency
        has_cycle = self.check_circular_dependency(plan, failure_step_id)
        if has_cycle:
            logger.warning(
                "Circular dependency detected, may affect backtracking accuracy"
            )

        # 4. LLM performs semantic root cause localization
        result = await self.llm_trace_root_cause(
            plan, failure_info, step_records
        )

        # 5. Merge code and LLM results
        # If LLM didn't return tracing_chain or it's empty, use code-built chain
        if not result.tracing_chain:
            result.tracing_chain = tracing_chain
        else:
            # Merge: LLM result takes priority, supplement missing nodes from code-built chain
            llm_chain_ids = {
                tp.step_id for tp in result.tracing_chain
            }
            for tp in tracing_chain:
                if tp.step_id not in llm_chain_ids:
                    result.tracing_chain.append(tp)

        # If LLM didn't specify rollback point but code found nearest Checkpoint, supplement
        if (
            result.rollback_point is None
            and nearest_cp_step_id is not None
        ):
            result.rollback_point = TracingPoint(
                step_id=nearest_cp_step_id,
                reason="Code-located nearest Checkpoint-associated step",
                checkpoint_id=nearest_cp_step_id,
            )

        # If circular dependency exists, mark Checkpoint as unreliable
        if has_cycle:
            result.checkpoint_reliable = False

        # Code reviews Checkpoint reliability (overrides LLM judgment)
        result.checkpoint_reliable = self.review_checkpoint_reliability(
            plan, result, step_records
        )

        return result

    def review_checkpoint_reliability(
        self,
        plan: Plan,
        failure_result: FailureTracingResult,
        step_records: list[StepRecord],
    ) -> bool:
        """Review Checkpoint reliability.

        Code method. Review rules:
        - If Checkpoint is code-implemented (step execution record has checkpoint_result), high trust
        - If failure point is shortly after Checkpoint passed (intermediate steps <= 2), suspect Checkpoint
        - If reverse tracing finds Checkpoint context data may have issues, mark as unreliable

        Args:
            plan: Current Plan
            failure_result: Failure backtracking result
            step_records: Step execution record list

        Returns:
            True means Checkpoint is reliable, False means unreliable
        """
        step_ids = [s.id for s in plan.choice.steps]
        failure_step_id = failure_result.failure_point.step_id

        # No Checkpoint, unreliable
        if not plan.checkpoint:
            return False

        # Find the nearest Checkpoint step
        nearest_cp_step_id = self.find_nearest_checkpoint(
            plan, failure_step_id
        )
        if nearest_cp_step_id is None:
            return False

        # Rule 1: Whether Checkpoint is code-implemented (execution record has checkpoint_result)
        record_map: dict[str, StepRecord] = {
            r.step_id: r for r in step_records
        }
        cp_record = record_map.get(nearest_cp_step_id)
        if cp_record is None or cp_record.checkpoint_result is None:
            # Checkpoint not executed or result not recorded, unreliable
            return False

        # Only need further review if Checkpoint result is pass
        cp_result = cp_record.checkpoint_result
        if isinstance(cp_result, dict):
            passed = cp_result.get("passed")
            if passed is False:
                # Checkpoint not passed, means it caught the issue, reliable
                return True

        # Rule 2: Failure point shortly after Checkpoint passed, suspect Checkpoint missed
        if failure_step_id in step_ids and nearest_cp_step_id in step_ids:
            cp_idx = step_ids.index(nearest_cp_step_id)
            fail_idx = step_ids.index(failure_step_id)
            steps_between = fail_idx - cp_idx
            if 0 < steps_between <= 2:
                # Failure point very close to Checkpoint, suspect Checkpoint missed
                logger.warning(
                    "Failure point is only %d steps from nearest Checkpoint, suspect Checkpoint missed",
                    steps_between,
                )
                return False

        # Rule 3: Whether there are context data issues in the reverse tracing chain
        # Check whether facts used by Checkpoint step have been updated
        for tp in failure_result.tracing_chain:
            record = record_map.get(tp.step_id)
            if record is None:
                continue
            # If the step's reason mentions error or exception
            if "error" in tp.reason.lower() or "exception" in tp.reason.lower() or "not passed" in tp.reason.lower():
                # If the problem step is at or before the Checkpoint step, Checkpoint may have missed
                if tp.step_id == nearest_cp_step_id:
                    return False
                # If the problem step is before the Checkpoint (upstream), Checkpoint should be able to catch
                if tp.step_id in step_ids and nearest_cp_step_id in step_ids:
                    problem_idx = step_ids.index(tp.step_id)
                    if problem_idx <= cp_idx:
                        # Problem before Checkpoint, but Checkpoint didn't catch it, unreliable
                        return False

        return True

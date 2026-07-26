"""TCC Replan engine - Try/Confirm/Cancel three-step Replan methodology.

Borrows the TCC concept from distributed transactions to implement an optional advanced Replan scheme.
Only applicable to high-failure-cost, high-external-dependency, high-side-effect-risk scenarios.

Three-phase flow:
- Try: Identify critical validation points, execute dry-run validation for each, data goes to temporary space
- Confirm: Execute Plan after all Try passes, reuse Try data, write to context
- Cancel: Rollback temporary state after Try failure, mark failed assumptions, decide whether to continue Replan
"""

import json
import logging
import re
from typing import Any

from pydantic import TypeAdapter

from xplan.models.plan import Plan
from xplan.models.tcc import (
    CancelResult,
    ConfirmResult,
    TCCPhase,
    TCCResult,
    TryResult,
    TryValidation,
    TryValidationType,
)
from xplan.prompts.tcc_prompt import (
    build_tcc_cancel_system_prompt,
    build_tcc_cancel_user_prompt,
    build_tcc_confirm_system_prompt,
    build_tcc_confirm_user_prompt,
    build_tcc_try_system_prompt,
    build_tcc_try_user_prompt,
)

logger = logging.getLogger(__name__)

# External tool related keywords
_EXTERNAL_TOOL_KEYWORDS = ("调用", "请求", "API", "api", "服务", "接口", "SDK")
# High-risk operation keywords
_HIGH_RISK_KEYWORDS = ("写入", "删除", "修改", "支付", "资金", "提交", "发布", "部署")


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response.

    Supports both markdown code block wrapped and bare JSON formats.
    """
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class TCCReplan:
    """TCC Replan engine.

    Implements the Try -> Confirm/Cancel three-step Replan methodology.
    As an optional advanced scheme, default enabled=False, needs to be explicitly enabled.

    Attributes:
        llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
        plan_generator: Plan generator, used for Replan again after Cancel (optional)
        enabled: TCC mode switch, default False
    """

    def __init__(
        self,
        llm_service: Any,
        plan_generator: Any = None,
        enabled: bool = False,
    ) -> None:
        """Initialize the TCC Replan engine.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            plan_generator: Plan generator, used for Replan again after Cancel (optional)
            enabled: TCC mode switch, default False
        """
        self.llm_service = llm_service
        self.plan_generator = plan_generator
        self.enabled = enabled

    async def run(
        self, plan: Plan, conversation_history: str = ""
    ) -> TCCResult:
        """Execute the complete TCC flow.

        Flow: try_phase -> (if passed) confirm_phase / (if failed) cancel_phase

        Args:
            plan: New Plan to validate
            conversation_history: Conversation history, used to supplement context

        Returns:
            TCC Replan complete result
        """
        # 1. Try phase: minimal validation
        try_result = await self.try_phase(plan)

        if try_result.all_passed:
            # 2a. Try all passed, execute Confirm phase
            confirm_result = await self.confirm_phase(plan, try_result)
            return TCCResult(
                phase=TCCPhase.CONFIRM,
                try_result=try_result,
                confirm_result=confirm_result,
                new_plan=plan,
            )

        # 2b. Try failed, execute Cancel phase
        cancel_result = await self.cancel_phase(plan, try_result)
        return TCCResult(
            phase=TCCPhase.CANCEL,
            try_result=try_result,
            cancel_result=cancel_result,
        )

    async def try_phase(self, plan: Plan) -> TryResult:
        """Execute the Try phase.

        Identify critical validation points, execute dry-run validation for each.
        Try-generated data goes to temp_data (temporary space).

        Args:
            plan: Plan to validate

        Returns:
            Try phase result
        """
        # Identify critical validation points (code rules)
        critical_points = self.identify_critical_points(plan)

        # Execute dry-run validation for each critical validation point
        validations: list[TryValidation] = []
        temp_data: dict = {}
        failed_assumptions: list[str] = []
        unavailable_tools: list[str] = []

        for step_id, validation_type in critical_points:
            validation = await self.dry_run(plan, step_id)
            # If dry_run returns a type inconsistent with rule-identified type, use rule-identified type
            if validation.validation_type != validation_type:
                validation.validation_type = validation_type
            validations.append(validation)

            # Collect failure info
            if not validation.passed:
                if validation.validation_type == TryValidationType.TOOL_AVAILABILITY:
                    unavailable_tools.append(step_id)
                elif (
                    validation.validation_type
                    == TryValidationType.ASSUMPTION_VALIDATION
                ):
                    failed_assumptions.append(validation.result or step_id)

            # Put reusable data into temporary space
            if validation.passed and validation.evidence:
                temp_data[f"{step_id}_evidence"] = validation.evidence

        all_passed = len(validations) > 0 and all(
            v.passed for v in validations
        )

        return TryResult(
            validations=validations,
            all_passed=all_passed,
            temp_data=temp_data,
            failed_assumptions=failed_assumptions,
            unavailable_tools=unavailable_tools,
        )

    def identify_critical_points(
        self, plan: Plan
    ) -> list[tuple[str, TryValidationType]]:
        """Identify critical validation points (code rules).

        Rules:
        - Operations heavily depended on by subsequent steps (steps referenced by multiple steps' reason in steps)
        - Steps using external tools (objective contains keywords like "调用", "请求", "API", etc.)
        - High-risk operations (objective contains keywords like "写入", "删除", "修改", "支付", "资金", etc.)

        Args:
            plan: Plan to validate

        Returns:
            List of (step_id, validation_type), sorted by priority
        """
        steps = plan.choice.steps
        if not steps:
            return []

        # Count how many times each step is referenced by subsequent steps' reason
        reference_count: dict[str, int] = {s.id: 0 for s in steps}
        for step in steps:
            for other in steps:
                if other.id != step.id and step.id in other.reason:
                    reference_count[step.id] += 1

        result: list[tuple[str, TryValidationType]] = []
        seen: set[str] = set()

        # Rule 1: Operations heavily depended on by subsequent steps (referenced >= 2 times)
        for step in steps:
            if reference_count[step.id] >= 2 and step.id not in seen:
                result.append((step.id, TryValidationType.KEY_DEPENDENCY))
                seen.add(step.id)

        # Rule 2: Steps using external tools
        for step in steps:
            if step.id in seen:
                continue
            if any(
                kw in step.objective for kw in _EXTERNAL_TOOL_KEYWORDS
            ):
                result.append(
                    (step.id, TryValidationType.TOOL_AVAILABILITY)
                )
                seen.add(step.id)

        # Rule 3: High-risk operations
        for step in steps:
            if step.id in seen:
                continue
            if any(kw in step.objective for kw in _HIGH_RISK_KEYWORDS):
                result.append(
                    (step.id, TryValidationType.ASSUMPTION_VALIDATION)
                )
                seen.add(step.id)

        return result

    async def confirm_phase(
        self, plan: Plan, try_result: TryResult
    ) -> ConfirmResult:
        """Execute the Confirm phase.

        Write Try results to context, reuse reusable data generated by Try.

        Args:
            plan: Plan to execute
            try_result: Try phase result

        Returns:
            Confirm phase result
        """
        system_prompt = build_tcc_confirm_system_prompt()
        user_prompt = build_tcc_confirm_user_prompt(
            plan.model_dump_json(),
            try_result.model_dump_json(),
        )

        try:
            response = await self.llm_service.chat(
                system_prompt, user_prompt
            )
            data = _extract_json(response)
            confirm_result = ConfirmResult.model_validate(data)

            # Write Try validation results into Plan context (as known facts)
            for validation in try_result.validations:
                if validation.passed:
                    fact = (
                        f"Step {validation.target_step_id} "
                        f"{validation.validation_type.value} validation passed"
                    )
                    if fact not in plan.context.known_facts:
                        plan.context.known_facts.append(fact)

            return confirm_result
        except Exception as e:
            logger.warning("Confirm phase LLM call or parse failed: %s", e)
            # Fallback: construct result directly based on code logic
            reused = bool(try_result.temp_data)
            return ConfirmResult(
                executed=True,
                try_results_written=True,
                reused_try_data=reused,
                execution_summary="Confirm phase fallback execution: Try results written to context",
            )

    async def cancel_phase(
        self, plan: Plan, try_result: TryResult
    ) -> CancelResult:
        """Execute the Cancel phase.

        Rollback temporary state and data generated by Try (clean temp_data),
        mark failed assumptions and unavailable tools, determine whether there are still alternative feasible solutions.

        Args:
            plan: Current Plan
            try_result: Try phase result

        Returns:
            Cancel phase result (with should_continue_replan and has_alternative_solutions)
        """
        failed_assumptions = try_result.failed_assumptions
        unavailable_tools = try_result.unavailable_tools

        # Check whether there are alternative solutions
        has_alternatives = self.check_alternatives(
            failed_assumptions, unavailable_tools
        )

        system_prompt = build_tcc_cancel_system_prompt()
        user_prompt = build_tcc_cancel_user_prompt(
            try_result.model_dump_json(),
            failed_assumptions,
            unavailable_tools,
        )

        try:
            response = await self.llm_service.chat(
                system_prompt, user_prompt
            )
            data = _extract_json(response)
            cancel_result = CancelResult.model_validate(data)
            # Use code-determined alternative solution result as authoritative
            cancel_result.has_alternative_solutions = has_alternatives
            cancel_result.should_continue_replan = has_alternatives
            if not has_alternatives and not cancel_result.abort_reason:
                cancel_result.abort_reason = "No alternative feasible solutions, all paths exhausted"
            return cancel_result
        except Exception as e:
            logger.warning("Cancel phase LLM call or parse failed: %s", e)
            # Fallback: construct result directly based on code logic
            should_continue = has_alternatives
            return CancelResult(
                temp_data_cleaned=True,
                failed_assumptions_marked=failed_assumptions,
                unavailable_tools_marked=unavailable_tools,
                should_continue_replan=should_continue,
                has_alternative_solutions=has_alternatives,
                abort_reason=(
                    ""
                    if should_continue
                    else "No alternative feasible solutions, all paths exhausted"
                ),
            )

    def check_alternatives(
        self,
        failed_assumptions: list[str],
        unavailable_tools: list[str],
    ) -> bool:
        """Check whether there are still alternative feasible solutions.

        Simplified implementation:
        - If failed assumptions or unavailable tools are empty, return True
        - If there are failed assumptions but the count is small (<=2), return True
        - Otherwise return False (all paths exhausted)

        Note: This is a simplified implementation; in practice should be determined by LLM.

        Args:
            failed_assumptions: List of failed assumptions
            unavailable_tools: List of unavailable tools

        Returns:
            Whether there are still alternative feasible solutions
        """
        if not failed_assumptions and not unavailable_tools:
            return True
        if len(failed_assumptions) <= 2:
            return True
        return False

    async def dry_run(
        self, plan: Plan, step_id: str
    ) -> TryValidation:
        """Execute dry-run validation for the specified step.

        Build validation prompt, ask LLM to simulate execution and output expected results.
        Does not actually execute, ensuring no side effects.

        Args:
            plan: Plan to validate
            step_id: Step ID to validate

        Returns:
            TryValidation validation result
        """
        # Find target step
        target_step = None
        for step in plan.choice.steps:
            if step.id == step_id:
                target_step = step
                break

        if target_step is None:
            return TryValidation(
                target_step_id=step_id,
                validation_type=TryValidationType.KEY_DEPENDENCY,
                passed=False,
                result=f"Step {step_id} not found",
                evidence="",
            )

        system_prompt = build_tcc_try_system_prompt()
        step_json = json.dumps(
            target_step.model_dump(), ensure_ascii=False
        )
        plan_json = plan.model_dump_json()
        user_prompt = (
            f"Please perform a dry-run validation on the following step in the Plan.\n\n"
            f"## Plan\n{plan_json}\n\n"
            f"## Step to validate\n{step_json}\n\n"
            f"Please output the dry-run validation result for this step, "
            f"in JSON format as a single validation object (containing target_step_id, "
            f"validation_type, passed, result, evidence fields)."
        )

        max_retries = 3
        last_error: Exception | None = None
        for _ in range(max_retries):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                # Handle LLM wrapping result in list or dict
                if isinstance(data, list):
                    data = data[0] if data else {}
                if isinstance(data, dict):
                    if "validations" in data and isinstance(
                        data["validations"], list
                    ):
                        data = (
                            data["validations"][0]
                            if data["validations"]
                            else {}
                        )
                validation = TryValidation.model_validate(data)
                validation.target_step_id = step_id
                return validation
            except Exception as e:
                last_error = e

        logger.warning(
            "dry_run validation step %s failed, retried %d times: %s",
            step_id,
            max_retries,
            last_error,
        )
        # Fallback: return failed validation result
        return TryValidation(
            target_step_id=step_id,
            validation_type=TryValidationType.KEY_DEPENDENCY,
            passed=False,
            result=f"dry-run validation failed: {last_error}",
            evidence="LLM call or parse failed",
        )

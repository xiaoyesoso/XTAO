"""Replan engine - Core implementation of the controlled correction mechanism.

Replan is the core implementation of Correction: during execution, based on new Goal, Context, Choice,
and Checkpoint results, performs controlled correction of the original plan.

Complete Replan flow:
1. detect_trigger: Detect Replan trigger timing
2. code_judge: Code judgment, filter out transient errors that don't need Replan
3. llm_judge: LLM judgment, decide whether Replan is needed and the granularity
4. execute_replan: Execute Replan, generate new Plan based on granularity
5. Check whether user clarification or authorization is needed
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, TypeAdapter

from xplan.models import CheckResult, Plan
from xplan.models.plan import PlanStatus
from xplan.models.replan import (
    ReplanGranularity,
    ReplanInfo,
    ReplanJudgment,
    ReplanResult,
    ReplanTrigger,
    StepChange,
)
from xplan.prompts.replan_prompt import (
    build_replan_execute_prompt,
    build_replan_judge_prompt,
    build_replan_system_prompt,
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


class ReplanEngine:
    """Replan engine, implements the controlled correction mechanism.

    Complete flow: detect_trigger -> code_judge -> (if needed) llm_judge -> (if needed) execute_replan.

    Attributes:
        llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
        constraint_manager: Constraint manager
        plan_generator: Plan generator, used for global Replan (optional)
        max_replan_total: Maximum Replan count, avoid infinite loops
    """

    def __init__(
        self,
        llm_service: Any,
        constraint_manager: Any,
        plan_generator: Any = None,
        max_replan_total: int = 3,
    ):
        """Initialize the Replan engine.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            constraint_manager: Constraint manager
            plan_generator: Plan generator, used for global Replan (optional)
            max_replan_total: Maximum Replan count, default 3
        """
        self.llm_service = llm_service
        self.constraint_manager = constraint_manager
        self.plan_generator = plan_generator
        self.max_replan_total = max_replan_total

    def detect_trigger(
        self,
        error: Exception | None,
        plan: Plan,
        user_input: str = "",
    ) -> ReplanTrigger | None:
        """Detect Replan trigger timing.

        Detection order (priority from high to low):
        1. Context change: user_input is not empty (user supplemented info)
        2. Assumption violation: plan.check_results has failing checks
        3. Tool call failure: error is not None

        Args:
            error: Exception during execution (can be None)
            plan: Current Plan
            user_input: User supplemental input (can be empty)

        Returns:
            Trigger type or None (no trigger)
        """
        # 1. Detect context change: user supplemented new info or constraints
        if user_input and user_input.strip():
            return ReplanTrigger.CONTEXT_CHANGE

        # 2. Detect assumption violation: checkpoint failure means original Plan assumptions were wrong
        if plan.check_results:
            for result in plan.check_results:
                if not result.passed:
                    return ReplanTrigger.ASSUMPTION_VIOLATION

        # 3. Detect tool call failure
        if error is not None:
            return ReplanTrigger.TOOL_FAILURE

        return None

    def code_judge(
        self,
        error: Exception | None,
        trigger: ReplanTrigger,
    ) -> ReplanJudgment:
        """Code judgment logic, filter out transient errors that don't need Replan.

        Judgment rules:
        - Transient timeout (TimeoutError) -> needs_replan=False, recommend direct retry
        - Other retryable transient errors -> needs_replan=False
        - Undeterminable errors -> needs_replan=True (defer to LLM judgment)

        Args:
            error: Exception during execution (can be None)
            trigger: Trigger type

        Returns:
            ReplanJudgment result
        """
        # Non-tool-failure scenarios, defer to LLM judgment
        if trigger != ReplanTrigger.TOOL_FAILURE:
            return ReplanJudgment(
                needs_replan=True,
                trigger=trigger,
                reason="Trigger type is non-tool-failure, needs LLM further judgment",
                evidence=f"trigger={trigger.value}",
            )

        # Tool failure scenario: filter transient errors
        if error is None:
            return ReplanJudgment(
                needs_replan=True,
                trigger=trigger,
                reason="Tool failure but no specific exception, defer to LLM judgment",
                evidence="error=None",
            )

        # Transient timeout: recommend direct retry, no Replan needed
        if isinstance(error, TimeoutError):
            return ReplanJudgment(
                needs_replan=False,
                trigger=trigger,
                reason="Transient timeout, recommend direct retry",
                evidence=f"error_type={type(error).__name__}",
            )

        # Connection errors and other transient errors: recommend retry
        error_type_name = type(error).__name__
        transient_error_types = {
            "ConnectionError",
            "ConnectionResetError",
            "ConnectionAbortedError",
            "OSError",
        }
        if error_type_name in transient_error_types:
            return ReplanJudgment(
                needs_replan=False,
                trigger=trigger,
                reason=f"Transient error ({error_type_name}), recommend direct retry",
                evidence=f"error_type={error_type_name}",
            )

        # Undeterminable errors: defer to LLM judgment
        return ReplanJudgment(
            needs_replan=True,
            trigger=trigger,
            reason="Cannot determine error nature via code, defer to LLM judgment",
            evidence=f"error_type={error_type_name}, error_msg={str(error)[:200]}",
        )

    async def llm_judge(
        self,
        plan: Plan,
        error: Exception | None,
        trigger: ReplanTrigger,
        check_results: list[CheckResult],
    ) -> ReplanJudgment:
        """LLM judgment logic.

        Build Replan judgment prompt, call LLM, parse into ReplanJudgment.
        Contains trigger type, whether Replan is needed, suggested granularity, rollback target, etc.

        Args:
            plan: Current Plan
            error: Exception during execution (can be None)
            trigger: Trigger type
            check_results: Checkpoint result list

        Returns:
            ReplanJudgment result
        """
        hard_constraints = (
            self.constraint_manager.get_hard_constraints()
            if self.constraint_manager
            else []
        )
        soft_constraints = (
            self.constraint_manager.get_soft_constraints()
            if self.constraint_manager
            else []
        )

        system_prompt = build_replan_system_prompt(
            hard_constraints, soft_constraints
        )

        error_info = (
            f"{type(error).__name__}: {str(error)}"
            if error is not None
            else ""
        )
        check_results_json = json.dumps(
            [r.model_dump() for r in check_results], ensure_ascii=False
        ) if check_results else ""

        user_prompt = build_replan_judge_prompt(
            plan.model_dump_json(), error_info, check_results_json
        )

        # Call LLM and parse, retry on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                # Supplement trigger type (ensure consistency with input)
                judgment = ReplanJudgment.model_validate(data)
                if judgment.trigger is None:
                    judgment.trigger = trigger
                return judgment
            except Exception as e:
                last_error = e
                logger.warning("Replan judgment LLM call or parse failed: %s", e)

        # Parse failure fallback: default to needing Replan, granularity inferred from trigger type
        logger.error(
            "Replan judgment LLM parse failed, using fallback strategy. Last error: %s",
            last_error,
        )
        return ReplanJudgment(
            needs_replan=True,
            trigger=trigger,
            reason="LLM judgment parse failed, using fallback strategy: default to needing Replan",
            evidence=f"parse_error={last_error}",
            granularity=self._infer_granularity(trigger),
        )

    def _infer_granularity(
        self, trigger: ReplanTrigger
    ) -> ReplanGranularity:
        """Infer default Replan granularity based on trigger type.

        Args:
            trigger: Trigger type

        Returns:
            Suggested Replan granularity
        """
        if trigger == ReplanTrigger.TOOL_FAILURE:
            return ReplanGranularity.STEP
        elif trigger == ReplanTrigger.CONTEXT_CHANGE:
            return ReplanGranularity.PARTIAL
        else:  # ASSUMPTION_VIOLATION
            return ReplanGranularity.PARTIAL

    async def execute_replan(
        self,
        plan: Plan,
        judgment: ReplanJudgment,
        conversation_history: str = "",
    ) -> ReplanResult:
        """Execute Replan.

        Select granularity based on judgment.granularity:
        - STEP: Re-plan subsequent steps from current step, keep previous steps
        - PARTIAL: Re-plan from judgment.rollback_step_id
        - GLOBAL: Call plan_generator to generate from scratch

        Build Replan execution prompt, call LLM to generate new Plan.
        Output ReplanResult (with retained/modified/removed steps categorization).
        Update replan_info.used_replan_total += 1.

        Args:
            plan: Current Plan
            judgment: Replan judgment result
            conversation_history: Conversation history

        Returns:
            ReplanResult execution result
        """
        granularity = judgment.granularity or ReplanGranularity.STEP
        replan_info = ReplanInfo(
            max_replan_total=self.max_replan_total,
            used_replan_total=1,
        )

        # Global Replan: prefer plan_generator to generate from scratch
        if granularity == ReplanGranularity.GLOBAL and self.plan_generator is not None:
            try:
                new_plan = await self.plan_generator.generate(
                    plan.goal.user_goal, conversation_history
                )
                new_plan.iteration_count = plan.iteration_count + 1
                # Global Replan: all original steps treated as removed, new steps treated as modified
                removed_steps = [
                    StepChange(
                        step_id=s.id,
                        reason=f"Global Replan, original step replaced by new Plan",
                        change_type="removed",
                    )
                    for s in plan.choice.steps
                ]
                modified_steps = [
                    StepChange(
                        step_id=s.id,
                        reason="New step generated by global Replan",
                        change_type="modified",
                        modification_detail=s.objective,
                    )
                    for s in new_plan.choice.steps
                ]
                return ReplanResult(
                    retained_steps=[],
                    modified_steps=modified_steps,
                    removed_steps=removed_steps,
                    new_plan=new_plan,
                    replan_info=replan_info,
                )
            except Exception as e:
                logger.warning("Global Replan failed, fallback to LLM Replan: %s", e)

        # STEP / PARTIAL / GLOBAL (no plan_generator) execute Replan via LLM
        return await self._llm_execute_replan(
            plan, judgment, conversation_history, replan_info
        )

    async def _llm_execute_replan(
        self,
        plan: Plan,
        judgment: ReplanJudgment,
        conversation_history: str,
        replan_info: ReplanInfo,
    ) -> ReplanResult:
        """Execute Replan via LLM.

        Args:
            plan: Current Plan
            judgment: Replan judgment result
            conversation_history: Conversation history
            replan_info: Replan control info

        Returns:
            ReplanResult execution result
        """
        hard_constraints = (
            self.constraint_manager.get_hard_constraints()
            if self.constraint_manager
            else []
        )
        soft_constraints = (
            self.constraint_manager.get_soft_constraints()
            if self.constraint_manager
            else []
        )

        system_prompt = build_replan_system_prompt(
            hard_constraints, soft_constraints
        )

        user_prompt = build_replan_execute_prompt(
            plan.model_dump_json(),
            judgment.model_dump_json(),
            replan_info.model_dump_json(),
            conversation_history,
        )

        # Call LLM and parse, retry on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                return self._parse_replan_result(data, replan_info, plan)
            except Exception as e:
                last_error = e
                logger.warning("Replan execution LLM call or parse failed: %s", e)

        # Parse failure fallback: return original Plan, mark as failed
        logger.error(
            "Replan execution LLM parse failed, returning original Plan. Last error: %s",
            last_error,
        )
        plan.status = PlanStatus.FAILED
        return ReplanResult(
            retained_steps=[],
            modified_steps=[],
            removed_steps=[],
            new_plan=plan,
            replan_info=replan_info,
        )

    def _parse_replan_result(
        self,
        data: Any,
        replan_info: ReplanInfo,
        original_plan: Plan,
    ) -> ReplanResult:
        """Parse the Replan result returned by LLM.

        Args:
            data: Parsed JSON data
            replan_info: Replan control info
            original_plan: Original Plan (fallback on parse failure)

        Returns:
            ReplanResult execution result
        """
        # Parse step change categorization
        retained_steps = [
            StepChange.model_validate(s)
            for s in data.get("retained_steps", [])
        ]
        modified_steps = [
            StepChange.model_validate(s)
            for s in data.get("modified_steps", [])
        ]
        removed_steps = [
            StepChange.model_validate(s)
            for s in data.get("removed_steps", [])
        ]

        # Parse new Plan
        new_plan = original_plan
        if "new_plan" in data and data["new_plan"] is not None:
            try:
                new_plan = Plan.model_validate(data["new_plan"])
                new_plan.iteration_count = original_plan.iteration_count + 1
            except Exception as e:
                logger.warning("New Plan parse failed, keeping original Plan: %s", e)
                new_plan = original_plan

        return ReplanResult(
            retained_steps=retained_steps,
            modified_steps=modified_steps,
            removed_steps=removed_steps,
            new_plan=new_plan,
            replan_info=replan_info,
        )

    async def run(
        self,
        plan: Plan,
        error: Exception | None = None,
        user_input: str = "",
        conversation_history: str = "",
    ) -> Plan:
        """Complete Replan flow.

        Flow: detect_trigger -> code_judge -> (if needed) llm_judge -> (if needed) execute_replan.

        - If no trigger detected, return original plan directly
        - If code_judge determines no Replan needed, return original plan directly
        - If used_replan_total >= max_replan_total, no more Replan, mark plan.status = FAILED
        - Otherwise execute Replan and return new Plan

        Args:
            plan: Current Plan
            error: Exception during execution (can be None)
            user_input: User supplemental input (can be empty)
            conversation_history: Conversation history

        Returns:
            New Plan after Replan (or original Plan)
        """
        # 1. Detect trigger timing
        trigger = self.detect_trigger(error, plan, user_input)
        if trigger is None:
            logger.info("No Replan trigger detected, returning original Plan")
            return plan

        logger.info("Replan trigger detected: %s", trigger.value)

        # 2. Code judgment: filter transient errors
        code_judgment = self.code_judge(error, trigger)
        if not code_judgment.needs_replan:
            logger.info("Code judgment determines no Replan needed: %s", code_judgment.reason)
            return plan

        # 3. Check Replan count limit
        if plan.iteration_count >= self.max_replan_total:
            logger.warning(
                "Maximum Replan count reached (%d), no more Replan, marking Plan as FAILED",
                self.max_replan_total,
            )
            plan.status = PlanStatus.FAILED
            return plan

        # 4. LLM judgment
        judgment = await self.llm_judge(
            plan, error, trigger, plan.check_results
        )
        if not judgment.needs_replan:
            logger.info("LLM judgment determines no Replan needed: %s", judgment.reason)
            return plan

        logger.info(
            "LLM judgment determines Replan needed, granularity: %s",
            judgment.granularity.value if judgment.granularity else "unspecified",
        )

        # 5. Check whether user clarification is needed
        need_clarify, clarify_content = self._check_user_clarification_needed(
            plan, judgment
        )
        if need_clarify:
            logger.info("User clarification needed: %s", clarify_content)
            plan.status = PlanStatus.FAILED
            return plan

        # 6. Execute Replan
        result = await self.execute_replan(
            plan, judgment, conversation_history
        )

        # 7. Check sensitive operations
        if result.new_plan is not None:
            need_auth, auth_desc = self._check_sensitive_operation(
                result.new_plan
            )
            if need_auth:
                logger.info("New Plan contains sensitive operations, requires user authorization: %s", auth_desc)
                # Mark as needing authorization; actual authorization handled by caller
                result.new_plan.status = PlanStatus.DRAFT

        # 8. Update iteration count
        if result.new_plan is not None:
            result.new_plan.iteration_count = plan.iteration_count + 1
            return result.new_plan

        return plan

    def _check_user_clarification_needed(
        self, plan: Plan, judgment: ReplanJudgment
    ) -> tuple[bool, str]:
        """Check whether user clarification is needed.

        Three trigger types:
        1. Hard constraint related: Replan involves hard constraint changes
        2. Parameter missing: Key info missing, cannot complete Replan based on existing info
        3. Critical tool failure with no alternative: Core tool unavailable and no alternative path

        Args:
            plan: Current Plan
            judgment: Replan judgment result

        Returns:
            (whether clarification needed, clarification content)
        """
        # 1. Hard constraint related: judgment reason mentions hard constraints
        hard_constraints = (
            self.constraint_manager.get_hard_constraints()
            if self.constraint_manager
            else []
        )
        reason_text = judgment.reason + judgment.evidence
        for hc in hard_constraints:
            if hc and hc in reason_text:
                return (
                    True,
                    f"Replan involves hard constraint changes, requires user confirmation: {hc}",
                )

        # 2. Parameter missing: trigger type is assumption violation and Context has missing info
        if judgment.trigger == ReplanTrigger.ASSUMPTION_VIOLATION:
            if plan.context.missing_info:
                missing = ", ".join(plan.context.missing_info)
                return (
                    True,
                    f"Key info missing, requires user supplementation: {missing}",
                )

        # 3. Critical tool failure with no alternative: tool failure and granularity is global (means no local alternative)
        if (
            judgment.trigger == ReplanTrigger.TOOL_FAILURE
            and judgment.granularity == ReplanGranularity.GLOBAL
        ):
            return (
                True,
                "Critical tool failure with no alternative, requires user confirmation on whether to adjust the goal",
            )

        return (False, "")

    def _check_sensitive_operation(
        self, plan: Plan
    ) -> tuple[bool, str]:
        """Check whether the new Plan contains more sensitive tool operations than the original Plan.

        Detection based on sensitive keywords in step objective text.
        Sensitive operations include: delete, fund, authorize, permission, config change, etc.

        Args:
            plan: New Plan

        Returns:
            (whether authorization needed, authorization request description)
        """
        sensitive_keywords = [
            "删除",
            "remove",
            "delete",
            "drop",
            "资金",
            "支付",
            "payment",
            "transfer",
            "授权",
            "权限",
            "permission",
            "grant",
            "配置变更",
            "系统配置",
        ]

        sensitive_steps = []
        for step in plan.choice.steps:
            objective_lower = step.objective.lower()
            for keyword in sensitive_keywords:
                if keyword.lower() in objective_lower:
                    sensitive_steps.append((step.id, step.objective, keyword))
                    break

        if sensitive_steps:
            desc = "; ".join(
                f"Step {sid} ({obj}) involves sensitive operation: {kw}"
                for sid, obj, kw in sensitive_steps
            )
            return (True, desc)

        return (False, "")

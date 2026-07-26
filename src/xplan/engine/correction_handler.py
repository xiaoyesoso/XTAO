"""Correction handler - Handle execution deviations based on correction rules.

Supports five correction strategies:
- RETRY: Retry based on granularity (step/partial_flow/full_restart), without modifying Plan structure
- REPLAN: Call plan_generator to regenerate Plan
- CLARIFY: Return info requiring user clarification (marked in plan)
- ROLLBACK: Rollback to the state before target_step_id
- ABORT: Abort execution, mark plan.status = ABORTED
"""

from typing import Any

from xplan.models import Correction, CorrectionType, Plan
from xplan.models.correction import RetryGranularity
from xplan.models.plan import PlanStatus


class CorrectionHandler:
    """Correction handler.

    Executes the corresponding correction strategy based on Correction rule's action.type.
    action is equivalent to the action in the TAO/ReAct loop, supporting complex parameters and tool/Skill integration.
    """

    def __init__(
        self,
        llm_service: Any,
        plan_generator: Any = None,
        replan_engine: Any = None,
    ):
        """Initialize the correction handler.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            plan_generator: Plan generator, used to regenerate Plan for REPLAN strategy (optional)
            replan_engine: Replan engine, preferred for REPLAN strategy (optional)
        """
        self.llm_service = llm_service
        self.plan_generator = plan_generator
        self.replan_engine = replan_engine

    async def handle(self, correction: Correction, plan: Plan) -> Plan:
        """Handle based on correction rule.

        Dispatches to the corresponding correction strategy based on action.type:
        - RETRY: Retry based on granularity, without modifying Plan structure
        - REPLAN: Call plan_generator to regenerate Plan
        - CLARIFY: Mark in plan that user clarification is needed
        - ROLLBACK: Rollback to the state before target_step_id
        - ABORT: Abort execution

        Args:
            correction: Correction rule
            plan: Current Plan

        Returns:
            Handled Plan (may be the modified original Plan or a newly generated Plan)
        """
        action = correction.action

        if action.type == CorrectionType.RETRY:
            # Retry: based on granularity, without modifying Plan structure
            granularity = action.retry_granularity or RetryGranularity.STEP
            if granularity == RetryGranularity.STEP:
                return await self.retry_step(plan, plan.current_step_index)
            elif granularity == RetryGranularity.PARTIAL_FLOW:
                return await self.retry_partial_flow(
                    plan, plan.current_step_index
                )
            else:  # FULL_RESTART
                return await self.retry_partial_flow(plan, 0)

        elif action.type == CorrectionType.REPLAN:
            # Regenerate Plan: used when the Plan itself has issues
            # Prefer ReplanEngine (controlled correction), then plan_generator
            if self.replan_engine is not None:
                # Execute controlled correction via ReplanEngine
                error_info = action.message or ""
                new_plan = await self.replan_engine.run(
                    plan,
                    error=Exception(error_info) if error_info else None,
                )
                return new_plan
            if self.plan_generator is not None:
                # Regenerate using the original user goal as input
                new_plan = await self.plan_generator.generate(
                    plan.goal.user_goal
                )
                new_plan.iteration_count = plan.iteration_count + 1
                return new_plan
            # Fall back to full retry when no plan_generator
            return await self.retry_partial_flow(plan, 0)

        elif action.type == CorrectionType.CLARIFY:
            # User clarification needed: mark in plan
            # Set status to FAILED; caller can get clarification content via correction.action.message
            plan.status = PlanStatus.FAILED
            return plan

        elif action.type == CorrectionType.ROLLBACK:
            # Rollback to before the specified step
            target_step_id = action.target_step_id or ""
            return await self.rollback_to_step(plan, target_step_id)

        elif action.type == CorrectionType.ABORT:
            # Abort execution
            return self.abort(plan, action.message)

        # Unknown correction type, return as-is
        return plan

    async def retry_step(self, plan: Plan, step_index: int) -> Plan:
        """Retry a single step, without modifying Plan structure.

        Only resets the specified step's status to pending; the rest of the Plan remains unchanged.

        Args:
            plan: Current Plan
            step_index: Index of the step to retry

        Returns:
            Modified Plan
        """
        if 0 <= step_index < len(plan.choice.steps):
            plan.choice.steps[step_index].status = "pending"
        return plan

    async def retry_partial_flow(
        self, plan: Plan, from_step_index: int
    ) -> Plan:
        """Retry partial flow, resetting status from the specified step.

        Resets all steps from from_step_index onward to pending,
        and updates current_step_index.

        Args:
            plan: Current Plan
            from_step_index: Starting step index

        Returns:
            Modified Plan
        """
        steps = plan.choice.steps
        for i in range(from_step_index, len(steps)):
            steps[i].status = "pending"
        plan.current_step_index = from_step_index
        return plan

    async def rollback_to_step(self, plan: Plan, step_id: str) -> Plan:
        """Rollback to before the specified step.

        Resets all steps from target_step_id onward to pending,
        and removes their corresponding check results, supporting root cause investigation.

        Args:
            plan: Current Plan
            step_id: Rollback target step ID

        Returns:
            Modified Plan
        """
        steps = plan.choice.steps
        target_index = -1
        for i, step in enumerate(steps):
            if step.id == step_id:
                target_index = i
                break

        if target_index == -1:
            # Target step not found, return as-is
            return plan

        # Reset all steps from target_index onward
        for i in range(target_index, len(steps)):
            steps[i].status = "pending"

        # Remove check results of steps within the rollback range
        step_ids_to_rollback = {s.id for s in steps[target_index:]}
        plan.check_results = [
            r
            for r in plan.check_results
            if r.step_id not in step_ids_to_rollback
        ]

        plan.current_step_index = target_index
        return plan

    def abort(self, plan: Plan, reason: str) -> Plan:
        """Abort execution, mark plan.status = ABORTED.

        Args:
            plan: Current Plan
            reason: Abort reason

        Returns:
            Plan with status ABORTED
        """
        plan.status = PlanStatus.ABORTED
        return plan

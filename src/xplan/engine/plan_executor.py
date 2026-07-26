"""Plan executor - Execute Plan step by step and run checkpoints.

Execution flow:
1. Set Plan status to RUNNING
2. Execute step by step (execute_step)
3. Run checkpoint after each step (run_checkpoint)
4. Trigger correction when checkpoint fails (CorrectionHandler)
5. Constraints are dynamically injected during execution
6. Update plan.status and plan.current_step_index after execution
"""

import json
import re
from typing import Any

from xplan.engine.correction_handler import CorrectionHandler
from xplan.models import (
    CheckEvidence,
    CheckResult,
    Checkpoint,
    Correction,
    CorrectionType,
    Plan,
    Step,
)
from xplan.models.context import Constraints
from xplan.models.plan import PlanStatus


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response.

    Supports both markdown code block wrapped and bare JSON formats.
    """
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class PlanExecutor:
    """Plan executor.

    Executes Plan step by step, running checkpoint after each step.
    Triggers correction when checkpoint fails; constraints are dynamically injected during execution.
    """

    def __init__(self, llm_service: Any, constraint_manager: Any):
        """Initialize the Plan executor.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            constraint_manager: Constraint manager, must provide get_constraints() -> Constraints interface
        """
        self.llm_service = llm_service
        self.constraint_manager = constraint_manager
        # Internally create correction handler, reusing the same LLM service
        self.correction_handler = CorrectionHandler(llm_service)

    async def execute(self, plan: Plan) -> Plan:
        """Execute Plan step by step.

        Execution flow:
        1. Set Plan status to RUNNING
        2. Loop through and execute each step
        3. Run associated checkpoint after each step
        4. Trigger correction when checkpoint fails
        5. Decide whether to continue, retry, rollback, or abort based on correction result

        Args:
            plan: Plan to execute (status should be READY)

        Returns:
            Executed Plan with status COMPLETED / FAILED / ABORTED
        """
        plan.status = PlanStatus.RUNNING
        i = 0
        while i < len(plan.choice.steps):
            step = plan.choice.steps[i]
            plan.current_step_index = i
            step.status = "running"

            # Execute step
            output = await self.execute_step(step, plan)

            # Run checkpoint (if the step has an associated checkpoint)
            checkpoint = self._find_checkpoint(plan, step.id)
            if checkpoint:
                results = await self.run_checkpoint(
                    checkpoint, output, plan
                )
                plan.check_results.extend(results)

                # Trigger correction when checkpoint fails
                if not all(r.passed for r in results):
                    correction = await self._find_matching_correction(
                        plan, results
                    )
                    if correction:
                        plan = await self.correction_handler.handle(
                            correction, plan
                        )

                        # Stop execution on abort or failure
                        if plan.status in (
                            PlanStatus.ABORTED,
                            PlanStatus.FAILED,
                        ):
                            return plan

                        # After REPLAN, got a new Plan, restart from the beginning
                        if correction.action.type == CorrectionType.REPLAN:
                            plan.status = PlanStatus.RUNNING
                            i = 0
                            continue

                        # After RETRY / ROLLBACK, continue based on current_step_index
                        i = plan.current_step_index
                        continue

                    # No matching correction rule, mark as failed
                    step.status = "failed"
                    plan.status = PlanStatus.FAILED
                    return plan

            # Step completed
            step.status = "done"
            i += 1

        # All steps completed
        plan.status = PlanStatus.COMPLETED
        plan.current_step_index = len(plan.choice.steps) - 1
        return plan

    async def execute_step(self, step: Step, plan: Plan) -> str:
        """Execute a single step, return step output.

        Constraints are dynamically injected into the system prompt during execution.

        Args:
            step: Step to execute
            plan: Current Plan

        Returns:
            Step execution output (string)
        """
        system_prompt = (
            "You are the Plan executor, responsible for executing a single step and outputting the execution result.\n"
            "Please complete the task based on the step objective and Plan context, and output the execution result."
        )

        # Dynamically inject constraints
        constraints = self._get_constraints()
        if constraints.hard:
            system_prompt += "\n\nHard constraints (must not violate):\n" + "\n".join(
                f"- {c}" for c in constraints.hard
            )
        if constraints.soft:
            system_prompt += "\n\nSoft constraints (try to satisfy):\n" + "\n".join(
                f"- {c}" for c in constraints.soft
            )

        user_prompt = (
            f"Step ID: {step.id}\n"
            f"Step objective: {step.objective}\n"
            f"Step reason: {step.reason}\n\n"
            f"Plan context:\n{plan.model_dump_json(indent=2)}"
        )

        response = await self.llm_service.chat(system_prompt, user_prompt)
        return response

    async def run_checkpoint(
        self,
        checkpoint: Checkpoint,
        step_output: str,
        plan: Plan,
    ) -> list[CheckResult]:
        """Run checkpoint, output list of CheckResult.

        Evaluates whether step output satisfies check items, outputs check results containing
        passed, result, and evidences.

        Args:
            checkpoint: Checkpoint definition
            step_output: Step execution output
            plan: Current Plan

        Returns:
            List of CheckResult, one per check item
        """
        checks_str = "\n".join(
            f"- {c}" for c in checkpoint.checks
        )
        system_prompt = (
            "You are the checkpoint evaluator, responsible for verifying whether the step output satisfies the check items.\n\n"
            "For each check item, output an evaluation result containing:\n"
            "- check_point: The check item\n"
            "- passed: Whether it passed (true/false)\n"
            "- result: Check result description\n"
            "- evidences: List of evidences supporting the result\n\n"
            "Output in JSON format:\n"
            '{"results": [{"check_point": "...", "passed": true, '
            '"result": "...", "evidences": [{"description": "...", "source": "..."}]}]}'
        )
        user_prompt = (
            f"Step output:\n{step_output}\n\n"
            f"Check items:\n{checks_str}\n\n"
            f"Plan context:\n{plan.model_dump_json(indent=2)}"
        )

        response = await self.llm_service.chat(system_prompt, user_prompt)
        data = _extract_json(response)

        # Handle LLM returning bare list or wrapped in dict
        if isinstance(data, dict):
            data = data.get("results", [data])
        if not isinstance(data, list):
            data = [data]

        results: list[CheckResult] = []
        for item in data:
            evidences = [
                CheckEvidence.model_validate(ev)
                if isinstance(ev, dict)
                else ev
                for ev in item.get("evidences", [])
            ]
            results.append(
                CheckResult(
                    step_id=checkpoint.step_id,
                    check_point=item.get("check_point", ""),
                    passed=item.get("passed", False),
                    result=item.get("result", ""),
                    evidences=evidences,
                )
            )
        return results

    def _find_checkpoint(
        self, plan: Plan, step_id: str
    ) -> Checkpoint | None:
        """Find the checkpoint associated with a step.

        Args:
            plan: Current Plan
            step_id: Step ID

        Returns:
            Associated Checkpoint, or None if no association
        """
        for cp in plan.checkpoint:
            if cp.step_id == step_id:
                return cp
        return None

    async def _find_matching_correction(
        self, plan: Plan, results: list[CheckResult]
    ) -> Correction | None:
        """Find a matching correction rule based on checkpoint failure results.

        Uses LLM to select the best match from the correction rule list.
        Falls back to the first correction rule when LLM matching fails.

        Args:
            plan: Current Plan
            results: List of failed check results

        Returns:
            Matching Correction, or None if no correction rules
        """
        if not plan.correction:
            return None

        failed_checks = [
            {"check_point": r.check_point, "result": r.result}
            for r in results
            if not r.passed
        ]
        corrections_str = json.dumps(
            [
                {
                    "index": idx,
                    "condition": c.condition,
                    "action_type": c.action.type.value,
                    "message": c.action.message,
                }
                for idx, c in enumerate(plan.correction)
            ],
            ensure_ascii=False,
        )

        system_prompt = (
            "You are the correction rule matcher. Based on the checkpoint failure results, "
            "select the best matching rule from the correction rule list.\n\n"
            'Output JSON: {"index": 0} (return {"index": -1} when no match)'
        )
        user_prompt = (
            f"Failure results:\n{json.dumps(failed_checks, ensure_ascii=False)}\n\n"
            f"Correction rule list:\n{corrections_str}"
        )

        try:
            response = await self.llm_service.chat(
                system_prompt, user_prompt
            )
            data = _extract_json(response)
            index = data.get("index", -1)
            if 0 <= index < len(plan.correction):
                return plan.correction[index]
        except Exception:
            pass

        # Fall back to the first correction rule when LLM matching fails
        return plan.correction[0]

    def _get_constraints(self) -> Constraints:
        """Get current constraints from the constraint manager.

        Returns empty constraints when constraint_manager is unavailable.
        """
        if self.constraint_manager is None:
            return Constraints()
        try:
            return Constraints(
                hard=self.constraint_manager.get_hard_constraints(),
                soft=self.constraint_manager.get_soft_constraints(),
            )
        except Exception:
            return Constraints()

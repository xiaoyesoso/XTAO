"""Backtracking engine - Implements five backtracking levels and progressive expansion strategy.

Backtracking is a deepening implementation of Correction, divided into five levels by scope from small to large:
- ACTION: Action level (retry), no Plan modification, direct retry
- STEP: Step level (switch tool), switch to the next candidate path
- STAGE: Stage level (return to stage entry point), re-plan with Checkpoint as stage boundary
- GLOBAL: Global, discard all intermediate results, start from original state
- CROSS_TURN: Cross-turn, handle historical data contaminated by error facts

Progressive expansion strategy: ACTION -> STEP -> STAGE -> GLOBAL, judge feasibility via TCC before each expansion.
Jump backtracking: Directly locate backtracking position via predefined rules or vector retrieval,
skipping progressive expansion.
"""

import json
import logging
import re
from typing import Any

from xplan.models.backtracking import (
    BacktrackingLevel,
    BacktrackingResult,
    CrossTurnContamination,
    JumpRule,
)
from xplan.models.plan import Plan

logger = logging.getLogger(__name__)

# Transient error types (action-level retry is sufficient)
_TRANSIENT_ERROR_TYPES = {
    "TimeoutError",
    "TimeoutException",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "OSError",
    "NetworkError",
}


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


class BacktrackingEngine:
    """Backtracking engine, implements five backtracking levels and progressive expansion strategy.

    Attributes:
        llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
        tcc_replan: TCC Replan instance (optional, used to judge feasibility during progressive expansion)
        candidate_path_manager: Candidate path manager (optional)
    """

    def __init__(
        self,
        llm_service: Any,
        tcc_replan: Any = None,
        candidate_path_manager: Any = None,
    ) -> None:
        """Initialize the backtracking engine.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            tcc_replan: TCC Replan instance (optional, used to judge feasibility during progressive expansion)
            candidate_path_manager: Candidate path manager (optional)
        """
        self.llm_service = llm_service
        self.tcc_replan = tcc_replan
        self.candidate_path_manager = candidate_path_manager

    def determine_level(
        self,
        error: Exception | None,
        failure_tracing_result: Any | None,
        plan: Any,
    ) -> BacktrackingLevel:
        """Determine the backtracking level.

        Judgment rules (by priority):
        1. Cross-turn error facts -> CROSS_TURN
        2. Transient errors (timeout, network jitter) -> ACTION
        3. Tool failure but has candidate path -> STEP
        4. Stage intermediate result invalid -> STAGE
        5. Plan overall direction wrong -> GLOBAL

        Args:
            error: Exception during execution (can be None)
            failure_tracing_result: Failure tracing result (can be None)
            plan: Current Plan

        Returns:
            Suggested backtracking level
        """
        # 1. Cross-turn error facts: failure tracing result marks cross-turn contamination
        if failure_tracing_result is not None:
            if hasattr(failure_tracing_result, "is_cross_turn") and failure_tracing_result.is_cross_turn:
                return BacktrackingLevel.CROSS_TURN
            # Check whether there is a cross-turn contamination field
            if hasattr(failure_tracing_result, "contamination"):
                return BacktrackingLevel.CROSS_TURN

        # 2. Transient errors: timeout, network jitter, etc.
        if error is not None:
            error_type_name = type(error).__name__
            if error_type_name in _TRANSIENT_ERROR_TYPES:
                return BacktrackingLevel.ACTION

        # 3. Tool failure but has candidate path: check whether candidate path manager has available paths
        if error is not None and self.candidate_path_manager is not None:
            # Try to locate decision node via error info
            if hasattr(plan, "choice") and hasattr(plan.choice, "steps"):
                for step in plan.choice.steps:
                    if self.candidate_path_manager.get_decision(step.id):
                        next_path = self.candidate_path_manager.get_next_available(step.id)
                        if next_path is not None:
                            return BacktrackingLevel.STEP

        # 4. Stage intermediate result invalid: checkpoint not passed
        if hasattr(plan, "check_results") and plan.check_results:
            for result in plan.check_results:
                if not result.passed:
                    return BacktrackingLevel.STAGE

        # 5. Plan overall direction wrong: default global backtracking
        return BacktrackingLevel.GLOBAL

    async def action_level_retry(
        self, plan: Plan, step_id: str, error: Exception | None
    ) -> BacktrackingResult:
        """Action-level backtracking (retry).

        No Plan modification, directly retry the current step.

        Args:
            plan: Current Plan
            step_id: Failed step ID
            error: Failure exception

        Returns:
            Backtracking result
        """
        logger.info("Action-level backtracking (retry): step %s", step_id)
        return BacktrackingResult(
            level=BacktrackingLevel.ACTION,
            success=True,
            rollback_to=step_id,
            new_plan_steps=[],
            reused_results=[],
            expanded=False,
            next_level=None,
        )

    async def step_level_switch(
        self, plan: Plan, step_id: str, decision_id: str
    ) -> BacktrackingResult:
        """Step-level backtracking (switch tool).

        Switch to the next candidate path via candidate_path_manager.

        Args:
            plan: Current Plan
            step_id: Failed step ID
            decision_id: Decision node ID

        Returns:
            Backtracking result
        """
        logger.info("Step-level backtracking (switch tool): step %s, decision node %s", step_id, decision_id)

        if self.candidate_path_manager is None:
            logger.warning("Candidate path manager not initialized, step-level backtracking failed")
            return BacktrackingResult(
                level=BacktrackingLevel.STEP,
                success=False,
                rollback_to=step_id,
                expanded=True,
                next_level=BacktrackingLevel.STAGE,
            )

        next_path = self.candidate_path_manager.switch_path(decision_id)
        if next_path is None:
            logger.info("Decision node %s has no available candidate path, need to expand backtracking scope", decision_id)
            return BacktrackingResult(
                level=BacktrackingLevel.STEP,
                success=False,
                rollback_to=step_id,
                expanded=True,
                next_level=BacktrackingLevel.STAGE,
            )

        return BacktrackingResult(
            level=BacktrackingLevel.STEP,
            success=True,
            rollback_to=step_id,
            new_plan_steps=[{"step_id": step_id, "new_path": next_path.path}],
            reused_results=[],
            expanded=False,
            next_level=None,
        )

    async def stage_level_rollback(
        self, plan: Plan, stage_checkpoint_id: str
    ) -> BacktrackingResult:
        """Stage-level backtracking.

        Use Checkpoint as stage boundary, return to stage entry point to re-plan the entire stage.

        Args:
            plan: Current Plan
            stage_checkpoint_id: Stage boundary Checkpoint-associated step ID

        Returns:
            Backtracking result
        """
        logger.info("Stage-level backtracking: return to stage entry point %s", stage_checkpoint_id)

        system_prompt = (
            "You are a Plan backtracking expert. Based on the current Plan and the stage backtracking target, "
            "re-plan this stage and its subsequent steps.\n"
            "Requirements:\n"
            "1. Preserve completed steps before the stage entry point\n"
            "2. Re-plan the stage entry point and subsequent steps\n"
            "3. Reuse available intermediate results\n"
            "Output JSON format:\n"
            '{"new_plan_steps": [{"id": "", "objective": "", "reason": ""}], '
            '"reused_results": ["reusable intermediate results"]}'
        )

        user_prompt = (
            f"## Current Plan\n{plan.model_dump_json()}\n\n"
            f"## Stage backtracking target\nReturn to step {stage_checkpoint_id} and re-plan this stage.\n\n"
            f"Please output the re-planned step list."
        )

        # Call LLM and parse, retry on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(system_prompt, user_prompt)
                data = _extract_json(response)
                new_plan_steps = data.get("new_plan_steps", [])
                reused_results = data.get("reused_results", [])
                return BacktrackingResult(
                    level=BacktrackingLevel.STAGE,
                    success=True,
                    rollback_to=stage_checkpoint_id,
                    new_plan_steps=new_plan_steps,
                    reused_results=reused_results,
                    expanded=False,
                    next_level=None,
                )
            except Exception as e:
                last_error = e
                logger.warning("Stage-level backtracking LLM call or parse failed: %s", e)

        logger.error("Stage-level backtracking LLM parse failed, last error: %s", last_error)
        return BacktrackingResult(
            level=BacktrackingLevel.STAGE,
            success=False,
            rollback_to=stage_checkpoint_id,
            expanded=True,
            next_level=BacktrackingLevel.GLOBAL,
        )

    async def global_replan(self, plan: Plan) -> BacktrackingResult:
        """Global Replan.

        Discard all intermediate results, start from original state.

        Args:
            plan: Current Plan

        Returns:
            Backtracking result
        """
        logger.info("Global Replan: start from original state")

        system_prompt = (
            "You are a Plan backtracking expert. The current Plan has an overall direction error and needs to be re-planned from scratch.\n"
            "Requirements:\n"
            "1. Discard all intermediate results\n"
            "2. Re-plan from the original goal\n"
            "3. Do not reuse any intermediate results\n"
            "Output JSON format:\n"
            '{"new_plan_steps": [{"id": "", "objective": "", "reason": ""}]}'
        )

        user_prompt = (
            f"## Current Plan\n{plan.model_dump_json()}\n\n"
            f"## Backtracking target\nGlobal Replan, re-plan from the original state.\n\n"
            f"Please output a brand new step list."
        )

        # Call LLM and parse, retry on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(system_prompt, user_prompt)
                data = _extract_json(response)
                new_plan_steps = data.get("new_plan_steps", [])
                return BacktrackingResult(
                    level=BacktrackingLevel.GLOBAL,
                    success=True,
                    rollback_to="",
                    new_plan_steps=new_plan_steps,
                    reused_results=[],
                    expanded=False,
                    next_level=None,
                )
            except Exception as e:
                last_error = e
                logger.warning("Global Replan LLM call or parse failed: %s", e)

        logger.error("Global Replan LLM parse failed, last error: %s", last_error)
        return BacktrackingResult(
            level=BacktrackingLevel.GLOBAL,
            success=False,
            rollback_to="",
            expanded=False,
            next_level=None,
        )

    async def cross_turn_replan(
        self, plan: Plan, contamination: CrossTurnContamination
    ) -> BacktrackingResult:
        """Cross-turn Replan.

        Handle historical data contaminated by error facts:
        - Find the earliest location where error facts were written
        - Identify contaminated intermediate results, historical summaries, user profiles, key fact tables
        - Repair strategy: check all related data or clear context to restore to the error stage

        Args:
            plan: Current Plan
            contamination: Cross-turn contamination record

        Returns:
            Backtracking result
        """
        logger.info(
            "Cross-turn Replan: error fact %s written in turn %d",
            contamination.error_fact_key,
            contamination.introduced_turn,
        )

        system_prompt = (
            "You are a Plan backtracking expert. Cross-turn contamination detected, need to fix contaminated data and re-plan.\n"
            "Fix strategy:\n"
            "1. Check all affected intermediate results, historical summaries, user profiles, key fact tables\n"
            "2. Clear or correct contaminated data\n"
            "3. Re-plan from the turn where the error occurred\n"
            "Output JSON format:\n"
            '{"new_plan_steps": [{"id": "", "objective": "", "reason": ""}], '
            '"reused_results": ["reusable uncontaminated results"], '
            '"rollback_to": "rollback position"}'
        )

        contamination_json = contamination.model_dump_json()
        user_prompt = (
            f"## Current Plan\n{plan.model_dump_json()}\n\n"
            f"## Cross-turn contamination record\n{contamination_json}\n\n"
            f"Please output the fixed re-planning result based on the contamination record."
        )

        # Call LLM and parse, retry on parse failure
        last_error: Exception | None = None
        for _ in range(3):
            try:
                response = await self.llm_service.chat(system_prompt, user_prompt)
                data = _extract_json(response)
                new_plan_steps = data.get("new_plan_steps", [])
                reused_results = data.get("reused_results", [])
                rollback_to = data.get("rollback_to", "")
                return BacktrackingResult(
                    level=BacktrackingLevel.CROSS_TURN,
                    success=True,
                    rollback_to=rollback_to,
                    new_plan_steps=new_plan_steps,
                    reused_results=reused_results,
                    expanded=False,
                    next_level=None,
                )
            except Exception as e:
                last_error = e
                logger.warning("Cross-turn Replan LLM call or parse failed: %s", e)

        logger.error("Cross-turn Replan LLM parse failed, last error: %s", last_error)
        return BacktrackingResult(
            level=BacktrackingLevel.CROSS_TURN,
            success=False,
            rollback_to="",
            expanded=False,
            next_level=None,
        )

    async def progressive_expansion(
        self,
        plan: Plan,
        error: Exception | None,
        failure_tracing_result: Any | None,
    ) -> BacktrackingResult:
        """Progressively expand backtracking scope.

        Expand level by level: ACTION -> STEP -> STAGE -> GLOBAL.
        Before each expansion, if there is tcc_replan, judge new plan feasibility via TCC.

        Args:
            plan: Current Plan
            error: Failure exception
            failure_tracing_result: Failure tracing result

        Returns:
            Backtracking result (with expanded and next_level)
        """
        logger.info("Progressive expansion backtracking scope started")

        # Get failure step ID
        step_id = ""
        if hasattr(plan, "choice") and hasattr(plan.choice, "steps"):
            for step in plan.choice.steps:
                if step.status == "failed":
                    step_id = step.id
                    break
            if not step_id and plan.choice.steps:
                step_id = plan.choice.steps[plan.current_step_index].id

        # 1. First try ACTION level (retry)
        result = await self.action_level_retry(plan, step_id, error)
        if result.success:
            logger.info("ACTION level backtracking succeeded")
            return result

        # 2. If failed, expand to STEP level (switch tool)
        logger.info("ACTION level failed, expanding to STEP level")
        if self.candidate_path_manager is not None and step_id:
            result = await self.step_level_switch(plan, step_id, step_id)
        else:
            result = BacktrackingResult(
                level=BacktrackingLevel.STEP,
                success=False,
                rollback_to=step_id,
                expanded=True,
                next_level=BacktrackingLevel.STAGE,
            )

        if result.success:
            # Judge new plan feasibility via TCC
            if self.tcc_replan is not None and self.tcc_replan.enabled:
                feasible = await self._check_feasibility_via_tcc(plan)
                if not feasible:
                    logger.info("TCC determines new plan infeasible, continue expanding")
                    result = BacktrackingResult(
                        level=BacktrackingLevel.STEP,
                        success=False,
                        rollback_to=step_id,
                        expanded=True,
                        next_level=BacktrackingLevel.STAGE,
                    )
                else:
                    result.expanded = True
                    result.next_level = None
                    return result
            else:
                result.expanded = True
                return result

        # 3. If failed, expand to STAGE level (stage backtracking)
        logger.info("STEP level failed, expanding to STAGE level")
        stage_checkpoint_id = step_id
        if hasattr(plan, "checkpoint") and plan.checkpoint:
            stage_checkpoint_id = plan.checkpoint[-1].step_id

        result = await self.stage_level_rollback(plan, stage_checkpoint_id)
        if result.success:
            if self.tcc_replan is not None and self.tcc_replan.enabled:
                feasible = await self._check_feasibility_via_tcc(plan)
                if not feasible:
                    logger.info("TCC determines new plan infeasible, continue expanding")
                    result = BacktrackingResult(
                        level=BacktrackingLevel.STAGE,
                        success=False,
                        rollback_to=stage_checkpoint_id,
                        expanded=True,
                        next_level=BacktrackingLevel.GLOBAL,
                    )
                else:
                    result.expanded = True
                    return result
            else:
                result.expanded = True
                return result

        # 4. If failed, expand to GLOBAL level
        logger.info("STAGE level failed, expanding to GLOBAL level")
        result = await self.global_replan(plan)
        result.expanded = True
        return result

    async def _check_feasibility_via_tcc(self, plan: Plan) -> bool:
        """Judge new plan feasibility via TCC.

        Args:
            plan: Plan to validate

        Returns:
            Whether the new plan is feasible
        """
        try:
            tcc_result = await self.tcc_replan.run(plan)
            # All Try passes means feasible
            if tcc_result.try_result and tcc_result.try_result.all_passed:
                return True
            return False
        except Exception as e:
            logger.warning("TCC feasibility check failed: %s", e)
            return False

    async def jump_backtracking(
        self,
        error_pattern: str,
        jump_rules: list[JumpRule] | None = None,
    ) -> BacktrackingResult | None:
        """Jump backtracking.

        If there are jump_rules, match error_pattern to directly locate backtracking position,
        skipping the overhead of progressive expansion.

        Args:
            error_pattern: Error pattern description
            jump_rules: Jump backtracking rule list (optional)

        Returns:
            Backtracking result, or None if no matching rule
        """
        logger.info("Jump backtracking: error pattern %s", error_pattern)

        if not jump_rules:
            return None

        for rule in jump_rules:
            # Simple string containment match
            if rule.error_pattern in error_pattern or error_pattern in rule.error_pattern:
                logger.info(
                    "Matched jump rule: backtracking position %s", rule.rollback_position
                )
                return BacktrackingResult(
                    level=BacktrackingLevel.STAGE,
                    success=True,
                    rollback_to=rule.rollback_position,
                    new_plan_steps=[],
                    reused_results=[],
                    expanded=False,
                    next_level=None,
                )

        logger.info("No matching jump rule")
        return None

    async def vector_jump_backtracking(
        self,
        error_context: str,
        vector_db_client: Any = None,
    ) -> BacktrackingResult | None:
        """Vector database supported jump backtracking (optional).

        If there is vector_db_client, convert error_context to vector,
        retrieve the most similar known case, directly locate backtracking position.

        Args:
            error_context: Error context description
            vector_db_client: Vector database client (optional)

        Returns:
            Backtracking result, or None if no vector_db_client or no match
        """
        logger.info("Vector database jump backtracking: error context %s", error_context)

        if vector_db_client is None:
            return None

        try:
            # Convert error context to vector and retrieve most similar known case
            results = vector_db_client.search(error_context, top_k=1)
            if not results:
                logger.info("Vector retrieval no results")
                return None

            best_match = results[0]
            similarity = best_match.get("similarity", 0.0)
            rollback_position = best_match.get("rollback_position", "")

            # Don't adopt if similarity below threshold
            if similarity < 0.8 or not rollback_position:
                logger.info(
                    "Vector retrieval similarity %s below threshold or no backtracking position", similarity
                )
                return None

            logger.info(
                "Vector retrieval match: backtracking position %s, similarity %s",
                rollback_position,
                similarity,
            )
            return BacktrackingResult(
                level=BacktrackingLevel.STAGE,
                success=True,
                rollback_to=rollback_position,
                new_plan_steps=[],
                reused_results=[],
                expanded=False,
                next_level=None,
            )
        except Exception as e:
            logger.warning("Vector database jump backtracking failed: %s", e)
            return None

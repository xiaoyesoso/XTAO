"""Plan generator - Generate complete Plan based on the G4C methodology.

Generation flow:
1. Retrieve RAG standards
2. Generate Goal (goal and success criteria)
3. Generate Context (context and constraints)
4. Generate Choice (path decision and steps)
5. Generate Checkpoint (checkpoints)
6. Generate Correction (correction rules)
7. Assemble Plan

After LLM returns JSON, parse with Pydantic; retry on parse failure.
"""

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

from xplan.models import (
    Choice,
    Checkpoint,
    Context,
    Constraints,
    Correction,
    Goal,
    Plan,
    Step,
)
from xplan.models.plan import PlanStatus
from xplan.prompts import (
    build_checkpoint_system_prompt,
    build_checkpoint_user_prompt,
    build_choice_system_prompt,
    build_choice_user_prompt,
    build_context_system_prompt,
    build_context_user_prompt,
    build_correction_system_prompt,
    build_correction_user_prompt,
    build_goal_system_prompt,
    build_goal_user_prompt,
)

T = TypeVar("T", bound=BaseModel)


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response.

    Supports both markdown code block wrapped and bare JSON formats.
    """
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class PlanGenerator:
    """Plan generator.

    Generates a complete Plan object step by step based on the G4C methodology.
    Each step calls the LLM to obtain structured JSON, parsed into model objects with Pydantic.
    Retries automatically on parse failure, up to max_iterations times.
    """

    def __init__(
        self,
        llm_service: Any,
        rag_service: Any,
        max_iterations: int = 3,
    ):
        """Initialize the Plan generator.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
            rag_service: RAG retrieval service, must provide async search(query) -> str interface
            max_iterations: Maximum retry count when LLM call or parsing fails
        """
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.max_iterations = max_iterations

    async def _retrieve_rag_context(self, query: str) -> str:
        """Retrieve domain standards from RAG service.

        Returns an empty string when RAG service is unavailable or retrieval fails,
        without blocking the generation flow.
        """
        if self.rag_service is None:
            return ""
        try:
            return await self.rag_service.search(query)
        except Exception:
            return ""

    async def _call_and_parse(
        self,
        system_prompt: str,
        user_prompt: str,
        model_class: type[T],
    ) -> T:
        """Call LLM and parse into a single model object, retry on parse failure.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            model_class: Target Pydantic model class

        Returns:
            Parsed model object

        Raises:
            RuntimeError: Still failing after reaching maximum retry count
        """
        last_error: Exception | None = None
        for _ in range(self.max_iterations):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                return model_class.model_validate(data)
            except Exception as e:
                last_error = e
        raise RuntimeError(
            f"LLM call or parsing failed after {self.max_iterations} retries: {last_error}"
        ) from last_error

    async def _call_and_parse_list(
        self,
        system_prompt: str,
        user_prompt: str,
        item_class: type[T],
    ) -> list[T]:
        """Call LLM and parse into a list of model objects, retry on parse failure.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            item_class: Pydantic model class for list elements

        Returns:
            Parsed list of model objects

        Raises:
            RuntimeError: Still failing after reaching maximum retry count
        """
        last_error: Exception | None = None
        for _ in range(self.max_iterations):
            try:
                response = await self.llm_service.chat(
                    system_prompt, user_prompt
                )
                data = _extract_json(response)
                # Handle the case where LLM wraps the list in a dict
                if isinstance(data, dict):
                    for key in ("corrections", "checkpoints", "items", "data"):
                        if key in data and isinstance(data[key], list):
                            data = data[key]
                            break
                    else:
                        data = [data]
                return TypeAdapter(list[item_class]).validate_python(data)
            except Exception as e:
                last_error = e
        raise RuntimeError(
            f"LLM call or parsing failed after {self.max_iterations} retries: {last_error}"
        ) from last_error

    async def generate(
        self, user_input: str, conversation_history: str = ""
    ) -> Plan:
        """Generate a complete Plan.

        Generates in seven steps following the G4C methodology:
        1. Retrieve RAG standards
        2. Generate Goal
        3. Generate Context
        4. Generate Choice
        5. Generate Checkpoint
        6. Generate Correction
        7. Assemble Plan

        Args:
            user_input: User input
            conversation_history: Conversation history, used to extract context

        Returns:
            Complete Plan object with status READY
        """
        # 1. Retrieve RAG standards
        rag_context = await self._retrieve_rag_context(user_input)

        # 2. Generate Goal
        goal = await self.generate_goal(user_input, rag_context)

        # 3. Generate Context (no preset constraints during generation; LLM extracts from conversation history)
        context = await self.generate_context(
            conversation_history, Constraints()
        )

        # 4. Generate Choice
        choice = await self.generate_choice(goal, context)

        # 5. Generate Checkpoint
        checkpoints = await self.generate_checkpoints(choice.steps)

        # 6. Generate Correction
        plan_dict = {
            "goal": goal.model_dump(),
            "context": context.model_dump(),
            "choice": choice.model_dump(),
            "checkpoint": [cp.model_dump() for cp in checkpoints],
        }
        corrections = await self.generate_corrections(plan_dict, rag_context)

        # 7. Assemble Plan
        plan = Plan(
            goal=goal,
            context=context,
            choice=choice,
            checkpoint=checkpoints,
            correction=corrections,
            status=PlanStatus.READY,
        )
        return plan

    async def generate_goal(
        self, user_input: str, rag_context: str
    ) -> Goal:
        """Call LLM to generate the goal."""
        system_prompt = build_goal_system_prompt()
        user_prompt = build_goal_user_prompt(user_input, rag_context)
        return await self._call_and_parse(
            system_prompt, user_prompt, Goal
        )

    async def generate_context(
        self,
        conversation_history: str,
        constraints: Constraints,
    ) -> Context:
        """Call LLM to generate the context."""
        system_prompt = build_context_system_prompt(
            constraints.hard, constraints.soft
        )
        user_prompt = build_context_user_prompt(conversation_history)
        return await self._call_and_parse(
            system_prompt, user_prompt, Context
        )

    async def generate_choice(
        self, goal: Goal, context: Context
    ) -> Choice:
        """Call LLM to generate the path decision."""
        system_prompt = build_choice_system_prompt()
        user_prompt = build_choice_user_prompt(
            goal.model_dump_json(), context.model_dump_json()
        )
        return await self._call_and_parse(
            system_prompt, user_prompt, Choice
        )

    async def generate_checkpoints(
        self, steps: list[Step]
    ) -> list[Checkpoint]:
        """Call LLM to generate checkpoints.

        Checkpoint placement follows three rules: at milestones, at key intermediate outputs,
        and after error-prone steps.
        Reference standard: number of checkpoints is about 1/3 of the number of steps.
        """
        system_prompt = build_checkpoint_system_prompt()
        steps_json = json.dumps(
            [s.model_dump() for s in steps], ensure_ascii=False
        )
        user_prompt = build_checkpoint_user_prompt(steps_json)
        return await self._call_and_parse_list(
            system_prompt, user_prompt, Checkpoint
        )

    async def generate_corrections(
        self, plan_dict: dict, rag_context: str
    ) -> list[Correction]:
        """Call LLM to generate correction rules."""
        system_prompt = build_correction_system_prompt()
        plan_json = json.dumps(plan_dict, ensure_ascii=False)
        user_prompt = build_correction_user_prompt(plan_json, rag_context)
        return await self._call_and_parse_list(
            system_prompt, user_prompt, Correction
        )

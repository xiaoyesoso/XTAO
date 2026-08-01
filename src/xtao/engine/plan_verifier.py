"""Plan verifier - Evaluate Plan quality across G4C five dimensions.

Introduces a "generate-evaluate-correct" loop during iterative Plan generation.
Plan Verifier evaluates across G4C five dimensions and outputs score, issues, and suggestions.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from xtao.models import Plan


class PlanVerificationResult(BaseModel):
    """Plan verification result.

    Evaluated across G4C five dimensions, outputs score, per-dimension issues, and improvement suggestions.
    """

    score: float = Field(
        description="Overall score (0-1), 1 means perfect",
    )
    goal_issues: list[str] = Field(
        default_factory=list,
        description="Goal dimension issue list",
    )
    context_issues: list[str] = Field(
        default_factory=list,
        description="Context dimension issue list",
    )
    choice_issues: list[str] = Field(
        default_factory=list,
        description="Choice dimension issue list",
    )
    checkpoint_issues: list[str] = Field(
        default_factory=list,
        description="Checkpoint dimension issue list",
    )
    correction_issues: list[str] = Field(
        default_factory=list,
        description="Correction dimension issue list",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Improvement suggestion list",
    )


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM response.

    Supports both markdown code block wrapped and bare JSON formats.
    """
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class PlanVerifier:
    """Plan verifier.

    Evaluates Plan across G4C five dimensions:
    - Goal: Is the goal clear? Are success criteria verifiable?
    - Context: Is known/missing info structured? Are constraints complete?
    - Choice: Is path selection evidence-based? Are steps reasonable?
    - Checkpoint: Are checkpoints sufficient? (Reference standard: 1/3 of step count)
    - Correction: Do correction rules cover main failure scenarios?
    """

    def __init__(self, llm_service: Any):
        """Initialize the Plan verifier.

        Args:
            llm_service: LLM service, must provide async chat(system_prompt, user_prompt) -> str interface
        """
        self.llm_service = llm_service

    async def verify(self, plan: Plan) -> PlanVerificationResult:
        """Evaluate Plan across G4C five dimensions.

        Args:
            plan: Plan to evaluate

        Returns:
            PlanVerificationResult containing score, per-dimension issues, and suggestions
        """
        system_prompt = (
            "You are the Plan quality evaluator. Please evaluate the Plan quality across the G4C five dimensions.\n\n"
            "Evaluation dimensions:\n"
            "1. Goal: Is the goal clear? Are success criteria verifiable? Do adjectives have quantitative standards?\n"
            "2. Context: Is known/missing info structured? Are constraints complete? Are hard constraints explicit?\n"
            "3. Choice: Is path selection evidence-based? Are steps reasonable? Is there a risk of fabrication?\n"
            "4. Checkpoint: Are checkpoints sufficient? (Reference standard: checkpoint count about 1/3 of step count) "
            "Do they cover milestones, key outputs, and error-prone steps?\n"
            "5. Correction: Do correction rules cover main failure scenarios? Is there a rollback strategy?\n\n"
            "Output in JSON format:\n"
            "{\n"
            '  "score": 0.0-1.0,\n'
            '  "goal_issues": ["..."],\n'
            '  "context_issues": ["..."],\n'
            '  "choice_issues": ["..."],\n'
            '  "checkpoint_issues": ["..."],\n'
            '  "correction_issues": ["..."],\n'
            '  "suggestions": ["..."]\n'
            "}"
        )
        user_prompt = (
            f"Please evaluate the following Plan:\n\n{plan.model_dump_json(indent=2)}"
        )

        response = await self.llm_service.chat(system_prompt, user_prompt)
        data = _extract_json(response)
        return PlanVerificationResult.model_validate(data)

    def is_passing(
        self, result: PlanVerificationResult, threshold: float = 0.8
    ) -> bool:
        """Determine whether the verification result passes the threshold.

        Args:
            result: Verification result
            threshold: Pass threshold, default 0.8

        Returns:
            True when score >= threshold
        """
        return result.score >= threshold

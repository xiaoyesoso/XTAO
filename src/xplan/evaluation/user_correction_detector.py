"""User correction rate detection - Detects whether user input is corrective expression.

User correction rate is an important online metric for Plan quality: when users frequently
correct the Agent's understanding, it indicates that the Plan's Context or Goal has uncertainty.

Detection strategy:
1. Keyword matching: Fast detection of common corrective expressions (e.g., "not what I meant", "you misunderstood", etc.)
2. LLM-assisted judgment: When llm_service is available, performs more accurate judgment on inputs not matched by keywords
"""

from __future__ import annotations

from typing import Any

from xplan.models.plan import Plan


# Corrective keyword list - ordered by priority, longer words matched first
_CORRECTION_KEYWORDS: list[str] = [
    # Chinese - explicit correction
    "不是这个意思",
    "你理解错了",
    "理解错了",
    "搞错了",
    "说错了",
    "不是这样",
    "不要这样",
    "不对",
    "错了",
    "不行",
    # Chinese - request redo
    "重新来",
    "重新做",
    "重做",
    "重新",
    # Chinese - request modification
    "改一下",
    "改一改",
    "换个",
    "换一种",
    # Chinese - re-clarify intent
    "我的意思是",
    "我是说",
    "应该是",
    "其实",
    # English
    "not what i meant",
    "not what i mean",
    "you misunderstood",
    "misunderstand",
    "that's wrong",
    "thats wrong",
    "that's not right",
    "try again",
    "redo",
    "start over",
    "wrong",
    "no,",
    "actually",
    "i meant",
    "i mean",
]


class UserCorrectionDetector:
    """User correction detector.

    Detects whether user input is a correction to the Agent based on keyword matching or LLM judgment.

    Usage:
        detector = UserCorrectionDetector()
        is_correction = await detector.detect_correction(user_input, plan)

    Fast keyword detection:
        is_correction = detector.detect_correction_keywords(user_input)
    """

    def __init__(self, llm_service: Any = None):
        """Initialize user correction detector.

        Args:
            llm_service: Optional LLM service for more accurate correction judgment.
                         Type is Any, injected externally with concrete implementation.
                         Convention: async callable: ``await llm_service(prompt: str) -> str``
        """
        self.llm_service = llm_service

    async def detect_correction(self, user_input: str, plan: Plan) -> bool:
        """Detect whether user input is a correction.

        Prioritizes keyword matching for fast detection; if keywords don't match and
        llm_service is available, uses LLM for more accurate judgment.

        Args:
            user_input: User input text
            plan: Current Plan, provides context for LLM judgment

        Returns:
            Whether it is a corrective expression
        """
        # Step 1: Fast detection based on keywords
        if self.detect_correction_keywords(user_input):
            return True

        # Step 2: If LLM is available, use LLM for more accurate judgment
        if self.llm_service is not None:
            return await self._detect_with_llm(user_input, plan)

        return False

    def detect_correction_keywords(self, user_input: str) -> bool:
        """Fast detection based on keywords.

        Detects whether user input contains corrective keywords.
        Keywords cover: explicit correction, request redo, request modification, re-clarify intent, etc.

        Args:
            user_input: User input text

        Returns:
            Whether corrective keywords are present
        """
        if not user_input:
            return False
        input_lower = user_input.lower()
        for keyword in _CORRECTION_KEYWORDS:
            if keyword.lower() in input_lower:
                return True
        return False

    async def _detect_with_llm(self, user_input: str, plan: Plan) -> bool:
        """Use LLM for correction detection.

        Builds a Prompt to call LLM, judging whether user input is a corrective expression.
        Falls back to no correction (False) when LLM call fails, to avoid false positives.

        Args:
            user_input: User input text
            plan: Current Plan, provides context

        Returns:
            Whether LLM judges it as a correction
        """
        if self.llm_service is None:
            return False

        # Build LLM prompt, providing Plan context
        goal_desc = plan.goal.user_goal if plan.goal else ""
        prompt = (
            "Please determine whether the following user input is a corrective expression toward the Agent.\n"
            "A corrective expression means: the user thinks the Agent misunderstood, the direction is wrong, or modifications or redo are needed.\n\n"
            f"Current Plan goal: {goal_desc}\n"
            f"User input: {user_input}\n\n"
            "Please answer only 'true' or 'false'."
        )

        try:
            response = await self.llm_service(prompt)
            if isinstance(response, str):
                return response.strip().lower() == "true"
            return bool(response)
        except Exception:
            # Fall back to no correction when LLM call fails, to avoid false positives
            return False

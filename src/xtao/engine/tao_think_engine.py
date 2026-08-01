"""TAO Think engine - five structured judgments per loop round.

Each Think round produces a structured ThinkResult covering:
1. Goal judgment (final vs stage goal, success criteria)
2. State judgment (fact sufficiency, missing slots, assumptions, conflicts)
3. Path judgment (candidate action selection, evidence-based)
4. Stop judgment (should the loop stop and via which exit)
5. Risk judgment (hard constraint violation risk)

Invalid LLM outputs are retried with a stricter prompt (task 3.8).
"""

import json
import logging
import re
from typing import Any

from xtao.models.tao import RiskLevel, TAOExit, TAOState, ThinkResult
from xtao.prompts.tao_prompt import (
    build_tao_think_system_prompt,
    build_tao_think_user_prompt,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Extract JSON from an LLM response (markdown block or bare JSON)."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


def _evidence_fragments(texts) -> set[str]:
    """Split evidence texts into matchable fragments.

    Whole sentences rarely appear verbatim in a free-form reason, so we
    additionally index their word/phrase fragments (>= 4 chars). Action
    names and short tokens are kept as-is.
    """
    fragments: set[str] = set()
    for text in texts:
        if not text:
            continue
        fragments.add(text)
        for part in re.split(r"[^\w一-鿿]+", text):
            if len(part) >= 4:
                fragments.add(part)
    return fragments


class TAOThinkEngine:
    """Think decision engine for the TAO loop.

    Attributes:
        llm_service: LLM service with async chat(system_prompt, user_prompt) -> str
        constraint_manager: Optional constraint manager for hard/soft constraint injection
        max_output_retries: Max retries when the LLM returns invalid output
    """

    def __init__(
        self,
        llm_service: Any,
        constraint_manager: Any = None,
        max_output_retries: int = 2,
    ) -> None:
        """Initialize the Think engine.

        Args:
            llm_service: LLM service
            constraint_manager: Optional ConstraintManager for constraint injection
            max_output_retries: Max retries on invalid Think output
        """
        self.llm_service = llm_service
        self.constraint_manager = constraint_manager
        self.max_output_retries = max_output_retries
        self.few_shot_examples: dict[str, list[dict[str, Any]]] | None = None

    def set_few_shot_examples(
        self, examples: dict[str, list[dict[str, Any]]] | None
    ) -> None:
        """Set few-shot examples for candidate actions.

        Args:
            examples: Mapping from action name to a list of example dicts.
                Each example dict has keys: scenario, selected, reason.
        """
        self.few_shot_examples = examples

    async def think(self, state: TAOState) -> ThinkResult:
        """Run one Think round: five structured judgments.

        Args:
            state: Current TAO state

        Returns:
            Validated ThinkResult
        """
        hard, soft = self._get_constraints()
        system_prompt = build_tao_think_system_prompt(hard, soft)
        user_prompt = build_tao_think_user_prompt(
            state, few_shot_examples=getattr(self, "few_shot_examples", None)
        )

        last_error: Exception | None = None
        for attempt in range(self.max_output_retries + 1):
            try:
                raw = await self.llm_service.chat(
                    system_prompt, user_prompt, response_format={"type": "json_object"}
                )
                result = self._parse_result(raw)
                self._validate_result(result, state)
                return result
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                last_error = e
                logger.warning(
                    "Invalid Think output (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_output_retries + 1,
                    e,
                )
                # Append stricter instruction for the retry round
                user_prompt = (
                    user_prompt
                    + "\n\nYour previous output was invalid. Output ONLY the JSON object, "
                    "and selected_action MUST be one of the candidate actions."
                )

        # Fall back to a safe interrupt decision when all retries fail
        logger.error("Think output invalid after retries: %s", last_error)
        return ThinkResult(
            current_goal=state.goal_state.current_goal,
            should_stop=True,
            exit_decision=TAOExit.INTERRUPT,
            reason=f"Think output invalid after {self.max_output_retries + 1} attempts: {last_error}",
            risk_level=RiskLevel.HIGH,
            risk_reason="Think engine failed to produce valid structured output",
        )

    # ── Parsing & validation ──────────────────────────────────

    def _parse_result(self, raw: str) -> ThinkResult:
        """Parse the raw LLM response into a ThinkResult."""
        data = _extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("Think output must be a JSON object")

        exit_raw = str(data.get("exit_decision", "continue")).lower()
        try:
            exit_decision = TAOExit(exit_raw)
        except ValueError:
            raise ValueError(f"Invalid exit_decision: {exit_raw}")

        risk_raw = str(data.get("risk_level", "low")).lower()
        try:
            risk_level = RiskLevel(risk_raw)
        except ValueError:
            risk_level = RiskLevel.LOW

        return ThinkResult(
            current_goal=str(data.get("current_goal", "")),
            success_criteria_satisfied=bool(data.get("success_criteria_satisfied", False)),
            current_goal_completed=bool(data.get("current_goal_completed", False)),
            facts_sufficient=bool(data.get("facts_sufficient", False)),
            missing_slots=[str(s) for s in data.get("missing_slots", [])],
            unverified_assumptions=[str(s) for s in data.get("unverified_assumptions", [])],
            fact_conflicts=[str(s) for s in data.get("fact_conflicts", [])],
            selected_action=str(data.get("selected_action", "") or ""),
            action_params=data.get("action_params") or {},
            should_stop=bool(data.get("should_stop", False)),
            exit_decision=exit_decision,
            reason=str(data.get("reason", "")),
            risk_level=risk_level,
            risk_reason=str(data.get("risk_reason", "")),
            raw_response=raw,
        )

    def _validate_result(self, result: ThinkResult, state: TAOState) -> None:
        """Validate a ThinkResult against boundary rules (code-side checks).

        Checks:
        - selected_action must come from the candidate space when the exit
          decision requires an action (continue / retry)
        - reason must be non-empty and evidence-based (minimum length requirement)
        - reason must reference concrete facts, constraints, or criteria

        Raises:
            ValueError: When validation fails
        """
        reason = result.reason.strip()
        if not reason:
            raise ValueError("reason must be non-empty (evidence-based requirement)")
        if len(reason) < 10:
            raise ValueError("reason is too short; provide an evidence-based extaoation")

        if result.exit_decision in (TAOExit.CONTINUE, TAOExit.RETRY):
            candidate_names = {c.name for c in state.candidate_actions}
            # USER_INTERACTION candidates and aggregate actions are also in the space
            if result.selected_action not in candidate_names:
                raise ValueError(
                    f"selected_action '{result.selected_action}' is not in the candidate space "
                    f"{sorted(candidate_names)}"
                )
        else:
            # Evidence anchoring below only applies to action-selecting
            # decisions; finish/clarify/replan reasons describe outcomes.
            return

        # Soft evidence check: when concrete anchors exist, the reason should
        # reference at least one keyword from facts, constraints, success
        # criteria, or the selected/recent action names. This is logged as a
        # warning rather than enforced, because LLMs often paraphrase or mix
        # languages, which makes exact substring matching unreliable. The
        # evidence-based requirement remains a prompt-level boundary rule.
        evidence_keywords: set[str] = set()
        evidence_keywords.update(_evidence_fragments(state.facts.keys()))
        evidence_keywords.update(_evidence_fragments(state.goal_state.success_criteria))
        evidence_keywords.update(c.name for c in state.candidate_actions)
        last_action = state.last_action()
        if last_action is not None:
            evidence_keywords.add(last_action.name)
        if self.constraint_manager is not None:
            hard_constraints, soft_constraints = self._get_constraints()
            evidence_keywords.update(_evidence_fragments(hard_constraints))
            evidence_keywords.update(_evidence_fragments(soft_constraints))
        if evidence_keywords and not any(
            keyword.lower() in reason.lower() for keyword in evidence_keywords
        ):
            logger.warning(
                "Evidence check not satisfied. reason=%r; keywords sample=%s",
                reason[:200],
                sorted(evidence_keywords)[:20],
            )

    # ── Constraint helpers ────────────────────────────────────

    def _get_constraints(self) -> tuple[list[str], list[str]]:
        """Get hard/soft constraints from the constraint manager, if any."""
        if self.constraint_manager is None:
            return [], []
        try:
            hard = self.constraint_manager.get_hard_constraints()
            soft = self.constraint_manager.get_soft_constraints()
            return list(hard), list(soft)
        except AttributeError:
            return [], []

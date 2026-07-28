"""TAO Observation interpreter - converts raw action outputs into structured Observations.

Division of labor:
- Code: field completeness checks, format checks, anomaly format detection,
  special-case handling (HTTP 200 with empty data, permission errors, duplicates)
- LLM: semantic interpretation (fact extraction, evidence binding, state
  change summary, information gap identification)

Extracted facts are written into Fact State by the TAOStateManager.
"""

import json
import logging
import re
from typing import Any

from xplan.models.tao import (
    ActionRecord,
    ExecutionStatus,
    FactCategory,
    InformationGain,
    Observation,
    ObservationFact,
    TAOState,
)
from xplan.prompts.tao_prompt import (
    build_tao_observation_system_prompt,
    build_tao_observation_user_prompt,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Extract JSON from an LLM response (markdown block or bare JSON)."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class TAOObservationInterpreter:
    """Observation interpretation engine.

    Attributes:
        llm_service: LLM service with async chat(system_prompt, user_prompt) -> str
        simple_interpret_threshold: Raw output length below which code-only
            interpretation may suffice (avoid unnecessary LLM calls)
    """

    def __init__(self, llm_service: Any) -> None:
        """Initialize the Observation interpreter.

        Args:
            llm_service: LLM service
        """
        self.llm_service = llm_service

    async def interpret(
        self,
        state: TAOState,
        record: ActionRecord,
        expectation: str = "",
    ) -> Observation:
        """Interpret an executed action record into a structured Observation.

        Args:
            state: Current TAO state
            record: Executed action record with raw output
            expectation: Pre-execution expectation, if any

        Returns:
            Structured Observation
        """
        # Code layer: field checks and special-case detection (tasks 5.3, 5.7)
        code_hints = self._code_checks(record)

        # LLM layer: semantic interpretation (task 5.4)
        observation = await self._llm_interpret(state, record, expectation, code_hints)

        # Code-layer overrides take precedence over LLM misjudgment
        observation = self._apply_code_overrides(observation, code_hints, record)
        observation.action_id = record.action_id
        return observation

    # ── Code layer checks (tasks 5.3, 5.7) ────────────────────

    def _code_checks(self, record: ActionRecord) -> dict[str, Any]:
        """Run deterministic checks on the raw output.

        Detects:
        - Action execution failure (status failed / exception)
        - HTTP 200 but empty data (empty dict/list/string, null fields)
        - Permission-denied patterns in output
        - Error payload patterns in output

        Returns:
            Hint dict consumed by the LLM prompt and code overrides
        """
        hints: dict[str, Any] = {
            "action_failed": False,
            "empty_result": False,
            "permission_denied": False,
            "error_payload": False,
            "duplicate_output": False,
            "messages": [],
        }

        if record.status.value == "failed" or record.error:
            hints["action_failed"] = True
            hints["messages"].append(f"action execution failed: {record.error}")
            return hints

        output = record.output

        # Empty data detection
        if output is None or output == "" or output == {} or output == []:
            hints["empty_result"] = True
            hints["messages"].append("output is empty")
        elif isinstance(output, dict):
            data = output.get("data")
            if data is not None and (data == {} or data == [] or data == ""):
                hints["empty_result"] = True
                hints["messages"].append("output.data is empty")
            # Permission patterns
            text = json.dumps(output, ensure_ascii=False, default=str).lower()
            if any(p in text for p in ("permission denied", "forbidden", "unauthorized", "403", "401")):
                hints["permission_denied"] = True
                hints["messages"].append("permission-denied pattern detected in output")
            # Error payload patterns
            if output.get("error") or output.get("error_code") or output.get("errmsg"):
                hints["error_payload"] = True
                hints["messages"].append("error payload detected in output")

        return hints

    # ── LLM layer interpretation (task 5.4) ───────────────────

    async def _llm_interpret(
        self,
        state: TAOState,
        record: ActionRecord,
        expectation: str,
        code_hints: dict[str, Any],
    ) -> Observation:
        """Interpret the raw output with the LLM."""
        system_prompt = build_tao_observation_system_prompt()
        user_prompt = build_tao_observation_user_prompt(
            state, record.name, record.input, record.output, expectation
        )
        if code_hints["messages"]:
            user_prompt += (
                "\n\n## Code-layer detection hints (deterministic, take precedence)\n"
                + "\n".join(f"- {m}" for m in code_hints["messages"])
            )

        try:
            raw = await self.llm_service.chat(
                system_prompt, user_prompt, response_format={"type": "json_object"}
            )
            return self._parse_observation(raw)
        except Exception as e:
            logger.warning("Observation LLM interpretation failed: %s", e)
            # Deterministic fallback: build a minimal observation from code hints
            return Observation(
                execution_status=(
                    ExecutionStatus.FAILED
                    if code_hints["action_failed"] or code_hints["error_payload"]
                    else ExecutionStatus.PARTIAL_SUCCESS
                    if code_hints["empty_result"] or code_hints["permission_denied"]
                    else ExecutionStatus.SUCCESS
                ),
                anomalies=list(code_hints["messages"]),
                summary=f"LLM interpretation unavailable: {e}",
            )

    def _parse_observation(self, raw: str) -> Observation:
        """Parse an LLM response into an Observation."""
        data = _extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("Observation output must be a JSON object")

        status_raw = str(data.get("execution_status", "success")).lower()
        try:
            execution_status = ExecutionStatus(status_raw)
        except ValueError:
            execution_status = ExecutionStatus.PARTIAL_SUCCESS

        gain_raw = str(data.get("information_gain", "low")).lower()
        try:
            information_gain = InformationGain(gain_raw)
        except ValueError:
            information_gain = InformationGain.LOW

        facts: list[ObservationFact] = []
        for item in data.get("new_facts", []) or []:
            if not isinstance(item, dict) or "key" not in item:
                continue
            category_raw = str(item.get("category", "confirmed")).lower()
            try:
                category = FactCategory(category_raw)
            except ValueError:
                category = FactCategory.SPECULATIVE
            facts.append(
                ObservationFact(
                    key=str(item["key"]),
                    value=item.get("value"),
                    category=category,
                    evidence=str(item.get("evidence", "")),
                )
            )

        return Observation(
            execution_status=execution_status,
            new_facts=facts,
            missing_information=[str(s) for s in data.get("missing_information", []) or []],
            state_changes=[str(s) for s in data.get("state_changes", []) or []],
            anomalies=[str(s) for s in data.get("anomalies", []) or []],
            suggested_next_action=str(data.get("suggested_next_action", "") or ""),
            progress=bool(data.get("progress", False)),
            information_gain=information_gain,
            summary=str(data.get("summary", "")),
        )

    # ── Code overrides (tasks 5.3, 5.7) ───────────────────────

    def _apply_code_overrides(
        self,
        observation: Observation,
        code_hints: dict[str, Any],
        record: ActionRecord,
    ) -> Observation:
        """Apply deterministic code-layer overrides to the LLM observation.

        Rules:
        - Failed action => execution_status failed, progress false
        - Empty result => at most partial_success
        - Permission denied => at most partial_success, anomaly recorded
        """
        if code_hints["action_failed"]:
            observation.execution_status = ExecutionStatus.FAILED
            observation.progress = False
            observation.information_gain = InformationGain.LOW
        elif code_hints["empty_result"] and observation.execution_status == ExecutionStatus.SUCCESS:
            observation.execution_status = ExecutionStatus.PARTIAL_SUCCESS
            if "output is empty" not in observation.missing_information:
                observation.missing_information.append("output data is empty")
        elif code_hints["permission_denied"] and observation.execution_status == ExecutionStatus.SUCCESS:
            observation.execution_status = ExecutionStatus.PARTIAL_SUCCESS

        for msg in code_hints["messages"]:
            if msg not in observation.anomalies:
                observation.anomalies.append(msg)

        return observation

    # ── Progress evaluation (task 5.5) ────────────────────────

    def detect_stagnation(self, state: TAOState, window: int = 3) -> bool:
        """Detect repeated low-progress observations (stagnation signal).

        Args:
            state: Current TAO state
            window: Number of recent observations to inspect

        Returns:
            True when the last `window` observations all show no progress and
            low information gain
        """
        recent = state.observations[-window:]
        if len(recent) < window:
            return False
        return all(
            (not o.progress) and o.information_gain == InformationGain.LOW for o in recent
        )

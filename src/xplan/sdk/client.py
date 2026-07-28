"""XPlan SDK - Async client for the XPlan G4C Plan service.

The SDK wraps all REST endpoints exposed by the XPlan FastAPI server and
provides a Pythonic, type-safe interface. It reuses the Pydantic models from
``xplan.models`` so callers can pass model instances directly without dealing
with raw JSON.

Usage:
    import asyncio
    from xplan.sdk import XPlanClient

    async def main():
        client = XPlanClient(base_url="http://localhost:8000")
        result = await client.run_plan(user_input="Help me optimize my resume")
        print(result)

    asyncio.run(main())
"""

from __future__ import annotations

from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel

from xplan.sdk.exceptions import (
    APIError,
    ConnectionError,
    TimeoutError,
    ValidationError,
    XPlanError,
)

T = TypeVar("T", bound=BaseModel)

# Default request timeout in seconds.
DEFAULT_TIMEOUT = 120.0


def _to_payload(obj: Any) -> Any:
    """Convert a Pydantic model (or nested structure) into a JSON-safe payload.

    Accepts BaseModel instances, dicts, lists, and primitives. BaseModel
    instances are dumped using ``model_dump`` with ``mode="json"`` so enums
    and datetimes are serialized correctly.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _to_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_payload(item) for item in obj]
    return obj


class XPlanClient:
    """Async client for the XPlan service.

    The client is the single entry point for all XPlan operations. Each method
    maps 1:1 to a REST endpoint. The main orchestration entry point is
    :meth:`run_plan`, which internally drives the full G4C lifecycle
    (generate -> verify -> execute -> correct).

    Args:
        base_url: Base URL of the XPlan server, e.g. ``http://localhost:8000``.
        api_key: Optional API key (sent as ``Authorization: Bearer <key>``).
        timeout: Default request timeout in seconds.
        client: Optional pre-configformed ``httpx.AsyncClient``. If provided,
            the caller is responsible for closing it.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._external_client = client is not None
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    # ── Lifecycle ────────────────────────────────────────────

    async def __aenter__(self) -> "XPlanClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client (no-op when an external client was passed)."""
        if not self._external_client:
            await self._client.aclose()

    # ── Low-level request helper ─────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        response_model: Type[T] | None = None,
    ) -> Any:
        """Send an HTTP request and return the parsed JSON response.

        Args:
            method: HTTP method (GET/POST/...).
            path: Path under ``/api`` (e.g. ``"/plan/run"``).
            json: Optional request body. Pydantic models are auto-serialized.
            params: Optional query parameters.
            response_model: Optional Pydantic model to parse the response into.

        Raises:
            ConnectionError: Cannot reach the server.
            TimeoutError: Request timed out.
            APIError: Server returned a non-2xx status code.
            ValidationError: Response cannot be parsed into ``response_model``.
        """
        url = f"/api{path}" if not path.startswith("/api") else path
        body = _to_payload(json) if json is not None else None
        try:
            response = await self._client.request(method, url, json=body, params=params)
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Cannot connect to XPlan server: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Request timed out: {exc}") from exc

        if response.status_code >= 400:
            detail = self._extract_error_detail(response)
            raise APIError(response.status_code, detail)

        data = response.json() if response.content else None
        if response_model is not None and data is not None:
            try:
                return response_model.model_validate(data)
            except Exception as exc:
                raise ValidationError(
                    f"Failed to parse response into {response_model.__name__}: {exc}"
                ) from exc
        return data

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        """Best-effort extraction of an error message from a failed response."""
        try:
            data = response.json()
        except Exception:
            return response.text
        if isinstance(data, dict):
            for key in ("detail", "message", "error"):
                if key in data:
                    return str(data[key])
        return str(data)

    # ── Health ───────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """GET /api/health - Check server health."""
        return await self._request("GET", "/health")

    # ── Main orchestration ───────────────────────────────────

    async def run_plan(
        self,
        user_input: str,
        conversation_history: str = "",
        config: Any = None,
    ) -> dict[str, Any]:
        """POST /api/plan/run - Main orchestration entry point.

        Runs the full G4C lifecycle: generate -> verify -> execute -> correct.
        This is the primary interface; internally it orchestrates all other
        subsystems (failure tracing, trust state, backtracking, replan,
        evaluation) based on the provided configuration.

        Args:
            user_input: User's goal or request.
            conversation_history: Optional conversation history for context.
            config: Optional :class:`~xplan.models.OrchestratorConfig` (or dict)
                controlling which subsystems are enabled. Set ``use_tao=True``
                on the config to execute each plan step via the TAO
                (Think-Action-Observation) controlled state loop.

        Returns:
            :class:`~xplan.models.OrchestratorResult` as a dict.
        """
        payload = {
            "user_input": user_input,
            "conversation_history": conversation_history,
            "config": _to_payload(config) if config is not None else None,
        }
        return await self._request("POST", "/plan/run", json=payload)

    # ── TAO (Think-Action-Observation) loop ────────────────

    async def run_tao(
        self,
        user_input: str,
        plan: Any = None,
        candidate_actions: list[Any] | None = None,
        max_loops: int = 10,
        max_time: float = 300.0,
    ) -> dict[str, Any]:
        """POST /api/tao/run - Run the full TAO controlled state loop.

        The TAO loop drives step-level execution through five runtime states
        (Goal / Action / Observation / Fact / Control): Think produces five
        structured judgments, the selected action is executed, and the raw
        output is interpreted into an evidence-bound Observation. The loop
        exits via continue / finish / clarify / retry / replan / interrupt,
        and an optional outer supervisor loop checks goal drift, constraint
        violations and stagnation every N inner rounds.

        Args:
            user_input: User's goal or request.
            plan: Optional :class:`~xplan.models.Plan` for goal/context anchoring.
            candidate_actions: Full candidate action space (list of
                :class:`~xplan.models.ActionCandidate` or dicts); coarse-filtered
                inside the engine.
            max_loops: Maximum TAO inner loop rounds.
            max_time: Maximum execution time in seconds.

        Returns:
            :class:`~xplan.models.TAOResult` as a dict.
        """
        payload = {
            "user_input": user_input,
            "plan": _to_payload(plan) if plan is not None else None,
            "candidate_actions": _to_payload(candidate_actions or []),
            "max_loops": max_loops,
            "max_time": max_time,
        }
        return await self._request("POST", "/tao/run", json=payload)

    async def tao_think(self, state: Any) -> dict[str, Any]:
        """POST /api/tao/think - Atomic TAO Think round.

        Runs one Think round on the given state, producing a structured
        ThinkResult (five judgments: goal, state, path, stop, risk) plus the
        loop controller's exit decision. The caller carries the
        :class:`~xplan.models.TAOState` between calls.

        Args:
            state: Current :class:`~xplan.models.TAOState` (or dict).

        Returns:
            Dict with ``think`` (ThinkResult) and ``exit`` (TAOExitRecord).
        """
        return await self._request("POST", "/tao/think", json={"state": _to_payload(state)})

    async def tao_act(
        self,
        state: Any,
        action_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/tao/act - Atomic TAO Action execution.

        Executes the named action from the candidate space carried in the
        state. Illegal actions (outside the candidate space) and unsatisfied
        hard preconditions are rejected with a 400 error.

        Args:
            state: Current :class:`~xplan.models.TAOState` (or dict) carrying
                the candidate action space.
            action_name: Selected action name (must be in the candidate space).
            params: Optional action parameters.

        Returns:
            Dict with ``record`` (:class:`~xplan.models.ActionRecord`).
        """
        payload = {
            "state": _to_payload(state),
            "action_name": action_name,
            "params": params or {},
        }
        return await self._request("POST", "/tao/act", json=payload)

    async def tao_observe(
        self,
        state: Any,
        record: Any,
        expectation: str = "",
    ) -> dict[str, Any]:
        """POST /api/tao/observe - Atomic TAO Observation interpretation.

        Interprets an action's raw output into a structured Observation:
        code performs field/format checks, the LLM performs semantic
        interpretation (fact extraction, evidence binding, gap
        identification). Note: HTTP 200 != real success; empty data and
        anomalies are detected.

        Args:
            state: Current :class:`~xplan.models.TAOState` (or dict).
            record: :class:`~xplan.models.ActionRecord` (or dict) to interpret.
            expectation: Optional expectation for the output.

        Returns:
            Dict with ``observation`` (:class:`~xplan.models.Observation`).
        """
        payload = {
            "state": _to_payload(state),
            "record": _to_payload(record),
            "expectation": expectation,
        }
        return await self._request("POST", "/tao/observe", json=payload)

    # ── Plan operations ──────────────────────────────────────

    async def generate_plan(
        self,
        user_input: str,
        conversation_history: str = "",
        use_iteration: bool = False,
    ) -> dict[str, Any]:
        """POST /api/plan/generate - Generate a G4C Plan.

        Args:
            user_input: User input describing the goal.
            conversation_history: Optional conversation history.
            use_iteration: If True, use the generate-evaluate-correct loop.

        Returns:
            Dict with ``plan`` (and ``verification_results``/``iterations``
            when iteration is enabled).
        """
        payload = {
            "user_input": user_input,
            "conversation_history": conversation_history,
            "use_iteration": use_iteration,
        }
        return await self._request("POST", "/plan/generate", json=payload)

    async def verify_plan(self, plan: Any) -> dict[str, Any]:
        """POST /api/plan/verify - Evaluate a Plan across G4C five dimensions.

        Args:
            plan: A :class:`~xplan.models.Plan` instance (or dict).

        Returns:
            Dict with ``verification`` result.
        """
        return await self._request("POST", "/plan/verify", json={"plan": _to_payload(plan)})

    async def execute_plan(self, plan: Any) -> dict[str, Any]:
        """POST /api/plan/execute - Execute a Plan step by step with checkpoints.

        Args:
            plan: A :class:`~xplan.models.Plan` instance (or dict).

        Returns:
            Dict with the executed ``plan`` (status updated).
        """
        return await self._request("POST", "/plan/execute", json={"plan": _to_payload(plan)})

    async def iterate_plan(
        self,
        user_input: str,
        conversation_history: str = "",
    ) -> dict[str, Any]:
        """POST /api/plan/iterate - Iterative Plan generation (generate-evaluate-correct loop).

        Returns:
            Dict with ``plan``, ``verification_results`` and ``iterations``.
        """
        payload = {
            "user_input": user_input,
            "conversation_history": conversation_history,
        }
        return await self._request("POST", "/plan/iterate", json=payload)

    async def trace_failure(
        self,
        plan: Any,
        failure_step_id: str,
        failure_info: str = "",
        step_records: list[Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/plan/trace - Trigger failure tracing and root cause location.

        Core concept: failure point != root cause point. The tracer builds a
        reverse tracing chain from the failure point to locate the true root
        cause, then suggests rollback and Replan start points.

        Args:
            plan: Current Plan.
            failure_step_id: ID of the failed step.
            failure_info: Optional failure description.
            step_records: Optional list of :class:`~xplan.models.StepRecord`.

        Returns:
            Dict with ``result`` (a FailureTracingResult).
        """
        payload = {
            "plan": _to_payload(plan),
            "failure_step_id": failure_step_id,
            "failure_info": failure_info,
            "step_records": _to_payload(step_records or []),
        }
        return await self._request("POST", "/plan/trace", json=payload)

    async def replan(
        self,
        plan: Any,
        error_info: str = "",
        user_input: str = "",
        conversation_history: str = "",
    ) -> dict[str, Any]:
        """POST /api/plan/replan - Trigger Replan (controlled correction).

        Flow: detect_trigger -> code_judge -> llm_judge -> execute_replan.

        Returns:
            Dict with the new ``plan`` and optional ``replan_result``.
        """
        payload = {
            "plan": _to_payload(plan),
            "error_info": error_info,
            "user_input": user_input,
            "conversation_history": conversation_history,
        }
        return await self._request("POST", "/plan/replan", json=payload)

    async def tcc_replan(
        self,
        plan: Any,
        conversation_history: str = "",
    ) -> dict[str, Any]:
        """POST /api/plan/tcc-replan - Execute TCC Replan (Try/Confirm/Cancel).

        Only applicable to high-failure-cost, high-external-dependency,
        high-side-effect-risk scenarios.

        Returns:
            Dict with ``result`` (a TCCResult).
        """
        payload = {
            "plan": _to_payload(plan),
            "conversation_history": conversation_history,
        }
        return await self._request("POST", "/plan/tcc-replan", json=payload)

    # ── Constraints ──────────────────────────────────────────

    async def add_hard_constraint(
        self,
        constraint: str,
        user_input: str,
    ) -> dict[str, Any]:
        """POST /api/constraints/hard - Add a hard constraint.

        Constraint modification requires user input as evidence; the Agent
        cannot modify constraints autonomously.
        """
        payload = {"constraint": constraint, "user_input": user_input}
        return await self._request("POST", "/constraints/hard", json=payload)

    async def add_soft_constraint(
        self,
        constraint: str,
        user_input: str,
    ) -> dict[str, Any]:
        """POST /api/constraints/soft - Add a soft constraint."""
        payload = {"constraint": constraint, "user_input": user_input}
        return await self._request("POST", "/constraints/soft", json=payload)

    async def get_constraints(self) -> dict[str, Any]:
        """GET /api/constraints - Get all constraints (hard and soft)."""
        return await self._request("GET", "/constraints")

    # ── Evaluation ───────────────────────────────────────────

    async def offline_analysis(self, plan: Any) -> dict[str, Any]:
        """POST /api/evaluation/offline - Offline analysis of Plan quality (G4C five dimensions)."""
        return await self._request(
            "POST", "/evaluation/offline", json={"plan": _to_payload(plan)}
        )

    async def record_replan_event(self, event: Any) -> dict[str, Any]:
        """POST /api/evaluation/replan/event - Record a Replan event for evaluation."""
        return await self._request(
            "POST", "/evaluation/replan/event", json={"event": _to_payload(event)}
        )

    async def get_replan_metrics(self) -> dict[str, Any]:
        """GET /api/evaluation/replan/metrics - Get Replan five metrics.

        Returns root cause accuracy, Replan start accuracy, result reuse rate,
        Replan recovery success rate, Replan oscillation rate and basic stats.
        """
        return await self._request("GET", "/evaluation/replan/metrics")

    async def get_replan_report(self) -> dict[str, Any]:
        """GET /api/evaluation/replan/report - Get Replan evaluation report (text)."""
        return await self._request("GET", "/evaluation/replan/report")

    async def annotate_replan(self, annotations: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /api/evaluation/replan/annotate - Import manual annotations.

        Each item must contain ``event_id`` and annotation fields
        (``root_cause_correct``, ``replan_start_correct``, etc.).
        """
        return await self._request(
            "POST", "/evaluation/replan/annotate", json={"annotations": annotations}
        )

    async def export_replan_test_set(self) -> dict[str, Any]:
        """GET /api/evaluation/replan/test-set - Export Replan evaluation test set."""
        return await self._request("GET", "/evaluation/replan/test-set")

    async def record_tao_evaluation_event(self, event: Any) -> dict[str, Any]:
        """POST /api/evaluation/tao/event - Record a TAO evaluation event."""
        return await self._request(
            "POST", "/evaluation/tao/event", json={"event": _to_payload(event)}
        )

    async def get_tao_metrics(self) -> dict[str, Any]:
        """GET /api/evaluation/tao/metrics - Get TAO evaluation metrics."""
        return await self._request("GET", "/evaluation/tao/metrics")

    async def get_tao_report(self) -> dict[str, Any]:
        """GET /api/evaluation/tao/report - Get TAO evaluation report."""
        return await self._request("GET", "/evaluation/tao/report")

    async def annotate_tao(self, annotations: list[Any]) -> dict[str, Any]:
        """POST /api/evaluation/tao/annotate - Import TAO golden answers."""
        return await self._request(
            "POST", "/evaluation/tao/annotate", json={"annotations": _to_payload(annotations)}
        )

    async def export_tao_test_set(self) -> dict[str, Any]:
        """GET /api/evaluation/tao/test-set - Export TAO evaluation test set."""
        return await self._request("GET", "/evaluation/tao/test-set")

    async def tao_llm_judge(self, request: Any) -> dict[str, Any]:
        """POST /api/evaluation/tao/judge - Run LLM-as-judge on a TAO round."""
        return await self._request(
            "POST", "/evaluation/tao/judge", json={"request": _to_payload(request)}
        )

    # ── Metrics ──────────────────────────────────────────────

    async def get_metrics(self) -> dict[str, Any]:
        """GET /api/metrics - Get online monitoring metrics."""
        return await self._request("GET", "/metrics")

    # ── DAG ──────────────────────────────────────────────────

    async def validate_dag(self, dag: Any) -> dict[str, Any]:
        """POST /api/dag/validate - Validate DAG structure (cycle detection + topological sort).

        Returns:
            Dict with ``valid``, ``errors``, ``cycles``, ``topological_order``.
        """
        return await self._request("POST", "/dag/validate", json={"dag": _to_payload(dag)})

    # ── Trust state ──────────────────────────────────────────

    async def add_fact(
        self,
        key: str,
        value: Any,
        evidence: str = "",
        source_step_id: str = "",
        depends_on: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/trust-state/facts - Add a fact entry (default state AVAILABLE)."""
        payload = {
            "key": key,
            "value": value,
            "evidence": evidence,
            "source_step_id": source_step_id,
            "depends_on": depends_on or [],
        }
        return await self._request("POST", "/trust-state/facts", json=payload)

    async def get_facts(self) -> dict[str, Any]:
        """GET /api/trust-state/facts - Get all fact entries."""
        return await self._request("GET", "/trust-state/facts")

    async def update_trust_state(
        self,
        key: str,
        new_state: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """POST /api/trust-state/update - Update the trust state of a fact.

        If the new state is ``invalid``, cascade marking is triggered: all
        facts depending on this fact are marked ``dirty`` (BFS traversal).
        Returns all change records.
        """
        payload = {"key": key, "new_state": new_state, "reason": reason}
        return await self._request("POST", "/trust-state/update", json=payload)

    async def get_trust_state_report(self) -> dict[str, Any]:
        """GET /api/trust-state/report - Get trust state report (counts per state)."""
        return await self._request("GET", "/trust-state/report")

    async def get_suspicious_and_dirty(self) -> dict[str, Any]:
        """GET /api/trust-state/suspicious - Get Suspicious and Dirty facts to prioritize."""
        return await self._request("GET", "/trust-state/suspicious")

    # ── Backtracking ─────────────────────────────────────────

    async def execute_backtracking(
        self,
        plan: Any,
        error_info: str = "",
        level: str | None = None,
        failure_tracing_result: dict[str, Any] | None = None,
        step_id: str = "",
        decision_id: str = "",
        stage_checkpoint_id: str = "",
        contamination: Any = None,
    ) -> dict[str, Any]:
        """POST /api/backtracking/execute - Execute backtracking at a given level.

        Supports five levels: ``action`` / ``step`` / ``stage`` / ``global`` /
        ``cross_turn``. When ``level`` is None the server auto-determines it.
        """
        payload = {
            "plan": _to_payload(plan),
            "error_info": error_info,
            "level": level,
            "failure_tracing_result": failure_tracing_result,
            "step_id": step_id,
            "decision_id": decision_id,
            "stage_checkpoint_id": stage_checkpoint_id,
            "contamination": _to_payload(contamination) if contamination is not None else None,
        }
        return await self._request("POST", "/backtracking/execute", json=payload)

    async def progressive_backtracking(
        self,
        plan: Any,
        error_info: str = "",
        failure_tracing_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/backtracking/progressive - Progressive expansion backtracking.

        Progressively expands scope: action -> step -> stage -> global. Each
        expansion validates the new plan via TCC before proceeding.
        """
        payload = {
            "plan": _to_payload(plan),
            "error_info": error_info,
            "failure_tracing_result": failure_tracing_result,
        }
        return await self._request("POST", "/backtracking/progressive", json=payload)

    async def jump_backtracking(
        self,
        error_pattern: str,
        jump_rules: list[Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/backtracking/jump - Jump backtracking via pattern rules.

        Skips progressive expansion by directly locating the backtracking
        position based on predefined jump rules.
        """
        payload = {
            "error_pattern": error_pattern,
            "jump_rules": _to_payload(jump_rules) if jump_rules is not None else None,
        }
        return await self._request("POST", "/backtracking/jump", json=payload)

    # ── Candidate paths ──────────────────────────────────────

    async def register_decision(
        self,
        decision_id: str,
        selected: str,
        candidates: list[Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/candidate-paths/register - Register a decision node with candidates."""
        payload = {
            "decision_id": decision_id,
            "selected": selected,
            "candidates": _to_payload(candidates or []),
        }
        return await self._request("POST", "/candidate-paths/register", json=payload)

    async def switch_candidate_path(self, decision_id: str) -> dict[str, Any]:
        """POST /api/candidate-paths/switch/{decision_id} - Switch to the next candidate path."""
        return await self._request("POST", f"/candidate-paths/switch/{decision_id}")

    async def get_failed_paths(self) -> dict[str, Any]:
        """GET /api/candidate-paths/failed - Get failed path records."""
        return await self._request("GET", "/candidate-paths/failed")


__all__ = [
    "XPlanClient",
    "XPlanError",
    "APIError",
    "ConnectionError",
    "TimeoutError",
    "ValidationError",
]

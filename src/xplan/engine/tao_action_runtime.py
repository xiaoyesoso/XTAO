"""TAO Action runtime - action abstraction, candidate filtering and execution.

An Action is a goal-oriented wrapper, not a raw tool. Four action types are
supported: tool_call, internal_api, user_interaction and aggregate.

Selection pipeline:
1. Coarse filter: code-side filtering by Plan node, intent, preconditions and
   business spec metadata.
2. Fine filter: performed by the Think engine (multi-dimensional scoring).
3. Execution: the selected action runs through a registered executor and is
   recorded as an ActionRecord.
"""

import inspect
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from xplan.models.plan import Plan
from xplan.models.tao import (
    ActionCandidate,
    ActionRecord,
    ActionStatus,
    ActionType,
    TAOState,
)

logger = logging.getLogger(__name__)

# Executor signature: async (params: dict) -> Any
ActionExecutor = Callable[[dict[str, Any]], Awaitable[Any]]
# User interaction handler: async (question: str) -> str
UserInteractionHandler = Callable[[str], Awaitable[str]]


class ActionExecutionError(Exception):
    """Raised when an action fails during execution."""


class IllegalActionError(Exception):
    """Raised when an action outside the candidate space is requested."""


class PreconditionError(Exception):
    """Raised when a hard precondition of an action is not satisfied."""


class TAOActionRuntime:
    """Action execution runtime for the TAO loop.

    Attributes:
        max_retries: Default max retries per action
    """

    def __init__(self, max_retries: int = 2) -> None:
        """Initialize the Action runtime.

        Args:
            max_retries: Default max retries per action
        """
        self.max_retries = max_retries
        self._executors: dict[str, ActionExecutor] = {}
        self._user_handler: UserInteractionHandler | None = None

    # ── Registration ──────────────────────────────────────────

    def register_executor(self, action_name: str, executor: ActionExecutor) -> None:
        """Register an executor for a tool_call / internal_api / aggregate action.

        Args:
            action_name: Action name matching the candidate name
            executor: Async callable taking params dict and returning raw output
        """
        self._executors[action_name] = executor

    def register_user_interaction_handler(self, handler: UserInteractionHandler) -> None:
        """Register the handler used for user_interaction actions.

        Args:
            handler: Async callable taking a question string and returning the
                user's reply
        """
        self._user_handler = handler

    # ── Candidate space: coarse filter (task 4.2) ─────────────

    def coarse_filter(
        self,
        candidates: list[ActionCandidate],
        plan: Plan | None = None,
        intent: str = "",
        state: TAOState | None = None,
    ) -> list[ActionCandidate]:
        """Coarse-filter the candidate action space.

        Filtering rules (code-side, deterministic):
        - Exclude actions whose metadata `plan_nodes` whitelist exists and does
          not contain the current Plan step id.
        - Exclude actions whose metadata `intents` whitelist exists and does
          not contain the given intent.
        - Exclude actions with hard preconditions that are unsatisfied
          (precondition keys must exist as confirmed/user_approved facts).

        Args:
            candidates: Full candidate list
            plan: Current Plan, if any
            intent: Current intent tag, if any
            state: Current TAO state for precondition checks

        Returns:
            Filtered candidate list for the Think fine-selection stage
        """
        current_step_id = ""
        if plan is not None and plan.choice is not None and plan.choice.steps:
            idx = min(plan.current_step_index, len(plan.choice.steps) - 1)
            current_step_id = plan.choice.steps[idx].id

        available_facts: set[str] = set()
        if state is not None:
            available_facts = {
                f.key
                for f in state.facts.values()
                if f.category.value in ("confirmed", "user_approved")
            }

        filtered: list[ActionCandidate] = []
        for candidate in candidates:
            node_whitelist = candidate.metadata.get("plan_nodes")
            if node_whitelist and current_step_id and current_step_id not in node_whitelist:
                continue
            intent_whitelist = candidate.metadata.get("intents")
            if intent_whitelist and intent and intent not in intent_whitelist:
                continue
            if state is not None and candidate.preconditions:
                if not all(pre in available_facts for pre in candidate.preconditions):
                    continue
            filtered.append(candidate)

        logger.info(
            "Coarse filter: %d -> %d candidates (step=%s, intent=%s)",
            len(candidates),
            len(filtered),
            current_step_id,
            intent,
        )
        return filtered

    # ── Execution (tasks 4.4-4.7) ─────────────────────────────

    async def execute(
        self,
        candidate: ActionCandidate,
        params: dict[str, Any],
        state: TAOState,
        retry_of: ActionRecord | None = None,
    ) -> ActionRecord:
        """Execute a candidate action and record an ActionRecord.

        Args:
            candidate: The selected action candidate
            params: Action parameters from ThinkResult
            state: Current TAO state (used for precondition re-check)
            retry_of: Previous failed record when this is a retry

        Returns:
            Completed ActionRecord (status done or failed)

        Raises:
            IllegalActionError: When the candidate is not in the state's space
            PreconditionError: When a hard precondition is unsatisfied
        """
        # Task 4.8: illegal action check
        legal_names = {c.name for c in state.candidate_actions}
        if candidate.name not in legal_names:
            raise IllegalActionError(
                f"Action '{candidate.name}' is not in the candidate space {sorted(legal_names)}"
            )

        # Precondition re-check at execution time (never skip hard preconditions)
        if candidate.preconditions:
            available = {
                f.key
                for f in state.facts.values()
                if f.category.value in ("confirmed", "user_approved")
            }
            missing = [p for p in candidate.preconditions if p not in available]
            if missing:
                raise PreconditionError(
                    f"Action '{candidate.name}' has unsatisfied preconditions: {missing}"
                )

        record = ActionRecord(
            name=candidate.name,
            type=candidate.type,
            tool_name=candidate.metadata.get("tool_name", candidate.name),
            input=dict(params),
            status=ActionStatus.RUNNING,
            rollbackable=candidate.rollbackable,
        )
        if retry_of is not None:
            record.retry_count = retry_of.retry_count + 1

        try:
            output = await self._dispatch(candidate, params)
            record.output = output
            record.status = ActionStatus.DONE
        except Exception as e:
            record.error = str(e)
            record.status = ActionStatus.FAILED
            logger.warning("Action %s failed: %s", candidate.name, e)
        finally:
            record.end_time = datetime.utcnow()

        return record

    async def _dispatch(self, candidate: ActionCandidate, params: dict[str, Any]) -> Any:
        """Dispatch execution by action type."""
        if candidate.type == ActionType.USER_INTERACTION:
            return await self._execute_user_interaction(params)

        if candidate.type == ActionType.AGGREGATE:
            return await self._execute_aggregate(candidate, params)

        executor = self._executors.get(candidate.name)
        if executor is None:
            raise ActionExecutionError(
                f"No executor registered for action '{candidate.name}'"
            )
        result = executor(params)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _execute_user_interaction(self, params: dict[str, Any]) -> Any:
        """Execute a user_interaction action: ask the user and record the reply."""
        if self._user_handler is None:
            raise ActionExecutionError("No user interaction handler registered")
        question = str(params.get("question", ""))
        if not question:
            raise ActionExecutionError("user_interaction action requires a 'question' param")
        reply = self._user_handler(question)
        if inspect.isawaitable(reply):
            reply = await reply
        return {"question": question, "reply": reply}

    async def _execute_aggregate(
        self, candidate: ActionCandidate, params: dict[str, Any]
    ) -> Any:
        """Execute an aggregate action: run sub-actions in order and collect outputs.

        Sub-actions are listed in candidate.metadata["sub_actions"] as names of
        registered executors.
        """
        sub_actions: list[str] = candidate.metadata.get("sub_actions", [])
        if not sub_actions:
            raise ActionExecutionError(
                f"Aggregate action '{candidate.name}' has no sub_actions metadata"
            )
        results: dict[str, Any] = {}
        for name in sub_actions:
            executor = self._executors.get(name)
            if executor is None:
                raise ActionExecutionError(
                    f"Aggregate action references unregistered sub-action '{name}'"
                )
            sub_params = params.get(name, params)
            result = executor(sub_params)
            if inspect.isawaitable(result):
                result = await result
            results[name] = result
        return results

    # ── Retry support (task 4.7) ──────────────────────────────

    def can_retry(self, record: ActionRecord, max_retries: int | None = None) -> bool:
        """Whether a failed action record can be retried.

        Args:
            record: Failed action record
            max_retries: Threshold override; defaults to runtime setting

        Returns:
            True when retry_count is below the threshold
        """
        threshold = self.max_retries if max_retries is None else max_retries
        return record.status == ActionStatus.FAILED and record.retry_count < threshold

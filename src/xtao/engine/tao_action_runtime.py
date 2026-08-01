"""TAO Action runtime - action abstraction, candidate filtering and execution.

An Action is a goal-oriented wrapper, not a raw tool. Four action types are
supported: tool_call, internal_api, user_interaction and aggregate.

Selection pipeline:
1. Coarse filter: code-side multi-dimensional filtering by intent, tags,
   preconditions, permissions, historical success rate and declarative rules.
2. Fine filter: performed by the Think engine (evidence-based selection).
3. Execution: the selected action runs through a registered executor and is
   recorded as an ActionRecord. High-availability wrappers (retry, fallback,
   circuit breaker) can be attached without changing action internals.
"""

import inspect
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from xtao.models.plan import Plan
from xtao.models.tao import (
    ActionAvailability,
    ActionCandidate,
    ActionFilterRule,
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


class PermissionError(Exception):
    """Raised when the user lacks permission for the selected action."""


class ParameterValidationError(Exception):
    """Raised when action parameters do not match the expected schema."""


class TAOActionRuntime:
    """Action execution runtime for the TAO loop.

    Attributes:
        max_retries: Default max retries per action
        circuit_breaker_threshold: Consecutive failures before disabling an action
        circuit_breaker_cooldown_seconds: Seconds before a disabled action is retried
        availability: In-memory availability tracker
    """

    def __init__(
        self,
        max_retries: int = 2,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown_seconds: float = 60.0,
    ) -> None:
        """Initialize the Action runtime.

        Args:
            max_retries: Default max retries per action
            circuit_breaker_threshold: Consecutive failures before disabling an action
            circuit_breaker_cooldown_seconds: Seconds before a disabled action is retried
        """
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_cooldown_seconds = circuit_breaker_cooldown_seconds
        self._executors: dict[str, ActionExecutor] = {}
        self._user_handler: UserInteractionHandler | None = None
        self._availability: dict[str, ActionAvailability] = {}
        self._rules: list[ActionFilterRule] = []

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

    def register_filter_rules(self, rules: list[ActionFilterRule]) -> None:
        """Register declarative filter rules used by coarse_filter.

        Args:
            rules: Declarative rules to include/exclude candidates
        """
        self._rules = list(rules)

    # ── Availability tracking (task 3.4) ──────────────────────

    def availability_of(self, name: str) -> ActionAvailability:
        """Get or create the availability record for an action."""
        if name not in self._availability:
            self._availability[name] = ActionAvailability(name=name)
        return self._availability[name]

    def record_success(self, name: str) -> None:
        """Record a successful execution for availability tracking."""
        av = self.availability_of(name)
        av.total_calls += 1
        av.success_calls += 1
        av.consecutive_failures = 0
        av.disabled = False

    def record_failure(self, name: str, reason: str) -> None:
        """Record a failed execution for availability tracking."""
        now = datetime.utcnow()
        av = self.availability_of(name)
        av.total_calls += 1
        av.failed_calls += 1
        av.last_failure_at = now
        av.last_failure_reason = reason
        av.consecutive_failures += 1
        if av.consecutive_failures >= self.circuit_breaker_threshold:
            av.disabled = True
            logger.warning(
                "Action %s disabled after %d consecutive failures",
                name,
                av.consecutive_failures,
            )

    def is_action_available(self, name: str) -> bool:
        """Return whether an action is currently available (not disabled)."""
        av = self._availability.get(name)
        if av is None:
            return True
        if not av.disabled:
            return True
        # Auto-recover after cooldown
        if (
            av.last_failure_at is not None
            and (datetime.utcnow() - av.last_failure_at).total_seconds()
            >= self.circuit_breaker_cooldown_seconds
        ):
            av.disabled = False
            av.consecutive_failures = 0
            logger.info("Action %s re-enabled after cooldown", name)
            return True
        return False

    # ── Candidate space: coarse filter (task 3.1) ─────────────

    def coarse_filter(
        self,
        candidates: list[ActionCandidate],
        plan: Plan | None = None,
        intent: str = "",
        tags: list[str] | None = None,
        state: TAOState | None = None,
        context: dict[str, Any] | None = None,
        granted_permissions: list[str] | None = None,
        required_success_rate: float = 0.0,
    ) -> list[ActionCandidate]:
        """Coarse-filter the candidate action space.

        Filtering dimensions (code-side, deterministic):
        - Disabled actions (circuit breaker) are excluded.
        - Plan node whitelist check.
        - Intent whitelist check (candidate.intents).
        - Tag filter (candidate.tags must contain all requested tags).
        - Hard preconditions (candidate.preconditions must exist as confirmed
          or user_approved facts).
        - Required parameter availability (candidate.required_params).
        - Permission check (candidate.permissions must be in granted_permissions).
        - Historical success rate threshold.
        - Declarative ActionFilterRule evaluation.

        Args:
            candidates: Full candidate list
            plan: Current Plan, if any
            intent: Current intent tag, if any
            tags: Tags that selected candidates must contain, if any
            state: Current TAO state for precondition checks
            context: Free-form context dict used by rules
            granted_permissions: Permissions the user has been granted
            required_success_rate: Minimum historical success rate (0 disables)

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

        request_tags = set(tags or [])
        permissions = set(granted_permissions or [])
        ctx = context or {}

        filtered: list[ActionCandidate] = []
        for candidate in candidates:
            # Disabled by circuit breaker
            if not self.is_action_available(candidate.name):
                continue

            # Plan node whitelist (legacy metadata)
            node_whitelist = candidate.metadata.get("plan_nodes")
            if node_whitelist and current_step_id and current_step_id not in node_whitelist:
                continue

            # Intent filter (explicit field or legacy metadata)
            intents = list(candidate.intents) or candidate.metadata.get("intents", [])
            if intents and intent and intent not in intents:
                continue

            # Tag filter: candidate must contain all requested tags
            if request_tags and not request_tags.issubset(set(candidate.tags)):
                continue

            # Precondition check: confirmed/user_approved facts
            if state is not None and candidate.preconditions:
                if not all(pre in available_facts for pre in candidate.preconditions):
                    continue

            # Required params: must exist as facts or in the provided context
            if state is not None and candidate.required_params:
                provided = set(available_facts)
                provided.update(ctx.keys())
                if not all(param in provided for param in candidate.required_params):
                    continue

            # Permission check
            if candidate.permissions:
                if not set(candidate.permissions).issubset(permissions):
                    continue

            # Historical success rate
            if required_success_rate > 0:
                av = self.availability_of(candidate.name)
                if av.total_calls > 0 and av.success_rate < required_success_rate:
                    continue

            # Declarative rules
            if not self._apply_filter_rules(candidate, available_facts, intent, ctx):
                continue

            filtered.append(candidate)

        logger.info(
            "Coarse filter: %d -> %d candidates (step=%s, intent=%s, tags=%s)",
            len(candidates),
            len(filtered),
            current_step_id,
            intent,
            tags,
        )
        return filtered

    def _apply_filter_rules(
        self,
        candidate: ActionCandidate,
        available_facts: set[str],
        intent: str,
        context: dict[str, Any],
    ) -> bool:
        """Evaluate declarative filter rules for a candidate.

        A rule matches the candidate when any of its action_names, tags or
        intent fields overlap. Once matched, the rule's include flag determines
        whether the candidate is kept (include=True) or dropped (include=False).
        """
        for rule in self._rules:
            matched = False
            if rule.action_names and candidate.name in rule.action_names:
                matched = True
            if not matched and rule.tags and set(rule.tags).intersection(set(candidate.tags)):
                matched = True
            if not matched and rule.intent and rule.intent == intent:
                matched = True
            if not matched:
                continue

            # Rule matched: evaluate fact/permission predicates
            if rule.required_facts and not all(f in available_facts for f in rule.required_facts):
                return False
            if rule.excluded_facts and any(f in available_facts for f in rule.excluded_facts):
                return False
            if rule.required_permissions:
                granted = set(context.get("granted_permissions", []))
                if not set(rule.required_permissions).issubset(granted):
                    return False

            return rule.include

        return True

    # ── Pre-execution validation (task 3.3 / 3.5) ───────────────

    def validate_candidate_in_space(
        self, action_name: str, candidate_space: list[ActionCandidate]
    ) -> ActionCandidate:
        """Validate that action_name is in the candidate space and return it.

        Args:
            action_name: Action selected by the Think engine
            candidate_space: Current coarse-filtered candidate space

        Returns:
            The matching ActionCandidate

        Raises:
            IllegalActionError: When the action is not in the candidate space
        """
        for candidate in candidate_space:
            if candidate.name == action_name:
                return candidate
        legal_names = sorted({c.name for c in candidate_space})
        raise IllegalActionError(
            f"Action '{action_name}' is not in the candidate space {legal_names}"
        )

    def validate_preconditions(
        self, candidate: ActionCandidate, state: TAOState
    ) -> None:
        """Validate that hard preconditions are satisfied.

        Args:
            candidate: Action to validate
            state: Current TAO state

        Raises:
            PreconditionError: When a hard precondition is unsatisfied
        """
        if not candidate.preconditions:
            return
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

    def validate_permissions(
        self, candidate: ActionCandidate, granted_permissions: list[str] | None = None
    ) -> None:
        """Validate that the user has the required permissions.

        Args:
            candidate: Action to validate
            granted_permissions: Permissions granted to the current user

        Raises:
            PermissionError: When a required permission is missing
        """
        if not candidate.permissions:
            return
        granted = set(granted_permissions or [])
        missing = [p for p in candidate.permissions if p not in granted]
        if missing:
            raise PermissionError(
                f"Action '{candidate.name}' requires permissions {missing}"
            )

    def validate_params(
        self, candidate: ActionCandidate, params: dict[str, Any]
    ) -> None:
        """Validate action parameters against params_schema and required_params.

        Args:
            candidate: Action to validate
            params: Parameters provided by the Think engine

        Raises:
            ParameterValidationError: When parameters are invalid
        """
        if candidate.required_params:
            missing = [p for p in candidate.required_params if p not in params]
            if missing:
                raise ParameterValidationError(
                    f"Action '{candidate.name}' missing required params: {missing}"
                )

        if candidate.params_schema:
            for key in params:
                if key not in candidate.params_schema:
                    raise ParameterValidationError(
                        f"Action '{candidate.name}' received unknown param '{key}'"
                    )

    # ── High-availability wrappers (task 3.2) ──────────────────

    def retry_wrapper(
        self,
        executor: ActionExecutor,
        max_retries: int | None = None,
        retryable_exceptions: tuple[type[Exception], ...] | None = None,
    ) -> ActionExecutor:
        """Wrap an executor with retry logic for transient failures.

        Args:
            executor: Base action executor
            max_retries: Max retry attempts; defaults to runtime setting
            retryable_exceptions: Exception types that should trigger retry

        Returns:
            Wrapped executor with retry behaviour
        """
        threshold = self.max_retries if max_retries is None else max_retries
        retryable = retryable_exceptions or (ConnectionError, TimeoutError)

        async def _run(params: dict[str, Any]) -> Any:
            last_error: Exception | None = None
            for attempt in range(threshold + 1):
                try:
                    result = executor(params)
                    if inspect.isawaitable(result):
                        return await result
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < threshold and isinstance(e, retryable):
                        logger.info(
                            "Retrying action after transient error (attempt %d/%d): %s",
                            attempt + 1,
                            threshold,
                            e,
                        )
                        continue
                    raise
            raise ActionExecutionError(
                f"Action failed after {threshold} retries: {last_error}"
            )

        return _run

    def fallback_wrapper(
        self,
        executor: ActionExecutor,
        fallback_executor: ActionExecutor,
        fallback_on: tuple[type[Exception], ...] | None = None,
    ) -> ActionExecutor:
        """Wrap an executor with a fallback executor when the primary fails.

        Args:
            executor: Primary executor
            fallback_executor: Fallback executor invoked when primary fails
            fallback_on: Exception types that trigger fallback

        Returns:
            Wrapped executor with fallback behaviour
        """
        fail_types = fallback_on or (Exception,)

        async def _run(params: dict[str, Any]) -> Any:
            try:
                result = executor(params)
                if inspect.isawaitable(result):
                    return await result
                return result
            except Exception as e:
                if isinstance(e, fail_types):
                    logger.info("Primary action failed, running fallback: %s", e)
                    result = fallback_executor(params)
                    if inspect.isawaitable(result):
                        return await result
                    return result
                raise

        return _run

    def circuit_breaker_wrapper(
        self,
        name: str,
        executor: ActionExecutor,
    ) -> ActionExecutor:
        """Wrap an executor with circuit breaker / availability tracking.

        Args:
            name: Action name used for availability tracking
            executor: Base executor

        Returns:
            Wrapped executor that tracks success/failure and disables the action
            after too many consecutive failures
        """

        async def _run(params: dict[str, Any]) -> Any:
            if not self.is_action_available(name):
                raise ActionExecutionError(
                    f"Action '{name}' is currently disabled by circuit breaker"
                )
            try:
                result = executor(params)
                if inspect.isawaitable(result):
                    result = await result
                self.record_success(name)
                return result
            except Exception as e:
                self.record_failure(name, str(e))
                raise

        return _run

    # ── Execution (tasks 4.4-4.7) ─────────────────────────────

    async def execute(
        self,
        candidate: ActionCandidate,
        params: dict[str, Any],
        state: TAOState,
        retry_of: ActionRecord | None = None,
        granted_permissions: list[str] | None = None,
    ) -> ActionRecord:
        """Execute a candidate action and record an ActionRecord.

        Args:
            candidate: The selected action candidate
            params: Action parameters from ThinkResult
            state: Current TAO state (used for precondition re-check)
            retry_of: Previous failed record when this is a retry
            granted_permissions: Permissions granted to the current user

        Returns:
            Completed ActionRecord (status done or failed)

        Raises:
            IllegalActionError: When the candidate is not in the state's space
            PreconditionError: When a hard precondition is unsatisfied
            PermissionError: When required permissions are missing
            ParameterValidationError: When params are invalid
        """
        # Task 4.8 + 3.5: illegal action check against current candidate space
        self.validate_candidate_in_space(candidate.name, state.candidate_actions)

        # Task 3.3: pre-execution validations
        self.validate_preconditions(candidate, state)
        self.validate_permissions(candidate, granted_permissions)
        self.validate_params(candidate, params)

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
            self.record_success(candidate.name)
        except Exception as e:
            record.error = str(e)
            record.status = ActionStatus.FAILED
            self.record_failure(candidate.name, str(e))
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

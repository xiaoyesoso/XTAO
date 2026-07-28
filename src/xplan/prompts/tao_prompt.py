"""TAO prompt module - Think / Observation / Supervisor prompts and boundary rules.

Covers:
- Think system & user prompts (five structured judgments)
- Observation system & user prompts (structured interpretation)
- Supervisor (outer loop) prompts
- Boundary rules injected into every Think/Observation prompt
"""

from xplan.models.tao import ActionCandidate, TAOState


# ── Boundary rules (design decision 11) ───────────────────────

BOUNDARY_RULES: list[str] = [
    "You may ONLY choose from the candidate actions provided. Never invent new tools or actions.",
    "Never skip unsatisfied hard preconditions. Distinguish mandatory preconditions from nice-to-have ones.",
    "Never upgrade assumptions or speculation to facts. Facts must be explicitly marked as assumption, inference or confirmed fact.",
    "Every fact and state change must be bound to evidence (an action_id, tool output or user input).",
    "Never modify the user's goal or hard constraints on your own. Goals and constraints are read-only.",
    "When missing information affects the core result and cannot be obtained via available tools, you MUST choose clarify.",
    "When the path itself is fine and only the current action failed transiently, choose retry (respect retry limits).",
    "When new facts invalidate the current path or the path cannot continue, choose replan.",
    "When the success criteria are already satisfied, you MUST choose finish. Never call tools just to keep looping.",
    "When no candidate action can advance the goal, choose clarify / replan / interrupt. Never repeat ineffective actions.",
]

EXIT_RULES: list[str] = [
    "finish: success criteria satisfied and no critical information gap remains.",
    "retry: the current path is fine, only the last action failed transiently (timeout, network, format).",
    "replan: new facts invalidate the current path, or the current path/tool choice itself is problematic.",
    "clarify: critical information is missing and cannot be obtained with available tools.",
    "interrupt: key tools are unavailable, budget exceeded, or loop limits reached without satisfying success criteria.",
    "continue: the goal is not yet complete and at least one candidate action can advance it.",
]


def build_boundary_rules_text() -> str:
    """Build the boundary rules block injected into Think prompts."""
    lines = [f"{i + 1}. {rule}" for i, rule in enumerate(BOUNDARY_RULES)]
    return "\n".join(lines)


def build_exit_rules_text() -> str:
    """Build the exit selection rules block."""
    return "\n".join(f"- {rule}" for rule in EXIT_RULES)


# ── Think prompts (tasks 3.1, 3.2) ────────────────────────────


def build_tao_think_system_prompt(
    hard_constraints: list[str] | None = None,
    soft_constraints: list[str] | None = None,
) -> str:
    """Build the Think system prompt.

    Injects Goal/Context/Constraint anchoring plus boundary rules and exit rules.

    Args:
        hard_constraints: Hard constraints, cannot be violated
        soft_constraints: Soft constraints, should be satisfied

    Returns:
        Think system prompt text
    """
    hard = hard_constraints or []
    soft = soft_constraints or []
    hard_text = "\n".join(f"- {c}" for c in hard) if hard else "- (No hard constraints)"
    soft_text = "\n".join(f"- {c}" for c in soft) if soft else "- (No soft constraints)"

    return f"""# Role and Responsibilities
You are the Think engine of a TAO (Think-Action-Observation) controlled state loop. In each round you must complete FIVE structured judgments and output a single JSON object.

# The Five Judgments
1. **Goal judgment**: Are we approaching the final goal or a stage goal? Are the success criteria satisfied? Is the current stage goal completed?
2. **State judgment**: Are the known facts sufficient? Are there missing slots, unverified assumptions or fact conflicts?
3. **Path judgment**: From the candidate actions, which one best advances the goal? Weigh goal progress, information gain, cost, risk and rollbackability.
4. **Stop judgment**: Is the information sufficient to answer the user? Would continuing noticeably improve quality? Is the budget exceeded? Should a partial result be returned?
5. **Risk judgment**: Could the selected action violate a hard constraint or cause high risk? If so, prefer clarify or replan.

# Boundary Rules (MUST follow)
{build_boundary_rules_text()}

# Exit Selection Rules
{build_exit_rules_text()}

# Hard Constraints (cannot be violated)
{hard_text}

# Soft Constraints (should be satisfied)
{soft_text}

# Output Format (JSON only, no extra text)
```json
{{
  "current_goal": "the goal being pursued this round",
  "success_criteria_satisfied": false,
  "current_goal_completed": false,
  "facts_sufficient": false,
  "missing_slots": ["slot_key"],
  "unverified_assumptions": ["assumption"],
  "fact_conflicts": [],
  "selected_action": "action name from candidates, empty when exit is not continue/retry",
  "action_params": {{}},
  "should_stop": false,
  "exit_decision": "continue | finish | clarify | retry | replan | interrupt",
  "reason": "evidence-based reason referencing Goal/Context/Constraint",
  "risk_level": "low | medium | high",
  "risk_reason": "required when risk_level is not low"
}}
```"""


def build_tao_think_user_prompt(state: TAOState) -> str:
    """Build the Think user prompt from the current TAO state.

    Args:
        state: Current TAO runtime state

    Returns:
        Think user prompt text
    """
    goal = state.goal_state
    criteria = "\n".join(f"- {c}" for c in goal.success_criteria) or "- (none)"

    fact_lines: list[str] = []
    for f in state.facts.values():
        value_text = f.value if f.value is not None else "(missing)"
        evidence = f", evidence: {f.evidence}" if f.evidence else ""
        fact_lines.append(f"- [{f.category.value}] {f.key}: {value_text}{evidence}")
    facts_text = "\n".join(fact_lines) or "- (no facts yet)"

    candidate_lines: list[str] = []
    for c in state.candidate_actions:
        pre = f", preconditions: {c.preconditions}" if c.preconditions else ""
        candidate_lines.append(
            f"- {c.name} ({c.type.value}): {c.description}{pre}, rollbackable={c.rollbackable}"
        )
    candidates_text = "\n".join(candidate_lines) or "- (no candidate actions)"

    history_lines: list[str] = []
    for record in state.actions[-5:]:
        obs = next(
            (o for o in state.observations if o.action_id == record.action_id),
            None,
        )
        obs_text = f" -> {obs.summary}" if obs and obs.summary else ""
        history_lines.append(
            f"- {record.action_id} {record.name}: {record.status.value}{obs_text}"
        )
    history_text = "\n".join(history_lines) or "- (no actions executed yet)"

    return f"""# Current TAO State

## Goal State
- final_goal: {goal.final_goal}
- current_goal: {goal.current_goal}
- current_goal_completed: {goal.current_goal_completed}
- success_criteria:
{criteria}

## Fact State
{facts_text}

## Candidate Actions (coarse-filtered, choose ONLY from these)
{candidates_text}

## Recent Action/Observation History (latest 5)
{history_text}

## Control State
- used_loops: {state.control.used_loops} / max_loops: {state.control.max_loops}

Complete the five judgments and output the JSON object."""


# ── Observation prompts (tasks 5.1, 5.2) ──────────────────────


def build_tao_observation_system_prompt() -> str:
    """Build the Observation system prompt.

    Returns:
        Observation system prompt text
    """
    return """# Role and Responsibilities
You are the Observation interpreter of a TAO loop. You convert the raw output of an Action into a structured Observation.

# You Must Answer
- Did the action REALLY succeed? (HTTP 200 does not equal real success; empty data, permission errors or irrelevant content mean partial_success or failed)
- Which new facts were obtained? What is the evidence for each fact (must reference the action output or user input)?
- Did the result match the pre-execution expectation?
- Which information is still missing?
- Were there anomalies, constraint violations or invalidated assumptions?
- What changed in the state? Was real progress made?

# Rules
- Never fabricate facts. Every fact must be traceable to the raw output.
- Mark uncertain inferences as category "speculative", never as "confirmed".
- If the output repeats earlier results with nothing new, set progress=false and information_gain=low.

# Output Format (JSON only, no extra text)
```json
{
  "execution_status": "success | partial_success | failed",
  "new_facts": [
    {"key": "fact_key", "value": "fact value", "category": "confirmed | speculative", "evidence": "where in the output this comes from"}
  ],
  "missing_information": ["still missing info"],
  "state_changes": ["what changed"],
  "anomalies": ["anomaly or violated assumption"],
  "suggested_next_action": "advisory next action name, may be empty",
  "progress": true,
  "information_gain": "low | medium | high",
  "summary": "one-sentence summary"
}
```"""


def build_tao_observation_user_prompt(
    state: TAOState,
    action_name: str,
    action_input: dict,
    raw_output: object,
    expectation: str = "",
) -> str:
    """Build the Observation user prompt.

    Args:
        state: Current TAO runtime state
        action_name: Executed action name
        action_input: Action input parameters
        raw_output: Raw action output (any JSON-serializable object)
        expectation: Pre-execution expectation, if any

    Returns:
        Observation user prompt text
    """
    known = "\n".join(
        f"- [{f.category.value}] {f.key}: {f.value if f.value is not None else '(missing)'}"
        for f in state.facts.values()
    ) or "- (none)"

    return f"""# Context

## Current Goal
{state.goal_state.current_goal}

## Known Facts Before This Action
{known}

## Executed Action
- name: {action_name}
- input: {action_input}
- expectation: {expectation or "(not specified)"}

## Raw Action Output
{raw_output}

Interpret the raw output and output the structured Observation JSON."""


# ── Supervisor (outer loop) prompts ───────────────────────────


def build_tao_supervisor_system_prompt(
    hard_constraints: list[str] | None = None,
) -> str:
    """Build the outer-loop supervisor system prompt.

    Args:
        hard_constraints: Hard constraints to check violations against

    Returns:
        Supervisor system prompt text
    """
    hard = hard_constraints or []
    hard_text = "\n".join(f"- {c}" for c in hard) if hard else "- (No hard constraints)"

    return f"""# Role and Responsibilities
You are the outer-loop supervisor of a double-layer TAO loop. The inner loop executes Think-Action-Observation rounds; you supervise the overall direction.

# You Must Check
1. **Goal drift**: Is the sequence of recent actions still advancing the final goal?
2. **Constraint violation**: Did any action or intermediate result violate a hard constraint?
3. **Stagnation**: Has real progress stalled over recent rounds (repeated similar actions, no new facts)?
4. **Cascading errors**: Are errors or invalid facts accumulating across rounds?

# Hard Constraints
{hard_text}

# Output Format (JSON only, no extra text)
```json
{{
  "goal_drift": false,
  "drift_explanation": "",
  "constraint_violations": [],
  "stagnation": false,
  "intervention": "none | replan | clarify | interrupt",
  "reason": "evidence-based reason referencing concrete actions or facts"
}}
```"""


def build_tao_supervisor_user_prompt(state: TAOState) -> str:
    """Build the outer-loop supervisor user prompt.

    Args:
        state: Current TAO runtime state

    Returns:
        Supervisor user prompt text
    """
    goal = state.goal_state

    history_lines: list[str] = []
    for record in state.actions:
        obs = next(
            (o for o in state.observations if o.action_id == record.action_id),
            None,
        )
        obs_text = ""
        if obs is not None:
            obs_text = (
                f" | status={obs.execution_status.value}, progress={obs.progress}, "
                f"gain={obs.information_gain.value}"
            )
            if obs.anomalies:
                obs_text += f", anomalies={obs.anomalies}"
        history_lines.append(f"- {record.name}: {record.status.value}{obs_text}")
    history_text = "\n".join(history_lines) or "- (no actions yet)"

    criteria = "\n".join(f"- {c}" for c in goal.success_criteria) or "- (none)"

    return f"""# TAO Execution Snapshot

## Goal
- final_goal: {goal.final_goal}
- current_goal: {goal.current_goal}
- success_criteria:
{criteria}

## Full Action/Observation History ({len(state.actions)} actions, {state.control.used_loops} loops)
{history_text}

Review the execution and output the supervision JSON."""

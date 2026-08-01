"""Replan prompt module - Controlled correction mechanism.

Replan is the core implementation of Correction: during execution, based on new
Goal, Context, Choice, and Checkpoint results, performs controlled correction
of the original plan.

This module provides three prompt builder functions:
- System prompt: constraint injection, evidence-based requirements, categorized output requirements
- Judge user prompt: judge whether Replan is needed
- Execute user prompt: execute Replan and output categorized change records
"""


def build_replan_system_prompt(
    hard_constraints: list[str], soft_constraints: list[str]
) -> str:
    """Build the Replan system prompt.

    Contains the following core requirements:
    1. Require bringing the complete G4C context (Goal/Context/Checkpoint results and evidence)
    2. Constraint re-emphasis injection (hard constraints cannot be violated, soft constraints should be satisfied)
    3. Require categorized output (retained/modified/removed steps + each with evidence-based reason)
    4. Evidence-based requirements: all Replan judgments must be based on evidence
    5. Clarify when to ask the user (constraint-related / parameter missing / key tool failure with no alternative)
    6. Permission and sensitive operations need user authorization in the Plan stage

    Args:
        hard_constraints: list of hard constraints, cannot be violated
        soft_constraints: list of soft constraints, should be satisfied

    Returns:
        Replan system prompt text
    """
    hard_text = (
        "\n".join(f"  - {c}" for c in hard_constraints)
        if hard_constraints
        else "  - (No hard constraints)"
    )
    soft_text = (
        "\n".join(f"  - {c}" for c in soft_constraints)
        if soft_constraints
        else "  - (No soft constraints)"
    )

    return f"""# Role and Responsibilities
You are the Replan expert in the G4C methodology. Your responsibility is to perform controlled correction
of the original plan during execution, based on new Goal, Context, Choice, and Checkpoint results.

Keywords of Replan: during execution, new information, controlled correction. Replan is not casually
rewriting the Plan, but evidence-based controlled correction.

# G4C Complete Context Requirements
When performing Replan judgment and execution, the complete G4C context must be brought:
1. **Goal**: current goal and success criteria (judge whether the goal needs adjustment)
2. **Context**: known facts, missing information, and constraints (judge whether the context has changed)
3. **Checkpoint results and evidence**: whether checkpoints passed, failed check items and their evidence (judge whether assumptions are violated)
4. **Choice**: current path decision and steps (judge whether the path needs adjustment)

# Constraint Management (Must read on every call)

## Hard Constraints (HARD - cannot be violated, execution must be blocked when violated)
{hard_text}

## Soft Constraints (SOFT - should be satisfied, recorded but allowed to continue when violated)
{soft_text}

## Constraint Rules
1. When a hard constraint is violated, **execution must be blocked**
2. When a soft constraint is violated, **record but allow to continue**
3. Constraints can only be modified by user input, Agent cannot modify constraints autonomously
4. Every constraint modification must be evidenced by user input

# Evidence-based Requirements (Key)
All Replan judgments must be based on evidence:
1. **No evidence, no claiming Goal changed**: must have explicit new user input or checkpoint evidence
2. **No evidence, no claiming Context changed**: must have new constraints or supplementary information added by the user
3. **No evidence, no claiming hard constraints changed**: hard constraints can only be modified by user input
4. All change reasons must reference specific facts, constraints, or checkpoint results

# Categorized Output Requirements
Replan execution results must be output categorized, each change must carry an evidence-based reason:
1. **retained_steps** (retained steps): steps that need no change, explain the retention reason
2. **modified_steps** (modified steps): steps that need modification, explain the modification reason and modification details
3. **removed_steps** (removed steps): steps no longer needed, explain the removal reason

# When to Ask the User
When the following three types of situations occur, you must ask the user, and cannot Replan autonomously:
1. **Constraint-related**: Replan involves changes to hard constraints, must be confirmed by the user
2. **Parameter missing**: critical information is missing, cannot complete Replan based on existing information
3. **Key tool failure with no alternative**: core tool is unavailable and there is no alternative path

# Permission and Sensitive Operations
1. Permission and sensitive operations (such as data deletion, fund operations, system configuration changes) need user authorization in the Plan stage
2. Replan must not introduce sensitive operations not authorized by the user
3. If the Plan after Replan contains more sensitive operations than the original Plan, need to mark and request authorization

# Replan Granularity
- **step**: current step Replan, retain previously completed steps, only re-plan the current and subsequent steps
- **partial**: partial Replan, re-plan starting from the specified rollback step
- **global**: global Replan, generate a brand new Plan from scratch (only used when the Plan is fundamentally wrong)

# Replan Trigger Timing
- **tool_failure**: tool call failed (non-transient), the original Plan's tool selection was wrong
- **context_change**: context has changed, the user added new information or constraints
- **assumption_violation**: assumption violated, checkpoint not passed indicates the original Plan's assumptions were wrong"""


def build_replan_judge_prompt(
    plan_json: str, error_info: str, check_results_json: str
) -> str:
    """Build the Replan judge user prompt.

    Args:
        plan_json: JSON string of the current Plan
        error_info: error information description (can be empty)
        check_results_json: JSON string of the checkpoint result list

    Returns:
        Replan judge user prompt text
    """
    return f"""Please judge whether Replan is needed based on the following information.

## Current Plan
{plan_json}

## Error Information
{error_info or "(No error information)"}

## Checkpoint Results
{check_results_json or "(No checkpoint results)"}

## Judgment Requirements
1. Judge whether the current Plan needs Replan (needs_replan)
2. If Replan is needed, determine the trigger timing type (trigger):
   - tool_failure: tool call failed (non-transient)
   - context_change: context has changed
   - assumption_violation: assumption violated (checkpoint not passed)
3. If Replan is needed, suggest Replan granularity (granularity):
   - step: only the current step has problems
   - partial: partial flow has problems
   - global: Plan is fundamentally wrong
4. If partial granularity, specify the rollback target step ID (rollback_step_id)
5. All judgments must be evidence-based, explain the basis in the reason and evidence fields

## Output Format
```json
{{
  "needs_replan": true,
  "trigger": "tool_failure",
  "reason": "judgment reason",
  "evidence": "judgment evidence, referencing specific errors or checkpoint results",
  "granularity": "step",
  "rollback_step_id": null
}}
```

Please output the judgment result in JSON format."""


def build_replan_execute_prompt(
    plan_json: str,
    judgment_json: str,
    replan_info_json: str,
    conversation_history: str,
) -> str:
    """Build the Replan execute user prompt.

    Args:
        plan_json: JSON string of the current Plan
        judgment_json: JSON string of the Replan judgment result
        replan_info_json: JSON string of the Replan control information
        conversation_history: conversation history, used to extract context

    Returns:
        Replan execute user prompt text
    """
    return f"""Please execute Replan based on the following information, generate a new Plan and categorize step changes.

## Current Plan
{plan_json}

## Replan Judgment Result
{judgment_json}

## Replan Control Information
{replan_info_json}

## Conversation History
{conversation_history or "(No conversation history)"}

## Execution Requirements
1. Execute the corresponding granularity of Replan according to judgment.granularity:
   - step: re-plan subsequent steps starting from the current step, retain previously completed steps
   - partial: re-plan starting from judgment.rollback_step_id
   - global: generate a brand new Plan from scratch
2. Generate a new Plan (new_plan), keep the G4C structure complete (Goal/Context/Choice/Checkpoint/Correction)
3. Categorize step changes, each must carry an evidence-based reason:
   - retained_steps: retained steps and reasons
   - modified_steps: modified steps and reasons and modification details
   - removed_steps: removed steps and reasons
4. Constraints must be faithfully echoed, cannot autonomously modify hard constraints
5. Must not introduce sensitive operations not authorized by the user

## Output Format
```json
{{
  "retained_steps": [
    {{
      "step_id": "step ID",
      "reason": "retention reason (evidence-based)",
      "change_type": "retained",
      "modification_detail": ""
    }}
  ],
  "modified_steps": [
    {{
      "step_id": "step ID",
      "reason": "modification reason (evidence-based)",
      "change_type": "modified",
      "modification_detail": "modification detail description"
    }}
  ],
  "removed_steps": [
    {{
      "step_id": "step ID",
      "reason": "removal reason (evidence-based)",
      "change_type": "removed",
      "modification_detail": ""
    }}
  ],
  "new_plan": {{
    "goal": {{...}},
    "context": {{...}},
    "choice": {{...}},
    "checkpoint": [...],
    "correction": [...]
  }}
}}
```

Please output the Replan execution result in JSON format."""

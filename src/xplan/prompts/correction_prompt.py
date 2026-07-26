"""Correction prompt module - Correction mechanism and failure recovery.

Resolves failure uncertainty: what to do after a deviation is discovered.
Lists five correction strategies (retry/replan/clarify/rollback/abort) and
applicable scenarios.
"""

from xplan.prompts.constants import RAG_CONTEXT_PLACEHOLDER


def build_correction_system_prompt() -> str:
    """Build the Correction system prompt.

    Lists five correction strategies and applicable scenarios:
    1. Retry: tool occasional failure, format error, network timeout
    2. Replan: the Plan itself has problems
    3. Clarify: insufficient information, prioritize collecting information
    4. Rollback: data/state has errors, used with Checkpoint
    5. Abort: unrecoverable error

    Returns:
        Correction system prompt text
    """
    return """# Role and Responsibilities
You are the Correction design expert in the G4C methodology. Your responsibility is to define correction rules for the Plan, ensuring failures are recoverable.

# Five Correction Strategies

| Strategy | Type | Applicable Scenario | Modifies Plan |
|---|---|---|---|
| Retry | retry | tool occasional failure, format error, network timeout | No |
| Replan | replan | the Plan itself has problems | Yes |
| Clarify | clarify | insufficient information, prioritize collecting information | No |
| Rollback | rollback | data/state has errors, used with Checkpoint | No |
| Abort | abort | unrecoverable error | No |

## Strategy 1: Retry (retry)
- **Applicable scenario**: tool occasional failure, API timeout, format error, etc., not Plan itself problems
- **Retry granularity**:
  - `step`: single step retry
  - `partial_flow`: partial flow retry (starting from a certain step)
  - `full_restart`: full retry
- **Modifies Plan**: No
- **Example**: network timeout -> retry the step

## Strategy 2: Replan (replan)
- **Applicable scenario**: the Plan itself has problems, such as wrong path selection, missing steps
- **Modifies Plan**: Yes (regenerate Plan)
- **Example**: find the Plan is missing a key step -> regenerate Plan

## Strategy 3: Clarify (clarify)
- **Applicable scenario**: when information is insufficient, prioritize collecting information from the user
- **Modifies Plan**: No
- **Example**: missing project background information -> ask the user

## Strategy 4: Rollback (rollback)
- **Applicable scenario**: data or state has errors, needs to be used with Checkpoint
- **Modifies Plan**: No
- **Example**: find generated content violates hard constraints -> rollback to before checkpoint and re-execute

## Strategy 5: Abort (abort)
- **Applicable scenario**: unrecoverable error, continuing execution is meaningless
- **Modifies Plan**: No
- **Example**: user explicitly gives up -> abort execution

# Core Principles
1. **Structured output**: output a JSON array, each correction rule contains:
   - `condition` (string): trigger condition description
   - `action` (object): correction action, containing:
     - `type`: correction strategy type (retry/replan/clarify/rollback/abort)
     - `retry_granularity`: retry granularity (only valid when type=retry, options: step/partial_flow/full_restart)
     - `target_step_id`: target step ID (for rollback or partial retry)
     - `params`: extra parameters
     - `message`: correction action description

2. **Priority**:
   - Occasional failures prioritize retry, avoid unnecessary Replan
   - Insufficient information prioritizes clarify, avoid continuing execution based on assumptions
   - When hard constraints are violated, prioritize rollback or Replan

# Output Format
```json
[
  {
    "condition": "missing key project information",
    "action": {
      "type": "clarify",
      "message": "clarify missing project information with the user"
    }
  },
  {
    "condition": "generated content violates no-fabrication constraint",
    "action": {
      "type": "rollback",
      "target_step_id": "generate_highlights",
      "message": "rollback to before highlight generation and re-execute"
    }
  }
]
```

# Notes
- Correction rules should cover the main risk scenarios in Plan execution
- action.type must be one of the five strategies
- Rollback strategy must specify target_step_id"""


def build_correction_user_prompt(plan_json: str, rag_context: str = "") -> str:
    """Build the Correction user prompt.

    Args:
        plan_json: JSON string of the Plan object
        rag_context: correction scenario context retrieved via RAG, optional

    Returns:
        Correction user prompt text
    """
    prompt = f"""Please design correction rules based on the following Plan.

## Plan
{plan_json}
"""
    if rag_context and rag_context.strip():
        prompt += f"""
## Correction Scenario Reference (RAG retrieval results)
{rag_context}

Please refer to the above correction scenarios, and design correction rules combined with the actual steps of the Plan.
"""
    else:
        prompt += f"""
{RAG_CONTEXT_PLACEHOLDER}
"""

    prompt += """
## Task Requirements
1. Analyze the failure scenarios that may occur in each step of the Plan
2. Define correction rules for key failure scenarios, choosing appropriate correction strategies
3. Occasional failures prioritize retry, insufficient information prioritizes clarify, hard constraint violations prioritize rollback
4. Cover main risks, no need to define correction rules for every step

Please output the correction rule list in JSON array format."""
    return prompt

"""Failure backtracking and root cause localization prompt module.

Core concept: failure point ≠ root cause point. Backtracking through reverse
investigation of the chain, starting from the failure point and checking layer
by layer upstream, finds the root cause point where the error was first introduced.

This module provides two prompt builder functions:
- System prompt: four-point definitions, reverse investigation checklist, code
  and LLM division of labor, Checkpoint reliability review
- User prompt: inject Plan, failure information, and step execution records
"""


def build_tracing_system_prompt() -> str:
    """Build the root cause localization system prompt.

    Contains the following core content:
    1. Four-point definitions (failure point/root cause point/rollback point/Replan start point)
    2. Emphasize failure point ≠ root cause point
    3. Reverse investigation checklist (6 categories of questions)
    4. Code and LLM division of labor description
    5. Checkpoint reliability review requirements
    6. Require output of structured FailureTracingResult JSON

    Returns:
        Root cause localization system prompt text
    """
    return """# Role and Responsibilities
You are the failure backtracking and root cause localization expert in the G4C methodology. Your responsibility
is to find the true root cause point through reverse investigation after execution failure, and provide
rollback point and Replan start point suggestions.

# Core Principle: failure point ≠ root cause point
- **Failure point**: the location where the error is exposed (usually the step that failed execution), is the symptom, not the cause
- **Root cause point**: the location where the error was first introduced, may be in the failed step itself, or in an earlier upstream step or context
- The goal of backtracking is to find the root cause point, not to stay at the failure point

# Four-point Definitions
1. **failure_point**: the location where the error is exposed. Must be filled, contains step_id, action, error
2. **root_cause_point**: the location where the error was first introduced. Can be empty (when the failure point is the root cause point)
3. **rollback_point**: the location where the state can be recovered, usually the step corresponding to the nearest trusted Checkpoint
4. **replan_start_point**: the starting location for re-planning, usually equal to the root cause point or rollback point

# Reverse Investigation Checklist (must check item by item)
Starting from the failure point, investigate layer by layer upstream according to the following 6 categories of questions:

1. **Did the current step itself execute incorrectly?**
   - Check whether the failed step's tool call, input parameters, and execution logic are correct
   - If the current step itself is wrong, the root cause point may be the failure point itself

2. **Is the current step input correct?**
   - Check the input data source of the failed step
   - If the input is wrong, the root cause point is in the upstream step that produced the wrong input

3. **Are the upstream intermediate results still trustworthy?**
   - Check whether the outputs of upstream steps that the failed step depends on are valid
   - If the upstream intermediate results have been polluted, the root cause point is in the step that first produced the polluted result

4. **Are the facts that upstream results depend on correct?**
   - Check whether there are erroneous facts in Context.known_facts
   - If the facts are wrong, the root cause point is in the step or context that introduced the erroneous facts

5. **Do the assumptions the original plan depends on still hold?**
   - Check whether the assumptions in the step execution records are violated
   - If the assumptions are violated, the root cause point is in the earliest step that depended on that assumption

6. **Have the user goal and constraints changed?**
   - Check whether Goal and Context.constraints are inconsistent with the snapshots in the execution records
   - If the goal or constraints changed, the root cause point is in the earliest step that did not respond to the change in time

# Code and LLM Division of Labor
- Code is responsible for: building the reverse investigation chain (determining upstream and downstream steps), finding the nearest Checkpoint, checking circular dependencies
- LLM is responsible: semantic root cause judgment, goal change judgment, constraint impact analysis, result reusability analysis
- What you receive is the reverse investigation chain already built by code, you need to perform semantic analysis on this basis

# Checkpoint Reliability Review
Must review the credibility of Checkpoints:
1. If the Checkpoint is a deterministic check implemented in code, the credibility is high
2. If the failure point is shortly after the Checkpoint passed, need to suspect whether the Checkpoint missed detection
3. If the reverse investigation finds that the context data when the Checkpoint was executed may have problems, mark checkpoint_reliable=false
4. If there is no related Checkpoint or the Checkpoint has expired, mark checkpoint_reliable=false

# Output Requirements
Must output structured FailureTracingResult JSON:
- failure_point: must be filled, contains step_id, action, error
- root_cause_point: root cause point, can be empty
- rollback_point: rollback point, can be empty
- replan_start_point: Replan start point, can be empty
- tracing_chain: reverse investigation chain, each item contains step_id and reason
- checkpoint_reliable: whether the Checkpoint is trustworthy, boolean
- All reason fields must be evidence-based, referencing specific execution records or context"""


def build_tracing_user_prompt(
    plan_json: str,
    failure_info: str,
    step_records_json: str,
) -> str:
    """Build the root cause localization user prompt.

    Args:
        plan_json: JSON string of the current Plan
        failure_info: failure information description (including failed step ID, action, error information)
        step_records_json: JSON string of the step execution record list

    Returns:
        Root cause localization user prompt text
    """
    return f"""Please perform failure backtracking and root cause localization based on the following information.

## Current Plan
{plan_json}

## Failure Information
{failure_info or "(No failure information)"}

## Step Execution Records
{step_records_json or "(No step execution records)"}

## Analysis Requirements
1. Confirm the failure point (failure_point), containing step_id, action, error
2. Check item by item according to the 6-category reverse investigation checklist, find the root cause point (root_cause_point)
3. Determine the rollback point (rollback_point), usually the step corresponding to the nearest trusted Checkpoint
4. Determine the Replan start point (replan_start_point), usually equal to the root cause point or rollback point
5. Review Checkpoint reliability (checkpoint_reliable)
6. All judgments must be evidence-based, referencing specific execution records in the reason field

## Output Format
```json
{{
  "failure_point": {{
    "step_id": "failed step ID",
    "reason": "reason for judging as failure point",
    "checkpoint_id": null,
    "action": "failed action",
    "error": "error information"
  }},
  "root_cause_point": {{
    "step_id": "root cause step ID",
    "reason": "reason for judging as root cause point (evidence-based)",
    "checkpoint_id": null,
    "action": "",
    "error": ""
  }},
  "rollback_point": {{
    "step_id": "rollback step ID",
    "reason": "reason for judging as rollback point",
    "checkpoint_id": "associated Checkpoint ID or null",
    "action": "",
    "error": ""
  }},
  "replan_start_point": {{
    "step_id": "Replan start point step ID",
    "reason": "reason for judging as Replan start point",
    "checkpoint_id": null,
    "action": "",
    "error": ""
  }},
  "tracing_chain": [
    {{
      "step_id": "step ID",
      "reason": "judgment of this step in the investigation chain",
      "checkpoint_id": null,
      "action": "",
      "error": ""
    }}
  ],
  "checkpoint_reliable": true
}}
```

Please output the failure backtracking result in JSON format."""

"""Choice prompt module - Path decision and steps.

Resolves path uncertainty: what paths are available and why this path is chosen.
Requires output of candidate paths and selection reasons (evidence-based),
each step contains id, objective, reason.
"""


def build_choice_system_prompt() -> str:
    """Build the Choice system prompt.

    Requirements:
    - Output candidate paths and selection reasons (evidence-based)
    - Selection reasons must be based on facts or constraints in the context
    - Each step contains id, objective, reason

    Returns:
        Choice system prompt text
    """
    return """# Role and Responsibilities
You are the Choice decision expert in the G4C methodology. Your responsibility is to make evidence-based path decisions based on Goal and Context.

# Core Principles
1. **Structured output**: Must output a JSON-formatted choice object containing the following fields:
   - `selected_path` (string): description of the selected path
   - `reason` (string): selection reason, must be based on facts or constraints in the context (evidence-based)
   - `candidate_paths` (string array): list of candidate paths
   - `steps` (object array): list of steps, each step contains id, objective, reason

2. **Evidence-based decision** (key):
   - Selection reasons (reason) must reference facts or constraints in the context
   - Cannot fabricate path reasons
   - Example: ✓ "If wrapped directly, it easily violates the no-fabrication requirement"
   - Example: ✗ "This is the best path" (no evidence support)

3. **Candidate paths**:
   - List at least 2 candidate paths
   - Explain why other paths were not selected (reflected in reason)

4. **Step definition**:
   - Each step must contain:
     - `id`: unique step identifier (snake_case English)
     - `objective`: step objective (clear description)
     - `reason`: reason for the step's existence, supports traceability
   - Steps should be logically coherent, progressively advancing goal achievement
   - The number of steps should be moderate, avoid being too fine or too coarse

# Output Format
```json
{
  "selected_path": "description of the selected path",
  "reason": "selection reason, referencing facts or constraints in the context",
  "candidate_paths": [
    "candidate path 1",
    "candidate path 2"
  ],
  "steps": [
    {
      "id": "extract_facts",
      "objective": "extract existing facts",
      "reason": "need to distinguish facts from speculation, providing basis for subsequent steps"
    }
  ]
}
```

# Notes
- Path selection must serve the Goal and comply with constraints in Context
- Prefer the path with the least risk and highest reliability
- If there are hard constraint conflicts, choose a path that avoids violating hard constraints"""


def build_choice_user_prompt(goal_json: str, context_json: str) -> str:
    """Build the Choice user prompt.

    Args:
        goal_json: JSON string of the Goal object
        context_json: JSON string of the Context object

    Returns:
        Choice user prompt text
    """
    return f"""Please make an evidence-based path decision based on the following Goal and Context.

## Goal
{goal_json}

## Context
{context_json}

## Task Requirements
1. Based on the above Goal and Context, list at least 2 candidate paths
2. Select the optimal path, and provide selection reasons based on facts or constraints
3. Break down the selected path into specific steps, each step containing id, objective, reason
4. The path and steps must comply with hard constraints in Context

Please output the choice object in JSON format."""

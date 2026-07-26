"""Context prompt module - Context and constraint management.

Resolves context uncertainty: what is currently known, what is missing, which
constraints cannot be violated. Emphasizes constraints (hard/soft constraints
injected separately), requires structured output of known_facts and missing_info.
"""

from xplan.prompts.constants import RAG_CONTEXT_PLACEHOLDER


def build_context_system_prompt(
    hard_constraints: list[str], soft_constraints: list[str]
) -> str:
    """Build the Context system prompt.

    Emphasizes constraint management:
    - Hard constraints (hard) cannot be violated, execution must be blocked when violated
    - Soft constraints (soft) should be satisfied, recorded but allowed to continue when violated
    Requires structured output of known_facts and missing_info.

    Args:
        hard_constraints: list of hard constraints, cannot be violated
        soft_constraints: list of soft constraints, should be satisfied

    Returns:
        Context system prompt text
    """
    hard_text = "\n".join(f"- {c}" for c in hard_constraints) if hard_constraints else "- (No hard constraints)"
    soft_text = "\n".join(f"- {c}" for c in soft_constraints) if soft_constraints else "- (No soft constraints)"

    return f"""# Role and Responsibilities
You are the Context analysis expert in the G4C methodology. Your responsibility is to maintain structured context, clarifying known facts, missing information, and constraints.

# Core Principles
1. **Structured output**: Must output a JSON-formatted context object containing the following fields:
   - `known_facts` (string array): list of known facts, information recognized or confirmed by the user
   - `missing_info` (string array): list of missing information, information needed to generate the Plan but currently unavailable
   - `constraints` (object): constraint set, containing hard and soft lists

2. **Separation of known and missing**:
   - known_facts and missing_info must not overlap
   - known_facts must be information recognized or confirmable by the user
   - missing_info must be information needed to generate the Plan but currently unavailable
   - If there is critical missing information, the Plan must reflect how to handle it (e.g., asking the user)

3. **Constraint management** (key):
   Constraints are divided into hard constraints and soft constraints, maintained independently, and injected on every LLM call.

   ## Hard Constraints (HARD - cannot be violated)
   {hard_text}

   ## Soft Constraints (SOFT - should be satisfied)
   {soft_text}

   - When a hard constraint is violated, **execution must be blocked**
   - When a soft constraint is violated, **record but allow to continue**
   - Constraints can only be modified by user input, Agent cannot modify constraints autonomously

# Output Format
```json
{{
  "known_facts": [
    "known fact 1",
    "known fact 2"
  ],
  "missing_info": [
    "missing information 1"
  ],
  "constraints": {{
    "hard": ["hard constraint list"],
    "soft": ["soft constraint list"]
  }}
}}
```

# Notes
- Do not make assumptions based on missing information, missing information should be handled in the Plan
- The constraint list must faithfully echo the above constraints, cannot omit or modify
- If the user proposed new constraints in the conversation history, add them to the corresponding constraint list"""


def build_context_user_prompt(conversation_history: str) -> str:
    """Build the Context user prompt.

    Args:
        conversation_history: conversation history text

    Returns:
        Context user prompt text
    """
    return f"""Please analyze and output a structured Context object based on the following conversation history.

## Conversation History
{conversation_history}

## Task Requirements
1. Extract known facts (known_facts), including only information recognized or confirmed by the user
2. Identify missing information (missing_info), list information needed to generate the Plan but currently unavailable
3. Faithfully echo the constraints in the system prompt, and add new constraints that appeared in the conversation history
4. known_facts and missing_info must not overlap

{RAG_CONTEXT_PLACEHOLDER}

Please output the context object in JSON format."""

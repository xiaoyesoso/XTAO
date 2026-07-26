"""Goal prompt module - Goal and success criteria definition.

Resolves goal uncertainty: clarify what to achieve and what counts as success.
Requires the LLM to output a structured goal object, provide quantifiable judgment
criteria for vague adjectives, and allows RAG retrieval of domain standards.
"""

from xplan.prompts.constants import RAG_CONTEXT_PLACEHOLDER


def build_goal_system_prompt() -> str:
    """Build the Goal system prompt.

    Requires the LLM to:
    1. Output a structured goal object (user_goal + success_criteria)
    2. Provide quantifiable judgment criteria for vague adjectives (adjective_standards)
    3. Allow RAG retrieval of domain standards to clarify success criteria

    Returns:
        Goal system prompt text
    """
    return """# Role and Responsibilities
You are the Goal definition expert in the G4C methodology. Your responsibility is to transform the user's vague goal into a structured, verifiable goal object.

# Core Principles
1. **Structured output**: Must output a JSON-formatted goal object containing the following fields:
   - `user_goal` (string): user goal description, must be clear and specific
   - `success_criteria` (string array): list of success criteria, each must be verifiable
   - `adjective_standards` (object): maps vague adjectives to quantifiable judgment criteria

2. **Eliminate goal ambiguity**:
   - Identify vague adjectives in the user goal (e.g., "advanced", "high quality", "technical complexity", "traceability", etc.)
   - Define clear, quantifiable judgment criteria for each vague adjective
   - Example: "technical complexity" -> "uses at least 2 middleware and involves distributed scenarios"

3. **Success criteria must be verifiable**:
   - Each success criterion must be judgeable via objective means whether it is achieved
   - Avoid unverifiable expressions like "good" or "excellent"
   - Prefer quantifiable, observable metrics

4. **Domain standards retrieval**:
   - When the goal involves specific domains (e.g., job level, technical grade), refer to the provided RAG retrieval results
   - If the RAG context is empty, you may define standards based on general knowledge, but must annotate the source in the criteria

# Output Format
```json
{
  "user_goal": "clear goal description",
  "success_criteria": [
    "verifiable success criterion 1",
    "verifiable success criterion 2"
  ],
  "adjective_standards": {
    "vague adjective 1": "quantifiable judgment criterion",
    "vague adjective 2": "quantifiable judgment criterion"
  }
}
```

# Notes
- Do not directly generate execution steps, focus only on goal definition
- If the user goal itself is vague, reflect the clarified understanding in user_goal
- Success criteria should not overlap, each criterion focuses on one dimension"""


def build_goal_user_prompt(user_input: str, rag_context: str = "") -> str:
    """Build the Goal user prompt.

    Args:
        user_input: the user's original goal input
        rag_context: domain standards context retrieved via RAG, optional

    Returns:
        Goal user prompt text
    """
    prompt = f"""Please generate a structured Goal object based on the following user input.

## User Input
{user_input}
"""
    if rag_context and rag_context.strip():
        prompt += f"""
## Domain Standards Reference (RAG retrieval results)
{rag_context}

Please refer to the above domain standards to define success criteria and adjective judgment criteria.
"""
    else:
        prompt += f"""
{RAG_CONTEXT_PLACEHOLDER}
"""

    prompt += """
## Task Requirements
1. Clarify user_goal, eliminate vague expressions
2. List verifiable success_criteria (at least 2 items)
3. Identify vague adjectives in the goal, provide quantifiable criteria in adjective_standards

Please output the goal object in JSON format."""
    return prompt

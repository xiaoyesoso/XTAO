"""Prompt aggregation module - integrates the five module prompts into a complete system prompt.

Integrates the prompts of Goal/Context/Choice/Checkpoint/Correction modules,
and injects hard constraints and soft constraints into the system prompt.
"""

from xtao.prompts.checkpoint_prompt import build_checkpoint_system_prompt
from xtao.prompts.choice_prompt import build_choice_system_prompt
from xtao.prompts.context_prompt import build_context_system_prompt
from xtao.prompts.correction_prompt import build_correction_system_prompt
from xtao.prompts.goal_prompt import build_goal_system_prompt


def build_full_system_prompt(
    hard_constraints: list[str], soft_constraints: list[str]
) -> str:
    """Integrate the five module prompts to build the complete G4C system prompt.

    Integrates the prompts of Goal, Context, Choice, Checkpoint, and Correction modules,
    and injects hard constraints and soft constraints into the system prompt. Constraints
    are injected on every LLM call to prevent them from being ignored as context grows.

    Args:
        hard_constraints: list of hard constraints, cannot be violated
        soft_constraints: list of soft constraints, should be satisfied

    Returns:
        Complete G4C system prompt text
    """
    hard_text = "\n".join(f"  - {c}" for c in hard_constraints) if hard_constraints else "  - (No hard constraints)"
    soft_text = "\n".join(f"  - {c}" for c in soft_constraints) if soft_constraints else "  - (No soft constraints)"

    # Constraint general rules, injected on every LLM call
    constraint_block = f"""# Constraint Management (Must read on every call)

Constraints are divided into hard constraints and soft constraints, maintained independently.

## Hard Constraints (HARD - cannot be violated, execution must be blocked when violated)
{hard_text}

## Soft Constraints (SOFT - should be satisfied, recorded but allowed to continue when violated)
{soft_text}

## Constraint Rules
1. When a hard constraint is violated, **execution must be blocked**
2. When a soft constraint is violated, **record but allow to continue**
3. Constraints can only be modified by user input, Agent cannot modify constraints autonomously
4. Every constraint modification must be evidenced by user input"""

    # Integrate the five module prompts
    sections = [
        "# G4C Methodology - Agent Plan Mechanism System Prompt",
        "",
        "Plan is not a step list, but a checkable, correctable, executable runtime object.",
        "This prompt integrates the five G4C elements: Goal, Context, Choice, Checkpoint, Correction.",
        "",
        "=" * 60,
        constraint_block,
        "=" * 60,
        "",
        "# Module 1: Goal - Goal and Success Criteria",
        "",
        build_goal_system_prompt(),
        "",
        "=" * 60,
        "",
        "# Module 2: Context - Context and Constraint Management",
        "",
        build_context_system_prompt(hard_constraints, soft_constraints),
        "",
        "=" * 60,
        "",
        "# Module 3: Choice - Path Decision and Steps",
        "",
        build_choice_system_prompt(),
        "",
        "=" * 60,
        "",
        "# Module 4: Checkpoint - Checkpoints and Process Verification",
        "",
        build_checkpoint_system_prompt(),
        "",
        "=" * 60,
        "",
        "# Module 5: Correction - Correction Mechanism and Failure Recovery",
        "",
        build_correction_system_prompt(),
        "",
        "=" * 60,
        "",
        "# Execution Principles",
        "",
        "1. Constraint priority: any output must comply with the above hard constraints",
        "2. Evidence-based: path selection and step design must be based on facts or constraints",
        "3. Checkable: key steps must have checkpoints to ensure process verifiability",
        "4. Correctable: predefined correction rules to ensure failure recoverability",
        "5. Executable: Plan must be an executable runtime object, not a step list",
    ]

    return "\n".join(sections)

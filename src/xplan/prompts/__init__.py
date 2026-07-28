"""G4C prompts module.

Modular prompt design, each module corresponds to one G4C element:
- Goal module: requires clear goals, defines adjective standards, allows RAG retrieval
- Context module: emphasizes constraints, hard/soft constraints injected separately
- Choice module: outputs candidate paths and selection reasons, evidence-based
- Checkpoint module: setting rules (milestones/key artifacts/error-prone steps), granularity control
- Correction module: lists failure scenarios and corresponding correction actions, supports RAG injection
- DAG module: dependency rules, counter-intuitive examples, few-shot examples
- Replan module: controlled correction mechanism, evidence-based judgment and categorized output
- Aggregator: integrates the five module prompts
"""

from xplan.prompts.aggregator import build_full_system_prompt
from xplan.prompts.checkpoint_prompt import (
    build_checkpoint_system_prompt,
    build_checkpoint_user_prompt,
)
from xplan.prompts.choice_prompt import (
    build_choice_system_prompt,
    build_choice_user_prompt,
)
from xplan.prompts.context_prompt import (
    build_context_system_prompt,
    build_context_user_prompt,
)
from xplan.prompts.correction_prompt import (
    build_correction_system_prompt,
    build_correction_user_prompt,
)
from xplan.prompts.dag_prompt import (
    build_dag_system_prompt,
    build_dag_user_prompt,
)
from xplan.prompts.goal_prompt import (
    build_goal_system_prompt,
    build_goal_user_prompt,
)
from xplan.prompts.replan_prompt import (
    build_replan_execute_prompt,
    build_replan_judge_prompt,
    build_replan_system_prompt,
)
from xplan.prompts.tcc_prompt import (
    build_tcc_cancel_system_prompt,
    build_tcc_cancel_user_prompt,
    build_tcc_confirm_system_prompt,
    build_tcc_confirm_user_prompt,
    build_tcc_try_system_prompt,
    build_tcc_try_user_prompt,
)
from xplan.prompts.tao_prompt import (
    build_exit_rules_text,
    build_boundary_rules_text,
    build_tao_observation_system_prompt,
    build_tao_observation_user_prompt,
    build_tao_supervisor_system_prompt,
    build_tao_supervisor_user_prompt,
    build_tao_think_system_prompt,
    build_tao_think_user_prompt,
)
from xplan.prompts.tracing_prompt import (
    build_tracing_system_prompt,
    build_tracing_user_prompt,
)

__all__ = [
    # Goal
    "build_goal_system_prompt",
    "build_goal_user_prompt",
    # Context
    "build_context_system_prompt",
    "build_context_user_prompt",
    # Choice
    "build_choice_system_prompt",
    "build_choice_user_prompt",
    # Checkpoint
    "build_checkpoint_system_prompt",
    "build_checkpoint_user_prompt",
    # Correction
    "build_correction_system_prompt",
    "build_correction_user_prompt",
    # DAG
    "build_dag_system_prompt",
    "build_dag_user_prompt",
    # Aggregator
    "build_full_system_prompt",
    # Replan
    "build_replan_system_prompt",
    "build_replan_judge_prompt",
    "build_replan_execute_prompt",
    # TCC Replan
    "build_tcc_try_system_prompt",
    "build_tcc_try_user_prompt",
    "build_tcc_confirm_system_prompt",
    "build_tcc_confirm_user_prompt",
    "build_tcc_cancel_system_prompt",
    "build_tcc_cancel_user_prompt",
    # Failure backtracking and root cause localization
    "build_tracing_system_prompt",
    "build_tracing_user_prompt",
    # TAO / ReAct
    "build_boundary_rules_text",
    "build_exit_rules_text",
    "build_tao_think_system_prompt",
    "build_tao_think_user_prompt",
    "build_tao_observation_system_prompt",
    "build_tao_observation_user_prompt",
    "build_tao_supervisor_system_prompt",
    "build_tao_supervisor_user_prompt",
]

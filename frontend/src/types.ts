// TypeScript types mirroring the XTAO backend Pydantic models.
// Source of truth: src/xtao/models/*.py

export interface Goal {
  user_goal: string;
  success_criteria: string[];
  adjective_standards: Record<string, string>;
}

export interface Constraints {
  hard: string[];
  soft: string[];
}

export interface Context {
  known_facts: string[];
  missing_info: string[];
  constraints: Constraints;
}

export interface Step {
  id: string;
  objective: string;
  reason: string;
  status: string; // pending | running | done | failed | skipped
}

export interface Choice {
  selected_path: string;
  reason: string;
  candidate_paths: string[];
  steps: Step[];
}

export interface Checkpoint {
  step_id: string;
  checks: string[];
}

export interface CorrectionAction {
  type: string; // retry | replan | clarify | rollback | abort
  retry_granularity?: string | null;
  target_step_id?: string | null;
  message: string;
}

export interface Correction {
  condition: string;
  action: CorrectionAction;
}

export interface Plan {
  goal: Goal;
  context: Context;
  choice: Choice;
  checkpoint: Checkpoint[];
  correction: Correction[];
  mode: string; // linear | dag
  status: string; // draft | ready | running | completed | failed | aborted
  current_step_index: number;
  iteration_count: number;
}

export interface StepExecutionRecord {
  step_id: string;
  step_objective: string;
  status: string; // pending | running | done | failed
  output: string;
  checkpoint_passed: boolean | null;
  checkpoint_results: Record<string, unknown>[];
  correction_applied: string | null;
  failure_traced: boolean;
  root_cause_step_id: string | null;
  backtracking_level: string | null;
  replan_triggered: boolean;
  tao_used: boolean;
  tao_loops: number;
  tao_exit: string | null;
}

export interface OrchestratorResult {
  plan: Plan;
  status: string; // completed | failed | aborted | clarify_needed
  step_records: StepExecutionRecord[];
  replan_count: number;
  iteration_count: number;
  verification_score: number | null;
  verification_passed: boolean | null;
  errors: string[];
  clarify_message: string | null;
}

export interface OrchestratorConfig {
  use_iteration?: boolean;
  max_iterations?: number;
  verify_before_execute?: boolean;
  verification_threshold?: number;
  skip_checkpoint?: boolean;
  enable_failure_tracing?: boolean;
  enable_trust_state?: boolean;
  enable_progressive_backtracking?: boolean;
  enable_tcc_replan?: boolean;
  max_replan_count?: number;
  use_tao?: boolean;
  tao_max_loops?: number;
  tao_max_time?: number;
  tao_supervisor_interval?: number;
  tao_supervisor_interval_seconds?: number;
}

"""G4C data model definitions.

Contains the Plan composite object and its five elements:
- Goal: goal and success criteria
- Context: context and constraints
- Choice: path decision and steps
- Checkpoint: checkpoint and process verification
- Correction: correction mechanism and failure recovery
"""

from xtao.models.plan import Plan, PlanMode, PlanStatus
from xtao.models.goal import Goal
from xtao.models.context import Context, Constraints
from xtao.models.choice import Choice, Step
from xtao.models.checkpoint import Checkpoint, CheckResult, CheckEvidence
from xtao.models.correction import Correction, CorrectionAction, CorrectionType
from xtao.models.dag import DAGNode, DAGEdge, DAGPlan
from xtao.models.replan import (
    ReplanGranularity,
    ReplanInfo,
    ReplanJudgment,
    ReplanResult,
    ReplanTrigger,
    StepChange,
)
from xtao.models.replan_evaluation import (
    OscillationDetector,
    ReplanEvent,
    ReplanMetrics,
)
from xtao.models.tcc import (
    CancelResult,
    ConfirmResult,
    TCCPhase,
    TCCResult,
    TryResult,
    TryValidation,
    TryValidationType,
)
from xtao.models.backtracking import (
    BacktrackingLevel,
    BacktrackingResult,
    CandidatePath,
    CrossTurnContamination,
    DecisionNode,
    FailurePathRecord,
    JumpRule,
)
from xtao.models.tracing import (
    FailureTracingResult,
    StepRecord,
    TracingPoint,
)
from xtao.models.trust_state import (
    FactEntry,
    TrustState,
    TrustStateChange,
    TrustStateReport,
)
from xtao.models.orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    StepExecutionRecord,
)
from xtao.models.tao import (
    ActionAvailability,
    ActionCandidate,
    ActionFilterRule,
    ActionRecord,
    ActionStatus,
    ActionType,
    ControlState,
    ExecutionStatus,
    FactCategory,
    FactItem,
    GoalState,
    InformationGain,
    InterventionType,
    Observation,
    ObservationFact,
    RiskLevel,
    SupervisorReview,
    TAOExit,
    TAOExitRecord,
    TAOResult,
    TAOState,
    ThinkResult,
)
from xtao.models.tao_evaluation import (
    ActionMetrics,
    ActionRoundEvaluation,
    GoldenAnswer,
    JudgeSource,
    LLMJudgeRequest,
    LLMJudgeResult,
    ObservationMetrics,
    ObservationRoundEvaluation,
    OverallMetrics,
    TAOEvaluationEvent,
    TAOEvaluationMetrics,
    TAOEvaluationReport,
    TAOEvaluationSuggestion,
    ThinkMetrics,
    ThinkRoundEvaluation,
)

__all__ = [
    "Plan",
    "PlanMode",
    "PlanStatus",
    "Goal",
    "Context",
    "Constraints",
    "Choice",
    "Step",
    "Checkpoint",
    "CheckResult",
    "CheckEvidence",
    "Correction",
    "CorrectionAction",
    "CorrectionType",
    "DAGNode",
    "DAGEdge",
    "DAGPlan",
    # Replan
    "ReplanGranularity",
    "ReplanInfo",
    "ReplanJudgment",
    "ReplanResult",
    "ReplanTrigger",
    "StepChange",
    # TCC Replan
    "TCCPhase",
    "TryValidationType",
    "TryValidation",
    "TryResult",
    "ConfirmResult",
    "CancelResult",
    "TCCResult",
    # Replan evaluation
    "OscillationDetector",
    "ReplanEvent",
    "ReplanMetrics",
    # Backtracking
    "BacktrackingLevel",
    "BacktrackingResult",
    "CandidatePath",
    "CrossTurnContamination",
    "DecisionNode",
    "FailurePathRecord",
    "JumpRule",
    # Tracing
    "FailureTracingResult",
    "StepRecord",
    "TracingPoint",
    # TrustState
    "FactEntry",
    "TrustState",
    "TrustStateChange",
    "TrustStateReport",
    # Orchestrator
    "OrchestratorConfig",
    "OrchestratorResult",
    "StepExecutionRecord",
    # TAO / ReAct
    "ActionAvailability",
    "ActionCandidate",
    "ActionFilterRule",
    "ActionRecord",
    "ActionStatus",
    "ActionType",
    "ControlState",
    "ExecutionStatus",
    "FactCategory",
    "FactItem",
    "GoalState",
    "InformationGain",
    "InterventionType",
    "Observation",
    "ObservationFact",
    "RiskLevel",
    "SupervisorReview",
    "TAOExit",
    "TAOExitRecord",
    "TAOResult",
    "TAOState",
    "ThinkResult",
    # TAO evaluation
    "ActionMetrics",
    "ActionRoundEvaluation",
    "GoldenAnswer",
    "JudgeSource",
    "LLMJudgeRequest",
    "LLMJudgeResult",
    "ObservationMetrics",
    "ObservationRoundEvaluation",
    "OverallMetrics",
    "TAOEvaluationEvent",
    "TAOEvaluationMetrics",
    "TAOEvaluationReport",
    "TAOEvaluationSuggestion",
    "ThinkMetrics",
    "ThinkRoundEvaluation",
]

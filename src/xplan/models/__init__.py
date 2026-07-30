"""G4C data model definitions.

Contains the Plan composite object and its five elements:
- Goal: goal and success criteria
- Context: context and constraints
- Choice: path decision and steps
- Checkpoint: checkpoint and process verification
- Correction: correction mechanism and failure recovery
"""

from xplan.models.plan import Plan, PlanMode, PlanStatus
from xplan.models.goal import Goal
from xplan.models.context import Context, Constraints
from xplan.models.choice import Choice, Step
from xplan.models.checkpoint import Checkpoint, CheckResult, CheckEvidence
from xplan.models.correction import Correction, CorrectionAction, CorrectionType
from xplan.models.dag import DAGNode, DAGEdge, DAGPlan
from xplan.models.replan import (
    ReplanGranularity,
    ReplanInfo,
    ReplanJudgment,
    ReplanResult,
    ReplanTrigger,
    StepChange,
)
from xplan.models.replan_evaluation import (
    OscillationDetector,
    ReplanEvent,
    ReplanMetrics,
)
from xplan.models.tcc import (
    CancelResult,
    ConfirmResult,
    TCCPhase,
    TCCResult,
    TryResult,
    TryValidation,
    TryValidationType,
)
from xplan.models.backtracking import (
    BacktrackingLevel,
    BacktrackingResult,
    CandidatePath,
    CrossTurnContamination,
    DecisionNode,
    FailurePathRecord,
    JumpRule,
)
from xplan.models.tracing import (
    FailureTracingResult,
    StepRecord,
    TracingPoint,
)
from xplan.models.trust_state import (
    FactEntry,
    TrustState,
    TrustStateChange,
    TrustStateReport,
)
from xplan.models.orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
    StepExecutionRecord,
)
from xplan.models.tao import (
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
from xplan.models.tao_evaluation import (
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

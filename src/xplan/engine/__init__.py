"""Engine layer - G4C Plan generation, evaluation, execution, and correction.

The engine layer provides full lifecycle management of Plan based on the G4C data model:
- PlanGenerator: Generate complete Plan (Goal/Context/Choice/Checkpoint/Correction)
- PlanVerifier: Evaluate Plan quality across G4C five dimensions
- PlanExecutor: Execute Plan step by step, run checkpoints and trigger corrections
- CorrectionHandler: Five correction strategies (RETRY/REPLAN/CLARIFY/ROLLBACK/ABORT)
- DAGValidator: DAG structure validation and topological analysis
- IterationLoop: Generate-evaluate-correct iteration loop
- BacktrackingEngine: Five backtracking levels and progressive expansion strategy
- CrossTurnTracker: Cross-turn error fact contamination tracking
- FailureTracer: Failure backtracking and root cause localization
"""

from xplan.engine.backtracking_engine import BacktrackingEngine
from xplan.engine.correction_handler import CorrectionHandler
from xplan.engine.cross_turn_tracker import CrossTurnTracker
from xplan.engine.dag_validator import DAGValidator
from xplan.engine.failure_tracer import FailureTracer
from xplan.engine.iteration_loop import IterationLoop
from xplan.engine.plan_executor import PlanExecutor
from xplan.engine.plan_generator import PlanGenerator
from xplan.engine.plan_verifier import (
    PlanVerificationResult,
    PlanVerifier,
)
from xplan.engine.replan_engine import ReplanEngine
from xplan.engine.tcc_replan import TCCReplan
from xplan.engine.orchestrator import PlanOrchestrator
from xplan.engine.tao_action_runtime import TAOActionRuntime
from xplan.engine.tao_engine import TAOEngine
from xplan.engine.tao_loop_controller import TAOLoopController
from xplan.engine.tao_observation_interpreter import TAOObservationInterpreter
from xplan.engine.tao_think_engine import TAOThinkEngine

__all__ = [
    "PlanGenerator",
    "PlanVerifier",
    "PlanVerificationResult",
    "PlanExecutor",
    "CorrectionHandler",
    "DAGValidator",
    "IterationLoop",
    "ReplanEngine",
    "TCCReplan",
    "BacktrackingEngine",
    "CrossTurnTracker",
    "FailureTracer",
    "PlanOrchestrator",
    # TAO / ReAct
    "TAOEngine",
    "TAOThinkEngine",
    "TAOActionRuntime",
    "TAOObservationInterpreter",
    "TAOLoopController",
]

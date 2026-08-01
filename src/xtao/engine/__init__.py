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

from xtao.engine.backtracking_engine import BacktrackingEngine
from xtao.engine.correction_handler import CorrectionHandler
from xtao.engine.cross_turn_tracker import CrossTurnTracker
from xtao.engine.dag_validator import DAGValidator
from xtao.engine.failure_tracer import FailureTracer
from xtao.engine.iteration_loop import IterationLoop
from xtao.engine.plan_executor import PlanExecutor
from xtao.engine.plan_generator import PlanGenerator
from xtao.engine.plan_verifier import (
    PlanVerificationResult,
    PlanVerifier,
)
from xtao.engine.replan_engine import ReplanEngine
from xtao.engine.tcc_replan import TCCReplan
from xtao.engine.orchestrator import PlanOrchestrator
from xtao.engine.tao_action_runtime import TAOActionRuntime
from xtao.engine.tao_engine import TAOEngine
from xtao.engine.tao_loop_controller import TAOLoopController
from xtao.engine.tao_observation_interpreter import TAOObservationInterpreter
from xtao.engine.tao_think_engine import TAOThinkEngine

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

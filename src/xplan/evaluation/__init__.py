"""Plan quality evaluation system - Offline + online dual-track.

Includes two levels of evaluation:
- Online monitoring (PlanMetrics): Real-time collection of Plan execution quality via Prometheus metrics
- Offline analysis (OfflineAnalyzer): Structured quality evaluation of Plan around G4C five dimensions
- User correction detection (UserCorrectionDetector): Detects whether user input is corrective expression
- Replan effect evaluation (ReplanEvaluator): Evaluates five core metrics of the Replan mechanism
"""

from xplan.evaluation.metrics import PlanMetrics
from xplan.evaluation.offline_analyzer import OfflineAnalysisResult, OfflineAnalyzer
from xplan.evaluation.replan_evaluator import ReplanEvaluator
from xplan.evaluation.user_correction_detector import UserCorrectionDetector

__all__ = [
    "PlanMetrics",
    "OfflineAnalysisResult",
    "OfflineAnalyzer",
    "UserCorrectionDetector",
    "ReplanEvaluator",
]

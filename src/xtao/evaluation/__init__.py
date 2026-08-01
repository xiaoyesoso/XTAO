"""Plan quality evaluation system - Offline + online dual-track.

Includes two levels of evaluation:
- Online monitoring (PlanMetrics): Real-time collection of Plan execution quality via Prometheus metrics
- Offline analysis (OfflineAnalyzer): Structured quality evaluation of Plan around G4C five dimensions
- User correction detection (UserCorrectionDetector): Detects whether user input is corrective expression
- Replan effect evaluation (ReplanEvaluator): Evaluates five core metrics of the Replan mechanism
"""

from xtao.evaluation.metrics import PlanMetrics
from xtao.evaluation.offline_analyzer import OfflineAnalysisResult, OfflineAnalyzer
from xtao.evaluation.replan_evaluator import ReplanEvaluator
from xtao.evaluation.user_correction_detector import UserCorrectionDetector
from xtao.evaluation.tao_evaluator import TAOEvaluator

__all__ = [
    "PlanMetrics",
    "OfflineAnalysisResult",
    "OfflineAnalyzer",
    "UserCorrectionDetector",
    "ReplanEvaluator",
    "TAOEvaluator",
]

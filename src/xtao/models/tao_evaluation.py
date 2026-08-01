"""TAO evaluation models - metrics, events, reports and annotations.

Provides structured data objects for the TAO quality evaluation system:
- Per-round evaluation events capturing Think / Action / Observation outputs
- Aggregated metrics across Think / Action / Observation / overall layers
- LLM-as-judge requests and human annotation (golden answer) comparisons
- Evaluation reports with trend analysis and optimization suggestions
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JudgeSource(str, Enum):
    """Source of an evaluation judgment."""

    CODE = "code"
    LLM = "llm"
    HUMAN = "human"


class ThinkRoundEvaluation(BaseModel):
    """Evaluation data for a single Think round."""

    round_index: int = Field(description="TAO inner loop round index")
    current_goal: str = Field(default="", description="Goal declared by Think")
    selected_action: str = Field(default="", description="Selected action name")
    action_params: dict[str, Any] = Field(default_factory=dict, description="Selected action params")
    exit_decision: str = Field(default="", description="Exit decision proposed by Think")
    missing_slots: list[str] = Field(default_factory=list, description="Missing slots identified")
    risk_level: str = Field(default="low", description="Risk level assigned")
    reason: str = Field(default="", description="Reasoning provided by Think")
    duration_ms: int = Field(default=0, description="Think latency in milliseconds")
    token_usage: dict[str, int] = Field(
        default_factory=dict, description="Token usage per model"
    )


class ActionRoundEvaluation(BaseModel):
    """Evaluation data for a single Action execution."""

    round_index: int = Field(description="TAO inner loop round index")
    action_id: str = Field(default="", description="Action record ID")
    action_name: str = Field(default="", description="Action name")
    tool_name: str = Field(default="", description="Underlying tool name")
    status: str = Field(default="", description="Execution status")
    duration_ms: int = Field(default=0, description="Execution latency in milliseconds")
    error: str = Field(default="", description="Error message when failed")


class ObservationRoundEvaluation(BaseModel):
    """Evaluation data for a single Observation interpretation."""

    round_index: int = Field(description="TAO inner loop round index")
    observation_id: str = Field(default="", description="Observation record ID")
    execution_status: str = Field(default="", description="Interpreted execution status")
    new_facts: list[dict[str, Any]] = Field(default_factory=list, description="Extracted facts")
    missing_information: list[str] = Field(default_factory=list, description="Missing info after observation")
    anomalies: list[str] = Field(default_factory=list, description="Detected anomalies")
    progress: bool = Field(default=False, description="Whether progress was reported")
    information_gain: str = Field(default="low", description="Information gain level")
    summary: str = Field(default="", description="Observation summary")
    duration_ms: int = Field(default=0, description="Observation latency in milliseconds")
    token_usage: dict[str, int] = Field(
        default_factory=dict, description="Token usage per model"
    )


class TAOEvaluationEvent(BaseModel):
    """Complete evaluation event for one TAO run."""

    event_id: str = Field(default_factory=lambda: f"tao-eval-{uuid4().hex[:8]}")
    task_id: str = Field(default="", description="Task or scenario identifier")
    user_input: str = Field(default="", description="Original user input")
    final_exit: str = Field(default="", description="Final TAO exit type")
    used_loops: int = Field(default=0, description="Total inner loop rounds")
    total_actions: int = Field(default=0, description="Total actions executed")
    success: bool = Field(default=False, description="Whether the task succeeded")
    duration_ms: int = Field(default=0, description="Total task latency in milliseconds")
    think_rounds: list[ThinkRoundEvaluation] = Field(default_factory=list)
    action_rounds: list[ActionRoundEvaluation] = Field(default_factory=list)
    observation_rounds: list[ObservationRoundEvaluation] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(
        default_factory=dict, description="Total token usage per model"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GoldenAnswer(BaseModel):
    """Human-annotated golden answer for a TAO evaluation event."""

    event_id: str = Field(description="Event this annotation belongs to")
    optimal_action: str | None = Field(default=None, description="Expected optimal action")
    optimal_params: dict[str, Any] | None = Field(default=None, description="Expected optimal action params")
    expected_facts: list[dict[str, Any]] = Field(default_factory=list, description="Expected extracted facts")
    expected_missing_slots: list[str] = Field(default_factory=list, description="Expected missing slots")
    should_stop: bool | None = Field(default=None, description="Whether the loop should stop")
    task_success: bool | None = Field(default=None, description="Whether the final task succeeded")
    notes: str = Field(default="", description="Annotator notes")


class ThinkMetrics(BaseModel):
    """Aggregated Think-phase metrics."""

    action_selection_accuracy: float = Field(default=0.0)
    action_param_accuracy: float = Field(default=0.0)
    goal_judgment_accuracy: float = Field(default=0.0)
    missing_slot_accuracy: float = Field(default=0.0)
    constraint_violation_rate: float = Field(default=0.0)
    stop_judgment_accuracy: float = Field(default=0.0)
    sample_count: int = Field(default=0)


class ActionMetrics(BaseModel):
    """Aggregated Action execution metrics."""

    success_rate: float = Field(default=0.0)
    average_response_time_ms: float = Field(default=0.0)
    p95_response_time_ms: float = Field(default=0.0)
    failure_count: int = Field(default=0)
    success_count: int = Field(default=0)
    sample_count: int = Field(default=0)
    by_tool: dict[str, dict[str, float]] = Field(default_factory=dict)


class ObservationMetrics(BaseModel):
    """Aggregated Observation interpretation metrics."""

    fact_extraction_precision: float = Field(default=0.0)
    fact_extraction_recall: float = Field(default=0.0)
    fact_extraction_f1: float = Field(default=0.0)
    evidence_binding_accuracy: float = Field(default=0.0)
    misread_rate: float = Field(default=0.0)
    anomaly_detection_accuracy: float = Field(default=0.0)
    missing_info_update_accuracy: float = Field(default=0.0)
    sample_count: int = Field(default=0)


class OverallMetrics(BaseModel):
    """Aggregated overall TAO task metrics."""

    task_success_rate: float = Field(default=0.0)
    average_loops: float = Field(default=0.0)
    average_actions: float = Field(default=0.0)
    average_tokens: float = Field(default=0.0)
    average_duration_ms: float = Field(default=0.0)
    sample_count: int = Field(default=0)


class TAOEvaluationMetrics(BaseModel):
    """Complete aggregated TAO evaluation metrics."""

    think: ThinkMetrics = Field(default_factory=ThinkMetrics)
    action: ActionMetrics = Field(default_factory=ActionMetrics)
    observation: ObservationMetrics = Field(default_factory=ObservationMetrics)
    overall: OverallMetrics = Field(default_factory=OverallMetrics)


class TAOEvaluationSuggestion(BaseModel):
    """A single optimization suggestion derived from metrics."""

    category: str = Field(description="Category: think/action/observation/overall")
    metric: str = Field(description="Metric name")
    value: float = Field(description="Current metric value")
    threshold: float = Field(description="Threshold used for comparison")
    suggestion: str = Field(description="Concrete optimization suggestion")


class TAOEvaluationReport(BaseModel):
    """Structured TAO evaluation report."""

    metrics: TAOEvaluationMetrics = Field(default_factory=TAOEvaluationMetrics)
    suggestions: list[TAOEvaluationSuggestion] = Field(default_factory=list)
    abnormal_samples: list[str] = Field(
        default_factory=list, description="Event IDs of abnormal samples"
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str = Field(default="", description="Natural-language summary")


class LLMJudgeRequest(BaseModel):
    """Request for LLM-as-Judge evaluation of a single TAO round."""

    event_id: str | None = Field(default=None)
    round_index: int = Field(default=0)
    user_input: str = Field(default="")
    context_summary: str = Field(default="")
    think_output: ThinkRoundEvaluation | None = Field(default=None)
    action_output: ActionRoundEvaluation | None = Field(default=None)
    observation_output: ObservationRoundEvaluation | None = Field(default=None)
    golden: GoldenAnswer | None = Field(default=None)


class LLMJudgeResult(BaseModel):
    """Result of an LLM-as-Judge evaluation."""

    event_id: str | None = Field(default=None)
    round_index: int = Field(default=0)
    source: JudgeSource = Field(default=JudgeSource.LLM)
    scores: dict[str, float] = Field(default_factory=dict)
    reasoning: str = Field(default="")

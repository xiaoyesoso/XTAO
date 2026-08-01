"""Offline analysis pipeline - Evaluates Plan quality around G4C five dimensions.

Offline analysis focuses on the structural quality of Plan, evaluated around the five G4C dimensions:
- Goal: Goal clarity (success_criteria, vague adjectives)
- Context: Constraint violation detection (especially hard constraints)
- Choice: Path selection rationality (evidence-based reason)
- Checkpoint: Checkpoint sufficiency (reference standard: about 1/3 of step count)
- Correction: Correction completeness (covers common failure scenarios)

Production environment supports analysis by sampling ratio to control resource consumption.
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, Field

from xtao.models.correction import CorrectionType
from xtao.models.plan import Plan


# Vague adjective list, used to detect Goal clarity
_VAGUE_ADJECTIVES: list[str] = [
    "好的", "高质量", "快速", "高效", "合理", "适当", "一些", "一定",
    "比较好", "尽量", "大概", "可能", "差不多", "优秀", "完美", "简单",
    "nice", "good", "fast", "high quality", "reasonable", "proper",
    "some", "certain", "better", "appropriate", "simple", "quick",
    "efficient", "effective",
]

# Common failure scenario keywords, used to check Correction completeness
_COMMON_FAILURE_SCENES: list[str] = [
    "失败", "错误", "超时", "异常", "不通过", "未通过",
    "fail", "error", "timeout", "exception",
]


class OfflineAnalysisResult(BaseModel):
    """Offline analysis result.

    The output of structured quality evaluation of Plan around G4C five dimensions.
    """

    plan_id: str | None = Field(
        default=None,
        description="Plan ID, None when Plan model has no id field",
    )
    score: float = Field(
        default=0.0,
        description="Overall score, between 0-1, higher indicates better Plan quality",
    )
    constraint_violations: list[str] = Field(
        default_factory=list,
        description="Constraint violation list, each item describes one violation",
    )
    checkpoint_issues: list[str] = Field(
        default_factory=list,
        description="Checkpoint issue list",
    )
    goal_issues: list[str] = Field(
        default_factory=list,
        description="Goal issue list",
    )
    choice_issues: list[str] = Field(
        default_factory=list,
        description="Path selection issue list",
    )
    correction_issues: list[str] = Field(
        default_factory=list,
        description="Correction issue list",
    )
    checkpoint_sufficient: bool = Field(
        default=True,
        description="Whether checkpoints are sufficient",
    )
    overall_assessment: str = Field(
        default="",
        description="Overall assessment description",
    )


class OfflineAnalyzer:
    """Offline Plan analyzer.

    Performs structured quality evaluation of Plan around G4C five dimensions,
    supports LLM-assisted analysis.

    Usage:
        analyzer = OfflineAnalyzer()
        result = await analyzer.analyze(plan)

    Production sampling analysis:
        results = await analyzer.analyze_with_sampling(plans, sample_ratio=0.1)
    """

    def __init__(self, llm_service: Any = None):
        """Initialize offline analyzer.

        Args:
            llm_service: Optional LLM service for assisted analysis. Type is Any,
                         injected externally with concrete implementation, must support async calls.
        """
        self.llm_service = llm_service

    async def analyze(self, plan: Plan) -> OfflineAnalysisResult:
        """Evaluate Plan around G4C five dimensions.

        Performs the following checks:
        1. Constraint violation detection (hard constraints first)
        2. Checkpoint sufficiency assessment (reference standard: about 1/3 of step count)
        3. Goal clarity assessment (success_criteria, vague adjectives)
        4. Choice path selection rationality assessment (evidence-based reason)
        5. Correction completeness assessment (covers common failure scenarios)

        Args:
            plan: Plan object to analyze

        Returns:
            Offline analysis result
        """
        # Perform various checks
        constraint_violations = self.check_constraint_violations(plan)
        checkpoint_sufficient, checkpoint_note = self.check_checkpoint_sufficiency(plan)
        goal_issues = self.check_goal_clarity(plan)
        choice_issues = self.check_choice_rationale(plan)
        correction_issues = self.check_correction_completeness(plan)

        # Aggregate checkpoint issues
        checkpoint_issues: list[str] = []
        if not checkpoint_sufficient:
            checkpoint_issues.append(checkpoint_note)

        # Calculate overall score
        score = self._calculate_score(
            constraint_violations=constraint_violations,
            checkpoint_sufficient=checkpoint_sufficient,
            goal_issues=goal_issues,
            choice_issues=choice_issues,
            correction_issues=correction_issues,
        )

        # Build overall assessment description
        overall_assessment = self._build_overall_assessment(
            score=score,
            constraint_violations=constraint_violations,
            checkpoint_sufficient=checkpoint_sufficient,
            goal_issues=goal_issues,
            choice_issues=choice_issues,
            correction_issues=correction_issues,
        )

        return OfflineAnalysisResult(
            plan_id=None,  # Plan model currently has no id field
            score=score,
            constraint_violations=constraint_violations,
            checkpoint_issues=checkpoint_issues,
            goal_issues=goal_issues,
            choice_issues=choice_issues,
            correction_issues=correction_issues,
            checkpoint_sufficient=checkpoint_sufficient,
            overall_assessment=overall_assessment,
        )

    def _calculate_score(
        self,
        constraint_violations: list[str],
        checkpoint_sufficient: bool,
        goal_issues: list[str],
        choice_issues: list[str],
        correction_issues: list[str],
    ) -> float:
        """Calculate overall score.

        Scoring strategy: Start from 1.0, deduct points by issue severity, minimum 0.0.
        Constraint violations have the highest weight (hard constraints cannot be violated),
        followed by insufficient checkpoints.

        Args:
            constraint_violations: Constraint violation list
            checkpoint_sufficient: Whether checkpoints are sufficient
            goal_issues: Goal issue list
            choice_issues: Path selection issue list
            correction_issues: Correction issue list

        Returns:
            Overall score (0-1)
        """
        score = 1.0
        # Deduct for constraint violations (highest weight, 0.15 each)
        score -= len(constraint_violations) * 0.15
        # Deduct 0.15 for insufficient checkpoints
        if not checkpoint_sufficient:
            score -= 0.15
        # Deduct for goal issues (0.1 each)
        score -= len(goal_issues) * 0.1
        # Deduct for path selection issues (0.1 each)
        score -= len(choice_issues) * 0.1
        # Deduct for correction issues (0.1 each)
        score -= len(correction_issues) * 0.1
        return max(score, 0.0)

    def _build_overall_assessment(
        self,
        score: float,
        constraint_violations: list[str],
        checkpoint_sufficient: bool,
        goal_issues: list[str],
        choice_issues: list[str],
        correction_issues: list[str],
    ) -> str:
        """Build overall assessment description.

        Args:
            score: Overall score
            constraint_violations: Constraint violation list
            checkpoint_sufficient: Whether checkpoints are sufficient
            goal_issues: Goal issue list
            choice_issues: Path selection issue list
            correction_issues: Correction issue list

        Returns:
            Overall assessment description text
        """
        parts: list[str] = []
        parts.append(f"Overall score: {score:.2f}")

        if constraint_violations:
            parts.append(f"Found {len(constraint_violations)} constraint violation(s), should be addressed first")
        else:
            parts.append("No constraint violations detected")

        if checkpoint_sufficient:
            parts.append("Checkpoints are sufficient")
        else:
            parts.append("Checkpoint count is insufficient")

        if goal_issues:
            parts.append(f"Goal definition has {len(goal_issues)} issue(s)")
        else:
            parts.append("Goal definition is clear")

        if choice_issues:
            parts.append(f"Path selection has {len(choice_issues)} issue(s)")
        else:
            parts.append("Path selection is reasonable")

        if correction_issues:
            parts.append(f"Correction mechanism has {len(correction_issues)} issue(s)")
        else:
            parts.append("Correction mechanism is complete")

        return "; ".join(parts) + "."

    def check_constraint_violations(self, plan: Plan) -> list[str]:
        """Detect whether Plan violates constraints.

        Checks whether paths and steps in Choice may violate hard constraints.
        Uses heuristic method: identifies negation forms in hard constraints (e.g. "不要X"),
        if the path or step description contains the negated content, it is considered a possible violation.

        Args:
            plan: Plan to check

        Returns:
            Violation description list, each item describes one violation
        """
        violations: list[str] = []
        hard_constraints = plan.context.constraints.hard
        if not hard_constraints:
            return violations

        # Check whether Choice's selected_path violates hard constraints
        selected_path = plan.choice.selected_path
        for constraint in hard_constraints:
            if self._text_violates_constraint(selected_path, constraint):
                violations.append(
                    f"Choice.selected_path may violate hard constraint: {constraint}"
                )

        # Check whether any step descriptions violate hard constraints
        for step in plan.choice.steps:
            step_text = f"{step.objective} {step.reason}"
            for constraint in hard_constraints:
                if self._text_violates_constraint(step_text, constraint):
                    violations.append(
                        f"Step '{step.id}' may violate hard constraint: {constraint}"
                    )

        return violations

    @staticmethod
    def _text_violates_constraint(text: str, constraint: str) -> bool:
        """Determine whether text may violate a constraint.

        Based on negation word detection: if the constraint is in negation form
        like "不要X / 不能X / 禁止X", and the text contains the negated content X,
        it is considered a possible violation.

        Args:
            text: Text to check
            constraint: Constraint description

        Returns:
            Whether a violation is possible
        """
        text_lower = text.lower()
        constraint_lower = constraint.lower()

        # Negation prefix list (Chinese and English)
        negation_prefixes = [
            "不要", "不能", "禁止", "不得", "避免", "切勿", "绝不可",
            "don't ", "do not ", "must not ", "never ", "no ", "avoid ",
            "forbidden ",
        ]

        for prefix in negation_prefixes:
            if constraint_lower.startswith(prefix):
                # Extract content after negation
                forbidden_content = constraint_lower[len(prefix):].strip()
                # Remove common punctuation
                forbidden_content = forbidden_content.strip("，。.,；;")
                if not forbidden_content:
                    continue
                # Remove common verb prefixes to extract core forbidden content
                # e.g. "do not use plaintext to store passwords" -> core content "plaintext to store passwords"
                for verb_prefix in [
                    "使用", "用", "进行", "做", "采用", "通过",
                    "to ", "use ", "using ", "do ", "via ",
                ]:
                    if forbidden_content.startswith(verb_prefix):
                        forbidden_content = forbidden_content[len(verb_prefix):].strip()
                        break
                if forbidden_content and forbidden_content in text_lower:
                    return True
        return False

    def check_checkpoint_sufficiency(self, plan: Plan) -> tuple[bool, str]:
        """Assess checkpoint sufficiency.

        Reference standard: Checkpoint count should be >= 1/3 of step count.
        Checkpoint setting three rules: at milestones, at key intermediate outputs, after error-prone steps.

        Args:
            plan: Plan to check

        Returns:
            (whether sufficient, description)
        """
        step_count = len(plan.choice.steps)
        checkpoint_count = len(plan.checkpoint)

        if step_count == 0:
            return True, "No steps, no checkpoints needed"

        # Reference standard: checkpoint count about 1/3 of step count, at least 1
        expected_min = max(1, step_count // 3)

        if checkpoint_count >= expected_min:
            return True, (
                f"Checkpoint count sufficient: {checkpoint_count} checkpoints / {step_count} steps"
                f" (reference standard: >= {expected_min})"
            )
        else:
            return False, (
                f"Checkpoint count insufficient: {checkpoint_count} checkpoints / {step_count} steps"
                f" (reference standard: >= {expected_min})"
            )

    def check_goal_clarity(self, plan: Plan) -> list[str]:
        """Check goal clarity.

        Checks whether success_criteria is empty, and whether user_goal contains
        vague adjectives that are not defined in adjective_standards with quantitative criteria.

        Args:
            plan: Plan to check

        Returns:
            Issue list
        """
        issues: list[str] = []
        goal = plan.goal

        # Check whether success_criteria is empty
        if not goal.success_criteria:
            issues.append("Goal.success_criteria is empty, missing verifiable success criteria")

        # Check whether user_goal has vague adjectives without quantitative standards defined
        user_goal_lower = goal.user_goal.lower()
        for adjective in _VAGUE_ADJECTIVES:
            if adjective.lower() in user_goal_lower:
                if adjective not in goal.adjective_standards:
                    issues.append(
                        f"Goal.user_goal contains vague adjective '{adjective}', "
                        f"but no quantitative standard defined in adjective_standards"
                    )

        return issues

    def check_choice_rationale(self, plan: Plan) -> list[str]:
        """Check path selection rationality.

        Checks whether Choice.reason is empty (must be evidence-based),
        whether each step has a reason, and whether candidate paths are provided for comparison.

        Args:
            plan: Plan to check

        Returns:
            Issue list
        """
        issues: list[str] = []
        choice = plan.choice

        # Check Choice's overall reason
        if not choice.reason.strip():
            issues.append("Choice.reason is empty, missing evidence-based path selection reason")

        # Check whether each step has a reason
        for step in choice.steps:
            if not step.reason.strip():
                issues.append(
                    f"Step '{step.id}' missing reason, cannot trace why the step exists"
                )

        # Check whether candidate_paths is empty (path selection lacks comparison)
        if not choice.candidate_paths:
            issues.append("Choice.candidate_paths is empty, no candidate paths provided for comparison")

        return issues

    def check_correction_completeness(self, plan: Plan) -> list[str]:
        """Check correction completeness.

        Checks whether there are correction rules, whether they cover common failure scenarios,
        and whether they include RETRY type basic correction strategy.

        Args:
            plan: Plan to check

        Returns:
            Issue list
        """
        issues: list[str] = []
        corrections = plan.correction

        # Check whether there are correction rules
        if not corrections:
            issues.append("Correction list is empty, missing correction rules, cannot handle execution deviations")
            return issues

        # Check whether common failure scenarios are covered
        # Reasonable standard: correction rules should cover at least one common failure scenario, not all
        covered_scenes: set[str] = set()
        for correction in corrections:
            condition_lower = correction.condition.lower()
            for scene in _COMMON_FAILURE_SCENES:
                if scene in condition_lower:
                    covered_scenes.add(scene)

        if not covered_scenes:
            issues.append(
                "Correction does not cover any common failure scenarios"
                f" (reference keywords: {', '.join(_COMMON_FAILURE_SCENES)})"
            )

        # Check whether RETRY type correction is included (the most basic correction strategy)
        has_retry = any(
            c.action.type == CorrectionType.RETRY for c in corrections
        )
        if not has_retry:
            issues.append(
                "Correction missing RETRY type correction, cannot handle retryable failure scenarios"
            )

        return issues

    async def analyze_with_sampling(
        self, plans: list[Plan], sample_ratio: float = 0.1
    ) -> list[OfflineAnalysisResult]:
        """Production environment sampling analysis.

        Randomly samples plans by sample_ratio, analyzes each sampled plan individually.
        Used to control the scale of offline analysis in resource-constrained production environments.

        Args:
            plans: List of Plans to analyze
            sample_ratio: Sampling ratio, between 0-1, default 0.1 (10%)

        Returns:
            List of analysis results for sampled Plans
        """
        if not plans:
            return []

        # Limit sample_ratio range
        ratio = max(0.0, min(1.0, sample_ratio))
        if ratio == 0.0:
            return []

        # Calculate sample size, at least 1
        sample_size = max(1, int(len(plans) * ratio))
        sample_size = min(sample_size, len(plans))

        # Random sampling
        sampled_plans = random.sample(plans, sample_size)

        # Analyze one by one
        results: list[OfflineAnalysisResult] = []
        for plan in sampled_plans:
            result = await self.analyze(plan)
            results.append(result)

        return results

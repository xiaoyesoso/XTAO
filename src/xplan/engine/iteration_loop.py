"""Iterative generation loop - Generate-evaluate-correct loop.

Introduces a "generate-evaluate-correct" loop during Plan generation.
Plan Verifier evaluates across G4C five dimensions; stops if passing, regenerates if not.
Sets a maximum iteration count limit; monitors average iteration count as a signal of Plan generation quality.
"""

from typing import Any

from xplan.models import Plan
from xplan.engine.plan_generator import PlanGenerator
from xplan.engine.plan_verifier import (
    PlanVerifier,
    PlanVerificationResult,
)


class IterationLoop:
    """Iterative Plan generation loop.

    Flow: generate -> evaluate -> correct -> generate -> ...
    Stops if evaluation passes (score >= threshold) or maximum iteration count is reached.
    """

    def __init__(
        self,
        plan_generator: PlanGenerator,
        plan_verifier: PlanVerifier,
        max_iterations: int = 3,
    ):
        """Initialize the iterative generation loop.

        Args:
            plan_generator: Plan generator
            plan_verifier: Plan verifier
            max_iterations: Maximum iteration count, default 3
        """
        self.plan_generator = plan_generator
        self.plan_verifier = plan_verifier
        self.max_iterations = max_iterations
        # Record iteration count per run, used to calculate average
        self._iteration_counts: list[int] = []

    async def run(
        self,
        user_input: str,
        conversation_history: str = "",
    ) -> tuple[Plan, list[PlanVerificationResult]]:
        """Execute the generate-evaluate-correct loop.

        Each iteration:
        1. Call plan_generator.generate to generate Plan
        2. Call plan_verifier.verify to evaluate Plan
        3. If evaluation passes (score >= threshold), stop and return
        4. If not passing and maximum iteration count not reached, continue to next iteration

        Args:
            user_input: User input
            conversation_history: Conversation history

        Returns:
            Tuple (final Plan, list of all verification results)
        """
        results: list[PlanVerificationResult] = []
        plan: Plan | None = None
        threshold = 0.8

        for i in range(self.max_iterations):
            # Generate Plan
            plan = await self.plan_generator.generate(
                user_input, conversation_history
            )
            plan.iteration_count = i + 1

            # Evaluate Plan
            result = await self.plan_verifier.verify(plan)
            results.append(result)

            # Stop if evaluation passes
            if self.plan_verifier.is_passing(result, threshold):
                self._iteration_counts.append(i + 1)
                return plan, results

        # Maximum iteration count reached without passing
        if plan is not None:
            self._iteration_counts.append(self.max_iterations)
        return plan, results  # type: ignore[return-value]

    def get_average_iterations(self) -> float:
        """Get average iteration count, used to monitor Plan generation quality.

        Most Plans complete in one iteration; a few require multiple.
        An average iteration count that is too high indicates Plan generation quality needs optimization.

        Returns:
            Average iteration count, returns 0.0 when no run records
        """
        if not self._iteration_counts:
            return 0.0
        return sum(self._iteration_counts) / len(self._iteration_counts)

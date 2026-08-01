"""Constraint management service - Manages hard constraints and soft constraints.

Core rule: Constraint modifications must be evidenced by user input; Agent cannot modify constraints autonomously.
If there is no user_input, raises ValueError.

Constraints are divided into hard constraints (hard, cannot be violated) and soft constraints (soft, should be satisfied).
They are injected into the system prompt on every LLM call to prevent constraints from being ignored as context grows.
"""

import logging

logger = logging.getLogger(__name__)

# Keywords used to extract constraints from conversation history
_HARD_CONSTRAINT_KEYWORDS: list[str] = [
    "不能",
    "必须",
    "禁止",
    "务必",
    "不可以",
    "严禁",
    "一定不能",
]

_SOFT_CONSTRAINT_KEYWORDS: list[str] = [
    "尽量",
    "最好",
    "建议",
    "优先",
    "希望",
    "尽可能",
]


class ConstraintManager:
    """Constraint management service, manages hard constraints and soft constraints.

    Constraint modifications must be evidenced by user input; Agent cannot modify constraints autonomously.
    If there is no user_input, raises ValueError.

    Attributes:
        hard_constraints: Hard constraint list, cannot be violated
        soft_constraints: Soft constraint list, should be satisfied
        _evidence: Constraint modification evidence records, key is constraint text, value is user_input
    """

    def __init__(self) -> None:
        """Initialize constraint manager, hard and soft constraint lists are empty."""
        self.hard_constraints: list[str] = []
        self.soft_constraints: list[str] = []
        self._evidence: dict[str, str] = {}

    def add_hard_constraint(self, constraint: str, user_input: str) -> None:
        """Add a hard constraint.

        Must provide user_input as evidence, otherwise raises ValueError.

        Args:
            constraint: Hard constraint text
            user_input: User input, as evidence for adding the constraint

        Raises:
            ValueError: When user_input is empty
        """
        if not user_input or not user_input.strip():
            raise ValueError(
                "Adding hard constraint requires user_input as evidence; Agent cannot add constraints autonomously"
            )
        if constraint and constraint not in self.hard_constraints:
            self.hard_constraints.append(constraint)
            self._evidence[constraint] = user_input
            logger.info("Added hard constraint: %s", constraint)

    def add_soft_constraint(self, constraint: str, user_input: str) -> None:
        """Add a soft constraint.

        Must provide user_input as evidence, otherwise raises ValueError.

        Args:
            constraint: Soft constraint text
            user_input: User input, as evidence for adding the constraint

        Raises:
            ValueError: When user_input is empty
        """
        if not user_input or not user_input.strip():
            raise ValueError(
                "Adding soft constraint requires user_input as evidence; Agent cannot add constraints autonomously"
            )
        if constraint and constraint not in self.soft_constraints:
            self.soft_constraints.append(constraint)
            self._evidence[constraint] = user_input
            logger.info("Added soft constraint: %s", constraint)

    def update_constraint(self, old: str, new: str, user_input: str) -> None:
        """Update a constraint.

        Must provide user_input as evidence, otherwise raises ValueError.
        Automatically identifies whether the old constraint is hard or soft, and updates it in the corresponding list.

        Args:
            old: Old constraint text
            new: New constraint text
            user_input: User input, as evidence for updating the constraint

        Raises:
            ValueError: When user_input is empty, or the old constraint does not exist
        """
        if not user_input or not user_input.strip():
            raise ValueError(
                "Updating constraint requires user_input as evidence; Agent cannot modify constraints autonomously"
            )

        if old in self.hard_constraints:
            index = self.hard_constraints.index(old)
            self.hard_constraints[index] = new
            # Migrate evidence
            self._evidence.pop(old, None)
            self._evidence[new] = user_input
            logger.info("Updated hard constraint: %s -> %s", old, new)
        elif old in self.soft_constraints:
            index = self.soft_constraints.index(old)
            self.soft_constraints[index] = new
            self._evidence.pop(old, None)
            self._evidence[new] = user_input
            logger.info("Updated soft constraint: %s -> %s", old, new)
        else:
            raise ValueError(f"Constraint to update does not exist: {old}")

    def remove_constraint(self, constraint: str, user_input: str) -> None:
        """Remove a constraint.

        Must provide user_input as evidence, otherwise raises ValueError.
        Automatically identifies whether the constraint is hard or soft, and removes it from the corresponding list.

        Args:
            constraint: Constraint text to remove
            user_input: User input, as evidence for removing the constraint

        Raises:
            ValueError: When user_input is empty, or the constraint does not exist
        """
        if not user_input or not user_input.strip():
            raise ValueError(
                "Removing constraint requires user_input as evidence; Agent cannot remove constraints autonomously"
            )

        if constraint in self.hard_constraints:
            self.hard_constraints.remove(constraint)
            self._evidence.pop(constraint, None)
            logger.info("Removed hard constraint: %s", constraint)
        elif constraint in self.soft_constraints:
            self.soft_constraints.remove(constraint)
            self._evidence.pop(constraint, None)
            logger.info("Removed soft constraint: %s", constraint)
        else:
            raise ValueError(f"Constraint to remove does not exist: {constraint}")

    def get_hard_constraints(self) -> list[str]:
        """Get the hard constraint list.

        Returns:
            A copy of the hard constraint list, to avoid external direct modification
        """
        return list(self.hard_constraints)

    def get_soft_constraints(self) -> list[str]:
        """Get the soft constraint list.

        Returns:
            A copy of the soft constraint list, to avoid external direct modification
        """
        return list(self.soft_constraints)

    def inject_into_prompt(self, base_prompt: str) -> str:
        """Inject constraints into the system prompt.

        Injects constraints into the system prompt on every LLM call, ensuring that
        the influence of constraints is not weakened. Hard and soft constraints are
        labeled separately to emphasize priority.

        Args:
            base_prompt: Base system prompt

        Returns:
            System prompt with constraints injected
        """
        hard_text = "\n".join(f"  - {c}" for c in self.hard_constraints) if self.hard_constraints else "  - (No hard constraints)"
        soft_text = "\n".join(f"  - {c}" for c in self.soft_constraints) if self.soft_constraints else "  - (No soft constraints)"

        constraint_block = f"""
# Constraint Management (Read every call)

## Hard Constraints (HARD - Must not violate, execution must be blocked on violation)
{hard_text}

## Soft Constraints (SOFT - Try to satisfy, record but allow continuation on violation)
{soft_text}

## Constraint Rules
1. Hard constraint violations **must block execution**
2. Soft constraint violations **record but allow continuation**
3. Constraints can only be modified by user input, Agent cannot modify constraints autonomously
"""

        return f"{base_prompt}\n{constraint_block}"

    def extract_constraints_from_history(self, conversation_history: str) -> None:
        """Extract constraints from conversation history.

        Simplified implementation, based on keyword matching:
        - Statements containing keywords like "不能" "必须" "禁止" are identified as hard constraints
        - Statements containing keywords like "尽量" "最好" "建议" are identified as soft constraints

        Note: This method is a simplified implementation that uses the entire statement as the constraint.
        The conversation history itself is user input, thus satisfying the rule that
        "constraint modifications must be evidenced by user input".

        Args:
            conversation_history: Conversation history text
        """
        if not conversation_history:
            return

        # Split conversation history by lines
        lines = conversation_history.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it is a user utterance (simplified check: starts with "user:" or "User:")
            is_user_input = (
                line.lower().startswith("用户:")
                or line.lower().startswith("user:")
                or line.lower().startswith("用户：")
            )
            # Extract utterance content
            content = line.split(":", 1)[-1].strip() if ":" in line else line
            content = content.split("：", 1)[-1].strip() if "：" in content else content

            # Match hard constraints based on keywords
            for keyword in _HARD_CONSTRAINT_KEYWORDS:
                if keyword in content:
                    if content not in self.hard_constraints:
                        self.hard_constraints.append(content)
                        self._evidence[content] = line
                        logger.info("Extracted hard constraint from conversation history: %s", content)
                    break

            # Match soft constraints based on keywords
            for keyword in _SOFT_CONSTRAINT_KEYWORDS:
                if keyword in content:
                    if content not in self.soft_constraints:
                        self.soft_constraints.append(content)
                        self._evidence[content] = line
                        logger.info("Extracted soft constraint from conversation history: %s", content)
                    break

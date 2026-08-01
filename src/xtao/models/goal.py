"""Goal model - goal and success criteria."""

from pydantic import BaseModel, Field


class Goal(BaseModel):
    """Goal definition of Plan.

    Resolves goal uncertainty: clarifies what to achieve and what counts as success.
    """

    user_goal: str = Field(description="User goal description")
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Success criteria list, each item must be verifiable",
    )
    adjective_standards: dict[str, str] = Field(
        default_factory=dict,
        description="Adjective standard definitions, mapping vague adjectives to quantifiable criteria",
    )

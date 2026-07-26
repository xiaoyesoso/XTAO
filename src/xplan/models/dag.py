"""DAG model - DAG-style Plan structure."""

from pydantic import BaseModel, Field


class DAGNode(BaseModel):
    """DAG node.

    Each node contains id and depends_on (list of dependency step IDs).
    """

    id: str = Field(description="Node unique identifier")
    objective: str = Field(description="Node objective")
    reason: str = Field(default="", description="Reason for the node's existence")
    depends_on: list[str] = Field(
        default_factory=list,
        description="List of dependency node IDs",
    )
    status: str = Field(
        default="pending",
        description="Node status: pending | running | done | failed | skipped",
    )


class DAGEdge(BaseModel):
    """DAG edge, for dependency relationships with attributes."""

    src: str = Field(description="Source node ID")
    dst: str = Field(description="Destination node ID")
    attrs: dict = Field(
        default_factory=dict,
        description="Dependency relationship attributes",
    )


class DAGPlan(BaseModel):
    """DAG-style Plan.

    Optional advanced mode, suitable for complex scenarios requiring step parallelism.
    Linear Plan is used by default, DAG is optionally enabled.
    """

    nodes: list[DAGNode] = Field(default_factory=list, description="Node list")
    edges: list[DAGEdge] = Field(
        default_factory=list,
        description="Edge list, for dependency relationships with attributes",
    )

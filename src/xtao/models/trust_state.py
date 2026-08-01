"""Intermediate result trust state model - marks trust state for intermediate results, supports cascade marking and evidence chain tracing.

Trust state is divided into five levels:
- VERIFIED: verified, currently trusted
- AVAILABLE: temporarily usable, not fully verified
- SUSPICIOUS: may have issues, needs re-checking
- INVALID: confirmed error
- DIRTY: depends on an INVALID result
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TrustState(str, Enum):
    """Intermediate result trust state."""

    VERIFIED = "verified"        # Verified, currently trusted
    AVAILABLE = "available"      # Temporarily usable, not fully verified
    SUSPICIOUS = "suspicious"    # May have issues, needs re-checking
    INVALID = "invalid"          # Confirmed error
    DIRTY = "dirty"              # Depends on an Invalid result


class FactEntry(BaseModel):
    """Fact entry (with trust state and evidence)."""

    key: str = Field(description="Fact key, e.g. highest_qps")
    value: Any = Field(description="Fact value")
    trust_state: TrustState = Field(default=TrustState.AVAILABLE, description="Trust state")
    evidence: str = Field(default="", description="Evidence source")
    source_step_id: str = Field(default="", description="Step ID that produced this fact")
    depends_on: list[str] = Field(default_factory=list, description="Other fact keys depended on")


class TrustStateChange(BaseModel):
    """Trust state change record."""

    key: str = Field(description="Fact key")
    old_state: TrustState = Field(description="Old state")
    new_state: TrustState = Field(description="New state")
    reason: str = Field(default="", description="Change reason")
    cascaded: bool = Field(default=False, description="Whether it is a cascade marking")


class TrustStateReport(BaseModel):
    """Trust state report."""

    facts: list[FactEntry] = Field(default_factory=list, description="All fact entries")
    changes: list[TrustStateChange] = Field(default_factory=list, description="State change records")
    verified_count: int = Field(default=0, description="Verified count")
    available_count: int = Field(default=0, description="Available count")
    suspicious_count: int = Field(default=0, description="Suspicious count")
    invalid_count: int = Field(default=0, description="Invalid count")
    dirty_count: int = Field(default=0, description="Dirty count")

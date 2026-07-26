"""XPlan Python SDK.

A Pythonic, type-safe async client for the XPlan G4C Plan service.

The SDK wraps every REST endpoint exposed by the XPlan FastAPI server and
reuses the Pydantic models from :mod:`xplan.models` so callers can pass model
instances directly without dealing with raw JSON.

Quick start:
    import asyncio
    from xplan.sdk import XPlanClient

    async def main():
        async with XPlanClient(base_url="http://localhost:8000") as client:
            health = await client.health_check()
            print(health)
            result = await client.run_plan(user_input="Help me optimize my resume")
            print(result)

    asyncio.run(main())

The primary entry point is :meth:`XPlanClient.run_plan`, which orchestrates
the full G4C lifecycle (generate -> verify -> execute -> correct). Granular
methods (generate_plan, verify_plan, execute_plan, replan, etc.) are exposed
for advanced control.
"""

from xplan.sdk.client import XPlanClient
from xplan.sdk.exceptions import (
    APIError,
    ConnectionError,
    TimeoutError,
    ValidationError,
    XPlanError,
)

__version__ = "0.1.0"

__all__ = [
    "XPlanClient",
    "XPlanError",
    "APIError",
    "ConnectionError",
    "TimeoutError",
    "ValidationError",
    "__version__",
]

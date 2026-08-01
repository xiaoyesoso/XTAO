"""XTAO Python SDK.

A Pythonic, type-safe async client for the XTAO G4C Plan service.

The SDK wraps every REST endpoint exposed by the XTAO FastAPI server and
reuses the Pydantic models from :mod:`xtao.models` so callers can pass model
instances directly without dealing with raw JSON.

Quick start:
    import asyncio
    from xtao.sdk import XTAOClient

    async def main():
        async with XTAOClient(base_url="http://localhost:8000") as client:
            health = await client.health_check()
            print(health)
            result = await client.run_plan(user_input="Help me optimize my resume")
            print(result)

    asyncio.run(main())

The primary entry point is :meth:`XTAOClient.run_plan`, which orchestrates
the full G4C lifecycle (generate -> verify -> execute -> correct). Granular
methods (generate_plan, verify_plan, execute_plan, replan, etc.) are exposed
for advanced control.
"""

from xtao.sdk.client import XTAOClient
from xtao.sdk.exceptions import (
    APIError,
    ConnectionError,
    TimeoutError,
    ValidationError,
    XTAOError,
)

__version__ = "0.1.0"

__all__ = [
    "XTAOClient",
    "XTAOError",
    "APIError",
    "ConnectionError",
    "TimeoutError",
    "ValidationError",
    "__version__",
]

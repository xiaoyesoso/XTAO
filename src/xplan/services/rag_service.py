"""RAG/knowledge base service - Wraps knowledge base retrieval.

Used to retrieve domain standards to clarify success criteria and adjective
standards in Goal, and to retrieve correction scenarios to assist Correction
design. When enabled=False, search methods return empty strings.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


class RAGService:
    """RAG/knowledge base service, wraps knowledge base retrieval.

    When enabled=False, all search methods return empty strings to avoid blocking the flow.
    When enabled=True, uses httpx to asynchronously call the RAG API.

    Attributes:
        enabled: Whether RAG retrieval is enabled
        api_base: RAG API base URL
        timeout: Request timeout (seconds), default 30
    """

    def __init__(
        self,
        enabled: bool = False,
        api_base: str = "",
        timeout: float = 30.0,
    ) -> None:
        """Initialize RAG service.

        Args:
            enabled: Whether RAG retrieval is enabled, default False
            api_base: RAG API base URL
            timeout: Request timeout (seconds), default 30
        """
        self.enabled = enabled
        self.api_base = api_base.rstrip("/") if api_base else ""
        self.timeout = timeout

    async def search(self, query: str, top_k: int = 3) -> str:
        """Retrieve domain standards, return search result text.

        Used to retrieve domain standards (e.g. job capability requirements)
        in the Goal definition phase, to clarify success criteria and
        adjective standards.

        Args:
            query: Search query text
            top_k: Number of most relevant results to return, default 3

        Returns:
            Search result text. If enabled=False, returns empty string.
        """
        if not self.enabled:
            logger.debug("RAG service not enabled, search returns empty string")
            return ""

        if not self.api_base:
            logger.warning("RAG service enabled but api_base is empty, returning empty string")
            return ""

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_base}/search",
                    json={"query": query, "top_k": top_k},
                )
                response.raise_for_status()
                data = response.json()
                # Expected response: {"results": [{"content": "...", "score": 0.9}, ...]}
                results = data.get("results", [])
                if not results:
                    return ""
                texts = [item.get("content", "") for item in results if item.get("content")]
                return "\n".join(texts)
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("RAG search failed (%s), returning empty string", type(e).__name__)
            return ""

    async def search_correction_scenarios(self, context: str) -> str:
        """Retrieve correction scenarios.

        Used to retrieve similar failure scenarios and correction practices
        in the Correction design phase, to help generate more practical
        correction rules.

        Args:
            context: Context text used to retrieve related correction scenarios

        Returns:
            Search result text. If enabled=False, returns empty string.
        """
        if not self.enabled:
            logger.debug("RAG service not enabled, search_correction_scenarios returns empty string")
            return ""

        if not self.api_base:
            logger.warning("RAG service enabled but api_base is empty, returning empty string")
            return ""

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.api_base}/search",
                    json={"query": f"Correction scenario: {context}", "top_k": 3},
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                if not results:
                    return ""
                texts = [item.get("content", "") for item in results if item.get("content")]
                return "\n".join(texts)
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning("RAG correction scenario search failed (%s), returning empty string", type(e).__name__)
            return ""

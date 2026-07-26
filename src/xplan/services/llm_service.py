"""LLM service - Wraps LLM calls.

Uses httpx to asynchronously call OpenAI-compatible API, supports retry (up to 3 times).
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class LLMService:
    """LLM service, wraps LLM calls.

    Uses httpx to asynchronously call OpenAI-compatible API, supports retry mechanism.

    Attributes:
        api_base: API base URL, e.g. https://api.siliconflow.cn/v1
        api_key: API key
        model: Model name
        max_retries: Maximum retry count, default 3
        timeout: Request timeout (seconds), default 60
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        """Initialize LLM service.

        Args:
            api_base: API base URL, e.g. https://api.siliconflow.cn/v1
            api_key: API key
            model: Model name
            max_retries: Maximum retry count, default 3
            timeout: Request timeout (seconds), default 60
        """
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict | None = None,
    ) -> str:
        """Call LLM, return response text.

        Uses OpenAI-compatible Chat Completions API, supports retry (up to max_retries times).

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            response_format: Response format definition for structured output, e.g. {"type": "json_object"}

        Returns:
            Response text returned by the LLM

        Raises:
            RuntimeError: Raised when all retries fail
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload: dict = {
            "model": self.model,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.api_base}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    "LLM call failed (HTTP %s), attempt %d/%d",
                    e.response.status_code,
                    attempt,
                    self.max_retries,
                )
            except (httpx.RequestError, KeyError, IndexError) as e:
                last_error = e
                logger.warning(
                    "LLM call failed (%s), attempt %d/%d",
                    type(e).__name__,
                    attempt,
                    self.max_retries,
                )

            # When not the last retry, wait for a while (exponential backoff)
            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"LLM call failed, retried {self.max_retries} times. Last error: {last_error}"
        )

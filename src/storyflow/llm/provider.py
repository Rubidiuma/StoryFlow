"""Placeholder for the application's single real LLM provider adapter."""

from collections.abc import AsyncIterator, Mapping
from typing import Any, NoReturn


class ProviderLLMClient:
    """Real-provider boundary deliberately left unwired for the MVP test path."""

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Reject requests until a concrete provider integration is configured."""
        self._not_configured()

    def stream_text(self, *, prompt: str, context: Mapping[str, Any]) -> AsyncIterator[str]:
        """Reject streamed requests until a concrete provider integration is configured."""
        self._not_configured()

    @staticmethod
    def _not_configured() -> NoReturn:
        raise NotImplementedError("A real LLM provider is not configured.")

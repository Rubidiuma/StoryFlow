"""Interfaces shared by LLM providers and test doubles."""

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable


class InvalidStructuredResponseError(ValueError):
    """A structured LLM response could not be represented as a JSON object."""


class LLMRequestError(RuntimeError):
    """An expected model request failure that application code may safely classify."""


class LLMRejectedError(LLMRequestError):
    """The configured model explicitly rejected a request without producing output."""


@runtime_checkable
class LLMClient(Protocol):
    """One structured request or one streamed text request to an LLM."""

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return one JSON object for the supplied prompt and context."""

    def stream_text(self, *, prompt: str, context: Mapping[str, Any]) -> AsyncIterator[str]:
        """Yield text chunks for the supplied prompt and context."""

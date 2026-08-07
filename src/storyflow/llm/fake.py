"""Deterministic LLM implementation for tests and local development."""

import json
from collections import deque
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from storyflow.llm.base import InvalidStructuredResponseError


class StreamInterruptedError(ConnectionError):
    """Raised when a scripted stream stops before producing all its text."""


class FakeLLMClient:
    """Return pre-scripted structured responses and streamed text chunks."""

    def __init__(
        self,
        *,
        json_responses: Iterable[object] = (),
        text_responses: Iterable[Sequence[str | BaseException]] = (),
    ) -> None:
        self._json_responses = deque(json_responses)
        self._text_responses = deque(text_responses)
        self.calls: list[dict[str, object]] = []

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return the next scripted JSON object."""
        self._record_call("generate_json", prompt, context)
        if not self._json_responses:
            raise AssertionError("No scripted JSON response remains.")
        response = self._json_responses.popleft()
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict):
            raise InvalidStructuredResponseError("Structured LLM responses must be JSON objects.")
        return deepcopy(response)

    async def stream_text(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> AsyncIterator[str]:
        """Yield the next scripted response exactly one chunk at a time."""
        self._record_call("stream_text", prompt, context)
        if not self._text_responses:
            raise AssertionError("No scripted text response remains.")
        for chunk in self._text_responses.popleft():
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    def _record_call(self, operation: str, prompt: str, context: Mapping[str, Any]) -> None:
        self.calls.append(
            {
                "operation": operation,
                "prompt": prompt,
                "context": deepcopy(dict(context)),
            }
        )

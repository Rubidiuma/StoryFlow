from __future__ import annotations

"""Real Anthropic LLM provider adapter."""

import json
import os
from collections.abc import AsyncIterator, Mapping
from typing import Any

import anthropic

from storyflow.llm.base import InvalidStructuredResponseError, LLMRequestError

_DEFAULT_MODEL = os.getenv("STORYFLOW_LLM_MODEL", "claude-haiku-4-5")
_MAX_TOKENS_JSON = 4096
_MAX_TOKENS_STREAM = 2048


class ProviderLLMClient:
    """Anthropic API adapter implementing the LLMClient protocol."""

    def __init__(self, api_key: str, *, model: str = _DEFAULT_MODEL) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Call the model and return its response parsed as a JSON object."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS_JSON,
                system=prompt,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False),
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise LLMRequestError(f"Anthropic API error: {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMRequestError("Anthropic connection error") from exc

        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        # Strip markdown code fences if present
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            result = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidStructuredResponseError(
                f"Model returned non-JSON: {stripped[:200]}"
            ) from exc
        if not isinstance(result, dict):
            raise InvalidStructuredResponseError("Model response must be a JSON object")
        return result

    async def stream_text(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> AsyncIterator[str]:
        """Stream text chunks from the model."""
        return _stream_generator(self._client, self._model, prompt, context)


async def _stream_generator(
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt: str,
    context: Mapping[str, Any],
) -> AsyncIterator[str]:
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=_MAX_TOKENS_STREAM,
            system=prompt,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                }
            ],
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except anthropic.APIStatusError as exc:
        raise LLMRequestError(f"Anthropic API error: {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMRequestError("Anthropic connection error") from exc

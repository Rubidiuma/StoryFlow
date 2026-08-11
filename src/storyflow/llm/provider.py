from __future__ import annotations

"""Real Anthropic LLM provider adapter."""

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from typing import Any

import anthropic

from storyflow.llm.base import InvalidStructuredResponseError, LLMRequestError

_log = logging.getLogger(__name__)

_DEFAULT_MODEL = os.getenv("STORYFLOW_LLM_MODEL", "claude-haiku-4-5")
_MAX_TOKENS_JSON = 4096
_MAX_TOKENS_STREAM = 2048


class ProviderLLMClient:
    """Anthropic API adapter implementing the LLMClient protocol."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        base_url: str | None = None,
    ) -> None:
        kwargs: dict = {}
        if base_url:
            kwargs["base_url"] = base_url
        # Poe and some proxies use Bearer auth; Anthropic uses x-api-key.
        # Use auth_token for Bearer, api_key for x-api-key.
        if base_url and "poe.com" in base_url:
            kwargs["auth_token"] = api_key
        else:
            kwargs["api_key"] = api_key
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._model = model
        _log.info(
            "ProviderLLMClient initialized: model=%s base_url=%s",
            model,
            base_url or "(default)",
        )

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
            _log.error(
                "Anthropic API error %s: %s", exc.status_code, exc.message
            )
            raise LLMRequestError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            _log.error("Anthropic connection error: %s", exc)
            raise LLMRequestError("Anthropic connection error") from exc
        except Exception as exc:
            _log.exception("Unexpected error calling Anthropic API: %s", exc)
            raise LLMRequestError(f"Unexpected LLM error: {exc}") from exc

        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        _log.warning("LLM raw response (%d chars): %.600s", len(text), text)

        # Strip markdown code fences if present
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            result = json.loads(stripped)
        except json.JSONDecodeError as exc:
            _log.warning("LLM returned non-JSON: %.300s", stripped)
            raise InvalidStructuredResponseError(
                f"Model returned non-JSON: {stripped[:200]}"
            ) from exc
        if not isinstance(result, dict):
            raise InvalidStructuredResponseError("Model response must be a JSON object")
        return result

    # stream_text must be a regular (sync) method returning an AsyncIterator,
    # matching the LLMClient protocol and how FakeLLMClient works.
    def stream_text(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> AsyncIterator[str]:
        """Return an async iterator that streams text chunks from the model."""
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
        _log.error("Anthropic stream API error %s: %s", exc.status_code, exc.message)
        raise LLMRequestError(
            f"Anthropic API error {exc.status_code}: {exc.message}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        _log.error("Anthropic stream connection error: %s", exc)
        raise LLMRequestError("Anthropic connection error") from exc
    except Exception as exc:
        _log.exception("Unexpected stream error: %s", exc)
        raise LLMRequestError(f"Unexpected stream error: {exc}") from exc

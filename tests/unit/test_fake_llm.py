"""Contract tests for the deterministic LLM test double."""

import json

import pytest

from storyflow.llm.base import LLMClient
from storyflow.llm.fake import FakeLLMClient, InvalidStructuredResponseError, StreamInterruptedError
from storyflow.llm.provider import ProviderLLMClient


def test_llm_client_declares_structured_and_streaming_operations() -> None:
    """Consumers can depend on one interface for JSON and streaming requests."""
    assert callable(LLMClient.generate_json)
    assert callable(LLMClient.stream_text)


@pytest.mark.asyncio
async def test_fake_returns_queued_json_and_records_each_received_context() -> None:
    """Queued structured results are consumed in order and preserve request evidence."""
    client = FakeLLMClient(json_responses=[{"title": "First"}, {"title": "Second"}])
    first_context = {"story_id": "story-1"}

    first_result = await client.generate_json(prompt="make bible", context=first_context)
    first_context["story_id"] = "changed-after-call"
    second_result = await client.generate_json(
        prompt="make scene plan", context={"story_id": "story-1", "scene": 1}
    )

    assert first_result == {"title": "First"}
    assert second_result == {"title": "Second"}
    assert client.calls == [
        {
            "operation": "generate_json",
            "prompt": "make bible",
            "context": {"story_id": "story-1"},
        },
        {
            "operation": "generate_json",
            "prompt": "make scene plan",
            "context": {"story_id": "story-1", "scene": 1},
        },
    ]


@pytest.mark.asyncio
async def test_fake_streams_queued_text_chunks_and_records_context() -> None:
    """A scripted text response reaches readers chunk-by-chunk in script order."""
    client = FakeLLMClient(text_responses=[["The door ", "opens."]])

    chunks = [
        chunk
        async for chunk in client.stream_text(
            prompt="write scene", context={"scene_plan": "open the door"}
        )
    ]

    assert chunks == ["The door ", "opens."]
    assert client.calls == [
        {
            "operation": "stream_text",
            "prompt": "write scene",
            "context": {"scene_plan": "open the door"},
        }
    ]


@pytest.mark.asyncio
async def test_fake_rejects_malformed_json_and_non_object_structures() -> None:
    """Structured generation makes malformed text and non-object JSON explicit failures."""
    client = FakeLLMClient(json_responses=['{"title": ', ["not", "an object"]])

    with pytest.raises(json.JSONDecodeError):
        await client.generate_json(prompt="make bible", context={})
    with pytest.raises(InvalidStructuredResponseError):
        await client.generate_json(prompt="make bible", context={})


@pytest.mark.asyncio
async def test_fake_raises_a_scripted_timeout_after_recording_the_request() -> None:
    """Services can deterministically exercise their timeout path without a provider call."""
    client = FakeLLMClient(json_responses=[TimeoutError("provider timed out")])

    with pytest.raises(TimeoutError, match="provider timed out"):
        await client.generate_json(prompt="make bible", context={"attempt": 1})

    assert client.calls == [
        {
            "operation": "generate_json",
            "prompt": "make bible",
            "context": {"attempt": 1},
        }
    ]


@pytest.mark.asyncio
async def test_fake_interrupts_a_scripted_stream_after_earlier_chunks() -> None:
    """Readers receive chunks emitted before a deterministic stream interruption."""
    client = FakeLLMClient(
        text_responses=[["The first sentence. ", StreamInterruptedError("connection lost")]]
    )

    chunks: list[str] = []
    with pytest.raises(StreamInterruptedError, match="connection lost"):
        async for chunk in client.stream_text(prompt="write scene", context={}):
            chunks.append(chunk)

    assert chunks == ["The first sentence. "]


@pytest.mark.asyncio
async def test_provider_skeleton_has_no_implicit_network_implementation() -> None:
    """A provider must be explicitly wired before application code can make a real request."""
    client = ProviderLLMClient()

    with pytest.raises(NotImplementedError, match="not configured"):
        await client.generate_json(prompt="make bible", context={})

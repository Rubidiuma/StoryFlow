"""Versioned server-sent events for one deterministic scene generation."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, field_validator
from starlette.responses import StreamingResponse

from storyflow.api.errors import generation_error_data, generation_http_error
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import StoryStatus
from storyflow.llm.base import LLMClient
from storyflow.services.generation import GenerationRequest, GenerationResult, GenerationService

EventName = Literal[
    "planning",
    "delta",
    "committed",
    "choice",
    "continue",
    "paused",
    "heartbeat",
    "error",
]


class GenerateStoryRequest(BaseModel):
    """Inputs required to generate one scene on a specific branch."""

    branch_id: UUID
    generation_key: str
    context: dict[str, object]

    @field_validator("generation_key")
    @classmethod
    def generation_key_is_visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("generation_key must contain visible text")
        return value


@dataclass(frozen=True, slots=True)
class _SSEEvent:
    name: EventName
    data: dict[str, object]


def create_generation_router(
    repository: StoryRepository | None,
    llm_client: LLMClient | None,
    *,
    emit_heartbeat: bool = False,
) -> APIRouter:
    """Build generation routes around explicitly injected runtime dependencies."""
    router = APIRouter(prefix="/api/stories", tags=["generation"])
    generation_service = (
        GenerationService(repository, llm_client)
        if repository is not None and llm_client is not None
        else None
    )

    @router.post("/{story_id}/generate")
    async def generate_story(
        story_id: UUID,
        request: GenerateStoryRequest,
    ) -> StreamingResponse:
        if repository is None or llm_client is None or generation_service is None:
            raise generation_http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "generation_service_unavailable",
                retryable=True,
            )
        story = repository.get_story(story_id)
        if story is None:
            raise generation_http_error(status.HTTP_404_NOT_FOUND, "story_not_found")
        branch = repository.get_branch(request.branch_id)
        if branch is None:
            raise generation_http_error(status.HTTP_404_NOT_FOUND, "branch_not_found")
        existing = repository.get_segment_by_generation_key(request.generation_key)
        if existing is not None:
            request_is_valid = (
                existing.story_id == story_id and existing.branch_id == request.branch_id
            )
        else:
            request_is_valid = (
                branch.story_id == story_id
                and story.status is StoryStatus.IDLE
                and story.current_branch_id == request.branch_id
            )
        if not request_is_valid:
            raise generation_http_error(
                status.HTTP_409_CONFLICT,
                "invalid_generation_state",
            )
        generation_request = GenerationRequest(
            story_id=story_id,
            branch_id=request.branch_id,
            generation_key=request.generation_key,
            context=request.context,
            scenes_since_last_choice=_scenes_since_last_choice(repository, request.branch_id),
        )
        branch_reserved = False
        if existing is None:
            branch_reserved = generation_service.try_reserve_branch(story_id, request.branch_id)
            if not branch_reserved:
                raise generation_http_error(
                    status.HTTP_409_CONFLICT,
                    "generation_conflict",
                    retryable=True,
                )

        async def event_stream() -> AsyncIterator[str]:
            queue: asyncio.Queue[_SSEEvent | None] = asyncio.Queue()

            async def publish_delta(text: str) -> None:
                await queue.put(_SSEEvent("delta", {"text": text}))

            async def run_generation() -> None:
                try:
                    result = await generation_service.generate(
                        generation_request,
                        on_delta=publish_delta,
                        branch_reserved=branch_reserved,
                    )
                    await _publish_result(queue, result)
                finally:
                    await queue.put(None)

            await queue.put(_SSEEvent("planning", {}))
            if emit_heartbeat:
                await queue.put(_SSEEvent("heartbeat", {"text": ""}))
            task = asyncio.create_task(run_generation())
            try:
                while (event := await queue.get()) is not None:
                    yield _encode_sse(event)
                await task
            finally:
                if not task.done():
                    task.cancel()
                if branch_reserved:
                    generation_service.release_branch(story_id, request.branch_id)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return router


def _scenes_since_last_choice(repository: StoryRepository, branch_id: UUID) -> int:
    """Count completed scenes after the latest persisted choice on this branch."""
    distance = 0
    for segment in reversed(repository.list_branch_path(branch_id)):
        if repository.get_choice_point_for_segment(segment.id) is not None:
            break
        distance += 1
    return distance


async def _publish_result(
    queue: asyncio.Queue[_SSEEvent | None],
    result: GenerationResult,
) -> None:
    """Publish commit and terminal control events after the service completes."""
    if result.error_code is not None or result.segment is None:
        await queue.put(_SSEEvent("error", generation_error_data(result.error_code)))
        return
    await queue.put(
        _SSEEvent(
            "committed",
            {"segment_id": str(result.segment.id), "status": result.status.value},
        )
    )
    if result.status is StoryStatus.WAITING_CHOICE and result.choice_point is not None:
        await queue.put(
            _SSEEvent(
                "choice",
                {
                    "choice_point_id": str(result.choice_point.id),
                    "options": [
                        {
                            "id": str(option.id),
                            "text": option.text,
                            "position": option.position,
                        }
                        for option in result.choice_point.options
                    ],
                },
            )
        )
    elif result.status is StoryStatus.PAUSED:
        await queue.put(_SSEEvent("paused", {}))
    else:
        await queue.put(_SSEEvent("continue", {}))


def _encode_sse(event: _SSEEvent) -> str:
    payload = {"version": 1, "event": event.name, "data": event.data}
    return f"event: {event.name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


__all__ = ["create_generation_router"]

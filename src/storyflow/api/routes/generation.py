from __future__ import annotations
"""Versioned server-sent events for one deterministic scene generation."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, field_validator
from starlette.responses import StreamingResponse

from storyflow.api.dependencies import optional_session_id
from storyflow.api.errors import generation_error_data, generation_http_error
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import StoryStatus
from storyflow.llm.base import LLMClient
from storyflow.security.rate_limit import RateLimiter
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
    rate_limiter: RateLimiter | None = None,
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
        http_request: Request,
    ) -> StreamingResponse:
        session_id = optional_session_id(http_request)
        # Session and story checks run even when the LLM is unavailable
        if repository is not None:
            story = repository.get_story(story_id)
            if story is None or (session_id is not None and story.session_id != session_id):
                raise generation_http_error(status.HTTP_404_NOT_FOUND, "story_not_found")
        if repository is None or llm_client is None or generation_service is None:
            raise generation_http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "generation_service_unavailable",
                retryable=True,
            )
        story = repository.get_story(story_id)
        if story is None or (session_id is not None and story.session_id != session_id):
            raise generation_http_error(status.HTTP_404_NOT_FOUND, "story_not_found")
        if rate_limiter is not None and session_id is not None:
            if not rate_limiter.is_allowed(session_id):
                raise generation_http_error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
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
        # Build server-side story context; merge with request.context so that
        # test fixtures (e.g. {"marker": "..."}) and client keys are preserved.
        server_context = _build_story_context(repository, story_id, request.branch_id)
        merged_context: dict[str, Any] = {**request.context, **server_context}
        generation_request = GenerationRequest(
            story_id=story_id,
            branch_id=request.branch_id,
            generation_key=request.generation_key,
            context=merged_context,
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


def _build_story_context(
    repository: StoryRepository,
    story_id: UUID,
    branch_id: UUID,
) -> dict[str, Any]:
    """Build the full layered context for generation from persisted story data."""
    from storyflow.services.context_builder import (
        ChoiceMemory,
        ContextBuilder,
        ForeshadowingMemory,
        LayeredMemory,
        SceneMemory,
    )

    bible = repository.get_bible(story_id)
    arcs = repository.list_story_arcs(story_id)
    segments = repository.list_branch_path(branch_id)
    memory = repository.get_latest_memory_snapshot(branch_id)

    fixed_memory: dict[str, Any] = {}
    if bible:
        fixed_memory = {
            "world_rules": bible.world_rules,
            "tone_rules": bible.tone_rules,
            "protagonist_core": bible.protagonist_core,
            "required_elements": bible.required_elements,
            "forbidden_elements": bible.forbidden_elements,
        }

    # Use the most recent active arc for this branch (or any active arc)
    current_arc: dict[str, Any] = {}
    branch_arcs = [a for a in arcs if str(a.branch_id) == str(branch_id) and a.status == "active"]
    if not branch_arcs:
        branch_arcs = [a for a in arcs if a.status == "active"]
    if branch_arcs:
        arc = branch_arcs[-1]
        current_arc = {
            "goal": arc.goal,
            "conflict": arc.conflict,
            "stage": arc.stage,
            "exit_conditions": arc.exit_conditions,
            "summary": arc.summary,
        }

    characters: list[dict[str, Any]] = []
    foreshadowing: list[ForeshadowingMemory] = []
    rolling_summary = ""
    if memory:
        for char in memory.characters:
            characters.append({
                "name": char.name,
                "role": char.role,
                "location": char.location,
                "motivation": char.motivation,
                "known_facts": char.known_facts,
                "relationships": char.relationships,
                "alive": char.alive,
            })
        for fid, fdesc in memory.foreshadowing.items():
            foreshadowing.append(ForeshadowingMemory(id=fid, description=fdesc, status="active"))
        rolling_summary = memory.rolling_summary

    choices: list[ChoiceMemory] = []
    for seg in segments:
        cp = repository.get_choice_point_for_segment(seg.id)
        if cp and cp.status == "selected":
            if cp.selected_option_id:
                opt = next((o for o in cp.options if o.id == cp.selected_option_id), None)
                if opt:
                    choices.append(ChoiceMemory(text=opt.text, effects=dict(opt.effects)))
            elif cp.selected_custom_action:
                choices.append(ChoiceMemory(
                    text=cp.selected_custom_action,
                    effects=dict(cp.selected_effects or {}),
                ))

    scenes = [
        SceneMemory(sequence=s.sequence, content=s.content, summary=s.summary)
        for s in segments
    ]

    layered = LayeredMemory(
        fixed_memory=fixed_memory,
        current_arc=current_arc,
        characters=characters,
        foreshadowing=foreshadowing,
        choices=choices,
        rolling_summary=rolling_summary,
        scenes=scenes,
    )

    try:
        built = ContextBuilder(budget_tokens=8000).build(layered)
        _log.debug("Built generation context: %d tokens estimated", built.estimated_tokens)
        return dict(built.layers)
    except Exception as exc:
        _log.warning("Context build failed, using minimal context: %s", exc)
        return {"story_id": str(story_id), "branch_id": str(branch_id)}


__all__ = ["create_generation_router"]

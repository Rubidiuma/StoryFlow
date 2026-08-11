from __future__ import annotations
"""Deterministic single-scene generation coordinator."""

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import StoryStatus
from storyflow.domain.models import (
    Branch,
    ChoicePoint,
    GenerationEvent,
    ScenePlan,
    Story,
    StorySegment,
)
from storyflow.domain.state_machine import StoryStateMachine
from storyflow.llm.base import InvalidStructuredResponseError, LLMClient, LLMRequestError
from storyflow.prompts.director import DIRECTOR_PROMPT_V1
from storyflow.prompts.writer import WRITER_PROMPT_V1
from storyflow.services.choice_policy import evaluate_choice_policy


class _DirectorRequestFailure(RuntimeError):
    """Internal marker for an expected provider request failure."""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Caller-owned inputs for one scene generation attempt."""

    story_id: UUID
    branch_id: UUID
    generation_key: str
    context: Mapping[str, object]
    scenes_since_last_choice: int = 0


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Stable service result for a committed scene or classified failure."""

    status: StoryStatus
    segment: StorySegment | None = None
    choice_point: ChoicePoint | None = None
    content: str = ""
    error_code: str | None = None


class GenerationService:
    """Coordinate Director, choice policy, Writer, and one transactional commit."""

    def __init__(self, repository: StoryRepository, llm_client: LLMClient) -> None:
        self.repository = repository
        self.llm_client = llm_client
        self._active_branches: set[tuple[UUID, UUID]] = set()

    def try_reserve_branch(self, story_id: UUID, branch_id: UUID) -> bool:
        """Atomically reserve one branch within this service's event loop."""
        branch_key = (story_id, branch_id)
        if branch_key in self._active_branches:
            return False
        self._active_branches.add(branch_key)
        return True

    def release_branch(self, story_id: UUID, branch_id: UUID) -> None:
        """Release an owned branch reservation on every terminal path."""
        self._active_branches.discard((story_id, branch_id))

    async def generate(
        self,
        request: GenerationRequest,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        *,
        branch_reserved: bool = False,
    ) -> GenerationResult:
        """Generate and commit at most one complete scene."""
        existing = self.repository.get_segment_by_generation_key(request.generation_key)
        if existing is not None:
            story = self.repository.get_story(request.story_id)
            if existing.story_id != request.story_id or existing.branch_id != request.branch_id:
                return GenerationResult(
                    status=story.status if story is not None else StoryStatus.ERROR,
                    error_code="invalid_generation_state",
                )
            result = GenerationResult(
                status=story.status if story is not None else StoryStatus.ERROR,
                segment=existing,
                choice_point=self.repository.get_choice_point_for_segment(existing.id),
                content=existing.content,
            )
            if on_delta is not None and existing.content:
                await on_delta(existing.content)
            return result

        story = self.repository.get_story(request.story_id)
        branch = self.repository.get_branch(request.branch_id)
        if (
            story is None
            or story.status is not StoryStatus.IDLE
            or story.current_branch_id != request.branch_id
            or branch is None
            or branch.story_id != request.story_id
        ):
            return GenerationResult(
                status=story.status if story is not None else StoryStatus.ERROR,
                error_code="invalid_generation_state",
            )

        acquired_here = not branch_reserved
        owns_reservation = branch_reserved or self.try_reserve_branch(
            request.story_id, request.branch_id
        )
        if not owns_reservation:
            return GenerationResult(
                status=story.status,
                error_code="generation_conflict",
            )

        try:
            return await self._generate_reserved(request, story, branch, on_delta)
        finally:
            if acquired_here:
                self.release_branch(request.story_id, request.branch_id)

    async def _generate_reserved(
        self,
        request: GenerationRequest,
        story: Story,
        branch: Branch,
        on_delta: Callable[[str], Awaitable[None]] | None,
    ) -> GenerationResult:
        """Run one generation after its branch has been exclusively reserved."""

        state_machine = StoryStateMachine(story.status)
        state_sequence: list[StoryStatus] = [story.status]
        self._advance(state_machine, state_sequence, StoryStatus.PLANNING)
        director_context = deepcopy(dict(request.context))
        try:
            plan = await self._generate_plan(director_context)
        except _DirectorRequestFailure:
            return GenerationResult(status=StoryStatus.ERROR, error_code="director_failed")
        if plan is None:
            return GenerationResult(status=StoryStatus.ERROR, error_code="director_invalid")

        policy = evaluate_choice_policy(
            story.choice_frequency,
            request.scenes_since_last_choice,
            plan.choice_suggestion,
        )
        choice = plan.choice_suggestion if policy.decision in ("accept", "force") else None
        final_plan = plan.model_copy(update={"choice_suggestion": choice})
        self._advance(state_machine, state_sequence, StoryStatus.STREAMING)
        writer_context: dict[str, Any] = deepcopy(dict(request.context))
        writer_context["scene_plan"] = final_plan.model_dump(mode="json")
        chunks: list[str] = []
        try:
            async for chunk in self.llm_client.stream_text(
                prompt=WRITER_PROMPT_V1,
                context=writer_context,
            ):
                chunks.append(chunk)
                if on_delta is not None and chunk:
                    await on_delta(chunk)
        except asyncio.CancelledError:
            return GenerationResult(
                status=StoryStatus.ERROR,
                error_code="generation_interrupted",
            )
        except Exception:  # noqa: BLE001 - provider exceptions are redacted at this boundary
            return GenerationResult(status=StoryStatus.ERROR, error_code="writer_failed")

        content = "".join(chunks)
        self._advance(state_machine, state_sequence, StoryStatus.COMMITTING)
        if choice is not None:
            final_status = StoryStatus.WAITING_CHOICE
        elif policy.decision == "pause":
            final_status = StoryStatus.PAUSED
        else:
            final_status = StoryStatus.IDLE
        self._advance(state_machine, state_sequence, final_status)
        parent = (
            self.repository.get_segment(branch.head_segment_id)
            if branch.head_segment_id is not None
            else None
        )
        segment = StorySegment(
            story_id=story.id,
            branch_id=branch.id,
            parent_segment_id=branch.head_segment_id,
            sequence=parent.sequence + 1 if parent is not None else 1,
            content=content,
            summary=final_plan.goal,
            scene_plan=final_plan.model_dump(mode="json"),
            generation_key=request.generation_key,
            status="completed",
        )
        event = GenerationEvent(
            story_id=story.id,
            branch_id=branch.id,
            event_type="committed",
            request_id=request.generation_key,
            duration_ms=0,
            input_token_estimate=0,
            output_size=len(content),
            state_sequence=state_sequence,
        )
        try:
            committed_story, committed_segment = self.repository.commit_generation_bundle(
                story,
                state_sequence,
                segment,
                choice,
                event,
            )
        except (sqlite3.Error, LookupError, ValueError, RuntimeError):
            return GenerationResult(status=StoryStatus.ERROR, error_code="commit_failed")
        return GenerationResult(
            status=committed_story.status,
            segment=committed_segment,
            choice_point=self.repository.get_choice_point_for_segment(committed_segment.id),
            content=committed_segment.content,
        )

    async def _generate_plan(self, context: Mapping[str, object]) -> ScenePlan | None:
        """Validate a Director response, retrying one structural failure only."""
        for _ in range(2):
            try:
                response = await self.llm_client.generate_json(
                    prompt=DIRECTOR_PROMPT_V1,
                    context=context,
                )
                return ScenePlan.model_validate(response)
            except (json.JSONDecodeError, InvalidStructuredResponseError, ValidationError):
                continue
            except (TimeoutError, LLMRequestError) as exc:
                raise _DirectorRequestFailure from exc
            except Exception as exc:
                raise _DirectorRequestFailure from exc
        return None

    @staticmethod
    def _advance(
        state_machine: StoryStateMachine,
        state_sequence: list[StoryStatus],
        target: StoryStatus,
    ) -> None:
        state_machine.transition(target)
        state_sequence.append(target)


def recover_interrupted_generations(repository: StoryRepository) -> list[Story]:
    """Recover persisted in-flight stories without invoking an LLM."""
    return repository.recover_interrupted_generations()


__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "GenerationService",
    "recover_interrupted_generations",
]

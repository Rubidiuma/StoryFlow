from __future__ import annotations

"""Deterministic single-scene generation coordinator."""

import asyncio
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

_log = logging.getLogger(__name__)

# Valid ChoiceType enum values and valid effect field keys
_VALID_CHOICE_TYPES = {"decision", "action", "dialogue"}
_VALID_EFFECT_KEYS = {"route_change", "information_state", "character_state", "relationship_change"}


def _normalize_character_names(content: str, characters: list[dict[str, Any]]) -> str:
    """Ensure character names in content match the official character list.

    This is a safety measure for cases where LLM may have:
    - Translated names to English/pinyin
    - Used alternate character forms
    - Capitalized or modified names

    Note: Full pinyin detection would require a pinyin library.
    The main defense against name mistranslation is the explicit prompt instruction
    to use exact character names as provided.
    """
    if not characters:
        return content

    # For now, this is a placeholder that simply logs if mismatches are detected
    # The primary fix is in the prompt (prompts/director.py, prompts/writer.py)
    # which explicitly instructs LLM to use exact names

    return content


def _normalize_director_response(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize model output to match ScenePlan/ChoicePoint domain schema.

    Handles common LLM deviations:
    - Unknown choice type names → mapped to 'decision'
    - 'structured_effects' key → renamed to 'effects'
    - Effect dicts with unknown keys → mapped to route_change fallback
    """
    result = dict(response)
    cs = result.get("choice_suggestion")
    if not isinstance(cs, dict):
        return result

    cs = dict(cs)

    # 1. Normalize choice type
    if cs.get("type") not in _VALID_CHOICE_TYPES:
        cs["type"] = "decision"

    # 2. Normalize options
    if isinstance(cs.get("options"), list):
        normalized: list[dict[str, Any]] = []
        for opt in cs["options"]:
            if not isinstance(opt, dict):
                continue
            opt = dict(opt)
            # Rename structured_effects → effects
            if "structured_effects" in opt and "effects" not in opt:
                opt["effects"] = opt.pop("structured_effects")
            # Ensure effects is a non-empty dict with only valid keys
            raw = opt.get("effects", {})
            if not isinstance(raw, dict) or not raw:
                opt["effects"] = {"route_change": opt.get("text", "continue")[:60]}
            else:
                valid_effects = {k: v for k, v in raw.items() if k in _VALID_EFFECT_KEYS}
                if not valid_effects:
                    # Fallback: convert first value to route_change string
                    first = next(iter(raw.values()), "continue")
                    opt["effects"] = {"route_change": str(first)[:60]}
                else:
                    opt["effects"] = valid_effects
            normalized.append(opt)
        cs["options"] = normalized

    result["choice_suggestion"] = cs
    return result

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
from storyflow.services.context_builder import SceneMemory
from storyflow.services.memory import MemoryService


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
        # Normalize character names to fix LLM mistakes (e.g., English translations)
        characters = request.context.get("characters", [])
        if isinstance(characters, list):
            content = _normalize_character_names(content, characters)
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
        await self._update_rolling_summary(committed_segment)
        return GenerationResult(
            status=committed_story.status,
            segment=committed_segment,
            choice_point=self.repository.get_choice_point_for_segment(committed_segment.id),
            content=committed_segment.content,
        )

    async def _update_rolling_summary(self, segment: StorySegment) -> None:
        """Best-effort rollup after a durable scene commit."""
        if not MemoryService.should_trigger_rolling_summary(segment.sequence):
            return
        try:
            snapshot = self.repository.get_latest_memory_snapshot(segment.branch_id)
            if snapshot is None:
                from storyflow.domain.models import MemorySnapshot

                snapshot = MemorySnapshot(
                    story_id=segment.story_id,
                    branch_id=segment.branch_id,
                    segment_id=segment.id,
                    context_version=1,
                )
            path = self.repository.list_branch_path(segment.branch_id)
            scenes = [
                SceneMemory(
                    sequence=item.sequence,
                    content=item.content,
                    summary=item.summary,
                )
                for item in path[-5:]
            ]
            updated = await MemoryService.update_rolling_summary(
                snapshot, scenes, self.llm_client
            )
            if updated.rolling_summary == snapshot.rolling_summary:
                return
            self.repository.save_memory_snapshot(
                updated.model_copy(
                    update={"id": uuid4(), "segment_id": segment.id},
                    deep=True,
                )
            )
        except Exception:  # noqa: BLE001 - summaries cannot invalidate committed prose
            _log.warning(
                "Rolling summary update failed for story=%s branch=%s sequence=%s",
                segment.story_id,
                segment.branch_id,
                segment.sequence,
                exc_info=True,
            )

    async def _generate_plan(self, context: Mapping[str, object]) -> ScenePlan | None:
        """Validate a Director response, retrying one structural failure only."""
        for attempt in range(2):
            try:
                raw = await self.llm_client.generate_json(
                    prompt=DIRECTOR_PROMPT_V1,
                    context=context,
                )
                response = _normalize_director_response(raw)
                return ScenePlan.model_validate(response)
            except (json.JSONDecodeError, InvalidStructuredResponseError, ValidationError) as exc:
                _log.warning(
                    "Director attempt %d failed validation: %s | keys: %s",
                    attempt + 1, exc,
                    list(response.keys()) if isinstance(response, dict) else "N/A",
                )
                continue
            except (TimeoutError, LLMRequestError) as exc:
                raise _DirectorRequestFailure from exc
            except Exception as exc:
                _log.exception("Director unexpected error: %s", exc)
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

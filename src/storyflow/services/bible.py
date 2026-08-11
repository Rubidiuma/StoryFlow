"""Structured generation and validation for initial story Bibles."""

import json
import logging
from uuid import UUID

_log = logging.getLogger(__name__)

from pydantic import BaseModel, Field, ValidationError, field_validator

from storyflow.db.repositories import StoryRepository
from storyflow.domain.models import (
    Branch,
    CharacterState,
    Story,
    StoryArc,
    StoryBible,
)
from storyflow.llm.base import InvalidStructuredResponseError, LLMClient, LLMRequestError
from storyflow.prompts.bible import BIBLE_PROMPT_V1


def _visible(value: str) -> str:
    if not value.strip():
        raise ValueError("generated required text must not be blank")
    return value


class GeneratedCharacter(BaseModel):
    """Character fields the model may provide before persistence binds ownership."""

    name: str
    role: str
    location: str = ""
    motivation: str = ""
    known_facts: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)
    alive: bool = True
    version: int = 1

    @field_validator("name", "role")
    @classmethod
    def required_text_is_visible(cls, value: str) -> str:
        return _visible(value)


class GeneratedFirstArc(BaseModel):
    """First-arc fields before story and branch ownership are assigned."""

    goal: str
    conflict: str
    stage: str = "rising"
    exit_conditions: list[str] = Field(default_factory=list)
    status: str = "active"
    summary: str = ""

    @field_validator("goal", "conflict")
    @classmethod
    def required_text_is_visible(cls, value: str) -> str:
        return _visible(value)


class GeneratedBiblePayload(BaseModel):
    """Validated provider-neutral response for the complete initial bundle."""

    world_rules: str
    tone_rules: str
    protagonist_core: str
    required_elements: list[str]
    forbidden_elements: list[str]
    characters: list[GeneratedCharacter] = Field(min_length=1)
    first_arc: GeneratedFirstArc

    @field_validator("world_rules", "tone_rules", "protagonist_core")
    @classmethod
    def required_text_is_visible(cls, value: str) -> str:
        return _visible(value)


def _normalize_bible_response(raw: dict) -> dict:
    """Map common LLM field-name variations to GeneratedBiblePayload schema."""
    r = dict(raw)

    # world_rules aliases
    for alt in ("world_setting", "world_building", "worldRules", "world"):
        if alt in r and "world_rules" not in r:
            r["world_rules"] = r.pop(alt)

    # tone_rules aliases
    for alt in ("tone", "toneRules", "writing_tone", "style_rules", "tone_style"):
        if alt in r and "tone_rules" not in r:
            r["tone_rules"] = r.pop(alt)

    # protagonist_core aliases
    for alt in ("protagonist", "protagonistCore", "character_core", "hero_core",
                "main_character", "protagonist_description"):
        if alt in r and "protagonist_core" not in r:
            r["protagonist_core"] = r.pop(alt)

    # required_elements aliases
    for alt in ("required", "must_include", "required_themes", "required_elements_list"):
        if alt in r and "required_elements" not in r:
            r["required_elements"] = r.pop(alt)
    if "required_elements" not in r:
        r["required_elements"] = []
    if isinstance(r["required_elements"], str):
        r["required_elements"] = [r["required_elements"]]

    # forbidden_elements aliases
    for alt in ("forbidden", "not_allowed", "excluded", "forbidden_elements_list"):
        if alt in r and "forbidden_elements" not in r:
            r["forbidden_elements"] = r.pop(alt)
    if "forbidden_elements" not in r:
        r["forbidden_elements"] = []
    if isinstance(r["forbidden_elements"], str):
        r["forbidden_elements"] = [r["forbidden_elements"]]

    # first_arc aliases
    for alt in ("initial_arc", "opening_arc", "arc", "story_arc", "first_story_arc"):
        if alt in r and "first_arc" not in r:
            r["first_arc"] = r.pop(alt)

    # Normalize first_arc sub-fields
    if isinstance(r.get("first_arc"), dict):
        arc = dict(r["first_arc"])
        for alt in ("arc_goal", "arcGoal", "main_goal", "objective"):
            if alt in arc and "goal" not in arc:
                arc["goal"] = arc.pop(alt)
        for alt in ("main_conflict", "arcConflict", "core_conflict", "central_conflict"):
            if alt in arc and "conflict" not in arc:
                arc["conflict"] = arc.pop(alt)
        r["first_arc"] = arc

    # Normalize characters list
    if isinstance(r.get("characters"), list):
        normalized_chars = []
        for char in r["characters"]:
            if not isinstance(char, dict):
                continue
            c = dict(char)
            # role aliases
            for alt in ("character_role", "type", "character_type"):
                if alt in c and "role" not in c:
                    c["role"] = c.pop(alt)
            if "role" not in c:
                c["role"] = "character"
            normalized_chars.append(c)
        r["characters"] = normalized_chars

    return r


class BibleGenerationValidationError(ValueError):
    """Both structured-generation attempts failed validation or parsing."""


class BibleGenerationRequestError(RuntimeError):
    """The model request failed before it produced a structured response."""


class PersistedBibleBundle(BaseModel):
    """API-facing view of the generated records committed together."""

    bible: StoryBible
    characters: list[CharacterState]
    first_arc: StoryArc
    initial_branch_id: UUID


async def generate_validated_bible(
    story: Story, llm_client: LLMClient
) -> GeneratedBiblePayload:
    """Request and validate a Bible response, retrying one structural failure."""
    context = story.config.model_dump(mode="json")
    for _ in range(2):
        try:
            raw = await llm_client.generate_json(
                prompt=BIBLE_PROMPT_V1,
                context=context,
            )
            response = _normalize_bible_response(raw)
            return GeneratedBiblePayload.model_validate(response)
        except (TimeoutError, LLMRequestError) as exc:
            raise BibleGenerationRequestError("Bible generation request failed") from exc
        except (json.JSONDecodeError, InvalidStructuredResponseError) as exc:
            _log.warning("Bible JSON parse failed: %s", exc)
            continue
        except ValidationError as exc:
            _log.warning("Bible validation failed: %s", exc)
            continue
    raise BibleGenerationValidationError("invalid structured Bible response")


def persist_generated_bible(
    story: Story,
    generated: GeneratedBiblePayload,
    repository: StoryRepository,
) -> PersistedBibleBundle:
    """Bind validated generated data to one root branch and commit the bundle."""
    branch = Branch(story_id=story.id, name="Main")
    bible = StoryBible(
        story_id=story.id,
        world_rules=generated.world_rules,
        tone_rules=generated.tone_rules,
        protagonist_core=generated.protagonist_core,
        required_elements=generated.required_elements,
        forbidden_elements=generated.forbidden_elements,
        version=1,
    )
    characters = [
        CharacterState(
            story_id=story.id,
            branch_id=branch.id,
            **character.model_dump(),
        )
        for character in generated.characters
    ]
    first_arc = StoryArc(
        story_id=story.id,
        branch_id=branch.id,
        **generated.first_arc.model_dump(),
    )
    repository.replace_generated_bible_bundle(
        story,
        bible,
        branch,
        characters,
        first_arc,
    )
    return PersistedBibleBundle(
        bible=bible,
        characters=characters,
        first_arc=first_arc,
        initial_branch_id=branch.id,
    )

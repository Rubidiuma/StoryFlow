"""Structured generation and validation for initial story Bibles."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from storyflow.db.repositories import StoryRepository
from storyflow.domain.models import (
    Branch,
    CharacterState,
    Story,
    StoryArc,
    StoryBible,
)
from storyflow.llm.base import LLMClient
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


class BibleGenerationValidationError(ValueError):
    """Both structured-generation attempts failed validation or parsing."""


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
            response = await llm_client.generate_json(
                prompt=BIBLE_PROMPT_V1,
                context=context,
            )
            return GeneratedBiblePayload.model_validate(response)
        except (TypeError, ValueError):
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

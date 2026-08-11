"""Domain models for StoryFlow per SPEC §8."""
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storyflow.domain.enums import ChoiceFrequency, ChoiceType, StoryStatus


def _naive_utc_now() -> datetime:
    """Return UTC in T02's naive-datetime representation without using deprecated utcnow."""
    return datetime.now(UTC).replace(tzinfo=None)


def _require_non_blank(value: str, message: str) -> str:
    """Reject strings that contain no visible content."""
    if not value.strip():
        raise ValueError(message)
    return value


class StoryConfig(BaseModel):
    """Story configuration input per SPEC §5.1."""

    genre: str = Field(..., description="Story genre: fantasy, scifi, mystery, emotion, or custom")
    structure: str = Field(..., description="Story structure: three_act, hero_journey, etc.")
    world_background: str = Field(
        ..., description="World background description", min_length=1, max_length=2000
    )
    protagonist_desc: str = Field(
        ..., description="Protagonist description", min_length=1, max_length=2000
    )
    important_supporting_characters: str | None = Field(None, max_length=1000)
    style: str = Field(..., description="Writing style", min_length=1, max_length=500)
    choice_frequency: ChoiceFrequency = Field(
        ..., description="少 (few), 中 (medium), or 多 (many) choices per SPEC §5.2"
    )
    required_elements: str | None = Field(None, max_length=1000)
    forbidden_elements: str | None = Field(None, max_length=1000)
    ending_tendency: str | None = Field(None, max_length=1000)

    @field_validator("genre", "structure", "world_background", "protagonist_desc", "style")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        """Required configuration text must contain visible content."""
        return _require_non_blank(value, "StoryConfig required text must not be blank")

    @model_validator(mode="after")
    def check_total_length(self) -> Self:
        """Total input length should not exceed 6000 characters per SPEC §5.1."""
        text_fields = (
            self.genre,
            self.structure,
            self.world_background,
            self.protagonist_desc,
            self.important_supporting_characters,
            self.style,
            self.required_elements,
            self.forbidden_elements,
            self.ending_tendency,
        )
        if sum(len(value) for value in text_fields if value is not None) > 6000:
            raise ValueError("StoryConfig text fields must not exceed 6000 characters")
        return self


class CustomAction(BaseModel):
    """User custom action per SPEC §5.4.

    Custom action must be 1-300 characters.
    """

    text: str = Field(..., min_length=1, max_length=300)


class ChoiceOption(BaseModel):
    """Choice option per SPEC §5.3 and §8."""

    id: UUID = Field(default_factory=uuid4)
    choice_point_id: UUID | None = None
    text: str = Field(..., min_length=1, description="Natural language option text")
    effects: dict[str, Any] = Field(
        ...,
        description="Structured hidden effects: route_change, character_state, information_state, relationship_change",
    )
    position: int = Field(0, description="Visual position in choice list")

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        """Choice text must contain visible content."""
        return _require_non_blank(value, "Choice option text must not be blank")

    @field_validator("effects")
    @classmethod
    def effects_not_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Effects must be non-empty dict."""
        if not v or len(v) == 0:
            raise ValueError("Choice option effects must not be empty")
        return v


class ChoicePoint(BaseModel):
    """Choice point definition per SPEC §5.3 and §8.

    Every choice must have exactly 3 semantically distinct options.
    """

    id: UUID = Field(default_factory=uuid4)
    segment_id: UUID | None = None
    type: ChoiceType = Field(..., description="decision, action, or dialogue")
    reason: str = Field(..., min_length=1, description="Why this choice appears (conflict, milestone, etc.)")
    options: list[ChoiceOption] = Field(..., description="Must contain exactly 3 options")
    status: str = Field("pending", description="pending, committed, selected")
    selected_option_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        """Choice reason must contain visible content."""
        return _require_non_blank(value, "Choice point reason must not be blank")

    @field_validator("options")
    @classmethod
    def exactly_three_options(cls, v: list[ChoiceOption]) -> list[ChoiceOption]:
        """Must have exactly 3 options per SPEC §5.3."""
        if len(v) != 3:
            raise ValueError("ChoicePoint must have exactly 3 options")
        return v

    @field_validator("options")
    @classmethod
    def options_must_be_unique(cls, v: list[ChoiceOption]) -> list[ChoiceOption]:
        """Option texts must be unique."""
        texts = [option.text.strip().casefold() for option in v]
        if len(texts) != len(set(texts)):
            raise ValueError("Choice options must have unique text")
        return v


class ScenePlan(BaseModel):
    """Structured scene plan generated by the director per SPEC §5.2."""

    goal: str = Field(..., min_length=1, description="Goal of the current scene")
    conflict: str = Field(..., min_length=1, description="Current scene conflict")
    beats: list[str] = Field(..., min_length=1, description="Ordered scene beats")
    choice_suggestion: ChoicePoint | None = None
    scene_complete: bool = True

    @field_validator("goal", "conflict")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        """Required scene text must contain non-whitespace content."""
        return _require_non_blank(value, "Scene plan text must not be blank")

    @field_validator("beats")
    @classmethod
    def beats_are_not_blank(cls, beats: list[str]) -> list[str]:
        """Every scene beat must contain non-whitespace content."""
        for beat in beats:
            _require_non_blank(beat, "Scene plan beats must not be blank")
        return beats


class StoryBible(BaseModel):
    """Story bible per SPEC §8.

    Immutable story foundation including world rules, tone, protagonist core, and first story arc.
    """

    story_id: UUID
    world_rules: str = Field(..., description="World rules and constraints")
    tone_rules: str = Field(..., description="Writing tone and style rules")
    protagonist_core: str = Field(..., description="Immutable protagonist core attributes")
    required_elements: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)
    version: int = Field(1, description="Bible version for conflict detection")


class CharacterState(BaseModel):
    """Character state per SPEC §8.

    Tracks character's current state, relationships, knowledge, and status.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    branch_id: UUID
    name: str
    role: str = Field(..., description="protagonist, antagonist, ally, neutral, etc.")
    location: str = Field(default="", description="Current location in story")
    motivation: str = Field(default="", description="Current motivation or goal")
    known_facts: list[str] = Field(default_factory=list, description="Information this character knows")
    secrets: list[str] = Field(default_factory=list, description="Secrets this character holds")
    relationships: dict[str, str] = Field(
        default_factory=dict, description="name -> relationship description"
    )
    alive: bool = Field(True, description="Character alive status")
    version: int = Field(1, description="For optimistic locking")


class Story(BaseModel):
    """Story record per SPEC §8.

    Represents a story instance with configuration and current state.
    """

    model_config = ConfigDict(use_enum_values=False)

    id: UUID = Field(default_factory=uuid4)
    session_id: str = Field(..., description="Anonymous session identifier")
    title: str = Field(default="Untitled", description="Story title")
    status: StoryStatus = Field(default=StoryStatus.DRAFT)
    choice_frequency: ChoiceFrequency
    config: StoryConfig
    current_branch_id: UUID | None = None
    pause_requested: bool = Field(False)
    version: int = Field(1, description="Optimistic lock version")
    created_at: datetime = Field(default_factory=_naive_utc_now)
    updated_at: datetime = Field(default_factory=_naive_utc_now)

    @model_validator(mode="after")
    def choice_frequency_must_match_config(self) -> Self:
        """Keep the compatibility field aligned with the canonical config value."""
        if self.choice_frequency != self.config.choice_frequency:
            raise ValueError("choice_frequency must equal config.choice_frequency")
        return self


class StoryArc(BaseModel):
    """Story arc per SPEC §8.

    Defines current narrative arc with goal, conflict, and exit conditions.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    branch_id: UUID
    goal: str = Field(..., description="Arc's main goal")
    conflict: str = Field(..., description="Central conflict driving this arc")
    stage: str = Field(default="rising", description="exposition, rising, climax, falling, resolution")
    exit_conditions: list[str] = Field(
        default_factory=list, description="Conditions for arc completion"
    )
    status: str = Field("active", description="active, completed, abandoned")
    summary: str = Field(default="", description="Summary of arc progress")


class StorySegment(BaseModel):
    """Story segment (scene) per SPEC §8.

    A single scene of generated story content.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    branch_id: UUID
    parent_segment_id: UUID | None = None
    sequence: int = Field(..., description="Order in story")
    content: str = Field(..., description="500-1000 character story text")
    summary: str = Field(default="", description="Scene summary for context")
    scene_plan: dict[str, Any] | None = None
    generation_key: str = Field(..., description="Idempotent key for generation")
    status: str = Field("pending", description="pending, completed, failed")
    created_at: datetime = Field(default_factory=_naive_utc_now)

    @model_validator(mode="after")
    def parent_must_not_be_self(self) -> Self:
        """Reject an immediate lineage cycle at the domain boundary."""
        if self.parent_segment_id == self.id:
            raise ValueError("a story segment cannot be its own parent")
        return self

    @field_validator("content")
    @classmethod
    def content_length(cls, v: str) -> str:
        """Content should be 500-1000 characters per SPEC §5.2."""
        # Note: This is a guideline, not hard constraint; service layer enforces
        return v


class Branch(BaseModel):
    """Story branch per SPEC §8.

    Represents alternative story path from a historical choice.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    parent_branch_id: UUID | None = None
    fork_choice_id: UUID | None = None
    fork_segment_id: UUID | None = None
    name: str = Field(default="Branch", description="User-friendly branch name")
    head_segment_id: UUID | None = None
    created_at: datetime = Field(default_factory=_naive_utc_now)


class MemorySnapshot(BaseModel):
    """Memory snapshot per SPEC §8.

    Captures story state at a specific point for branching and recovery.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    branch_id: UUID
    segment_id: UUID | None = None
    characters: list[CharacterState] = Field(default_factory=list)
    active_threads: list[str] = Field(default_factory=list, description="Active plot threads")
    foreshadowing: dict[str, str] = Field(
        default_factory=dict,
        description="Foreshadowing clues: id -> description",
    )
    rolling_summary: str = Field(default="", description="Compressed summary of recent events")
    context_version: int = Field(1, description="Version of context budget constraints")


class GenerationEvent(BaseModel):
    """Generation event log per SPEC §8.

    Logs each generation request for observability.
    """

    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    branch_id: UUID | None = Field(
        ..., description="Branch for generation work; absent for aggregate-level recovery"
    )
    event_type: str = Field(..., description="planning, streaming, committed, error, etc.")
    request_id: str = Field(..., description="Unique request identifier for tracing")
    duration_ms: int = Field(0, description="Duration in milliseconds")
    model: str | None = None
    input_token_estimate: int = Field(0)
    output_size: int = Field(0)
    error_code: str | None = None
    state_sequence: list[StoryStatus] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_naive_utc_now)

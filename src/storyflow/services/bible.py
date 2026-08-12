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
            # Ensure list fields are actually lists (model sometimes returns strings)
            for list_field in ("known_facts", "secrets"):
                val = c.get(list_field)
                if isinstance(val, str):
                    c[list_field] = [val] if val.strip() else []
                elif val is None:
                    c[list_field] = []
            # Ensure relationships is always a dict, not a string
            rel = c.get("relationships")
            if isinstance(rel, str):
                c["relationships"] = {rel: rel} if rel.strip() else {}
            elif not isinstance(rel, dict):
                c["relationships"] = {}
            normalized_chars.append(c)
        r["characters"] = normalized_chars

    # Normalize first_arc sub-fields - ensure exit_conditions is a list
    if isinstance(r.get("first_arc"), dict):
        arc = dict(r["first_arc"])
        exit_cond = arc.get("exit_conditions")
        if isinstance(exit_cond, str):
            arc["exit_conditions"] = [exit_cond] if exit_cond.strip() else []
        elif not isinstance(exit_cond, list):
            arc["exit_conditions"] = []
        r["first_arc"] = arc

    return r


def _first_str(d: dict, *keys: str, default: str = "") -> str:
    """Return the first non-empty string value from any of the given keys."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def _lenient_bible_fallback(raw: dict, story: "Story") -> "GeneratedBiblePayload":
    """Extract whatever we can from the model response; fill gaps from story config."""
    cfg = story.config

    # Collect all string values from the response as a pool of text
    all_text = " ".join(
        str(v) for v in raw.values() if isinstance(v, (str, int, float))
    ) or str(raw)

    world_rules = _first_str(raw,
        "world_rules", "world_setting", "world_building", "world",
        "世界规则", "世界设定",
        default=f"{cfg.world_background}") or "故事世界的基本规则与设定。"

    tone_rules = _first_str(raw,
        "tone_rules", "tone", "writing_tone", "style",
        "基调规则", "文风",
        default=cfg.style) or "克制而明亮的叙事风格。"

    protagonist_core = _first_str(raw,
        "protagonist_core", "protagonist", "character_core", "hero",
        "主角核心", "主角",
        default=cfg.protagonist_desc) or "主角的核心性格与不变的价值观。"

    # required/forbidden elements
    def _to_list(val: object) -> list[str]:
        if isinstance(val, list):
            return [str(x) for x in val if str(x).strip()]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    required = _to_list(raw.get("required_elements") or raw.get("required") or [])
    forbidden = _to_list(raw.get("forbidden_elements") or raw.get("forbidden") or [])

    # Characters - try to extract, fall back to minimal protagonist
    chars_raw = raw.get("characters") or raw.get("角色") or []
    if isinstance(chars_raw, list) and chars_raw:
        chars = []
        for c in chars_raw:
            if isinstance(c, dict) and c.get("name"):
                chars.append(GeneratedCharacter(
                    name=str(c.get("name", "主角")),
                    role=str(c.get("role") or c.get("character_role") or "protagonist"),
                    location=str(c.get("location", "")),
                    motivation=str(c.get("motivation", "")),
                ))
        if not chars:
            chars = [GeneratedCharacter(name="主角", role="protagonist",
                                        motivation=cfg.protagonist_desc[:200])]
    else:
        chars = [GeneratedCharacter(name="主角", role="protagonist",
                                    motivation=cfg.protagonist_desc[:200])]

    # first_arc
    arc_raw = (raw.get("first_arc") or raw.get("initial_arc") or
               raw.get("arc") or raw.get("story_arc") or {})
    if isinstance(arc_raw, dict):
        arc_goal = _first_str(arc_raw, "goal", "arc_goal", "objective",
                              default="") or "推进故事主线，揭开核心谜题。"
        arc_conflict = _first_str(arc_raw, "conflict", "main_conflict", "core_conflict",
                                  default="") or "主角面临的核心阻碍与内外冲突。"
    else:
        arc_goal = "推进故事主线，揭开核心谜题。"
        arc_conflict = "主角面临的核心阻碍与内外冲突。"

    first_arc = GeneratedFirstArc(goal=arc_goal, conflict=arc_conflict)

    return GeneratedBiblePayload(
        world_rules=world_rules,
        tone_rules=tone_rules,
        protagonist_core=protagonist_core,
        required_elements=required,
        forbidden_elements=forbidden,
        characters=chars,
        first_arc=first_arc,
    )


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
    from storyflow.services.naming import get_protagonist_name

    context = story.config.model_dump(mode="json")

    # Extract or generate protagonist name and add to context
    protagonist_name = get_protagonist_name(story.config.protagonist_desc)
    context["protagonist_name"] = protagonist_name
    _log.debug("Using protagonist name: %s", protagonist_name)

    last_raw: dict = {}
    for attempt in range(2):
        try:
            raw = await llm_client.generate_json(
                prompt=BIBLE_PROMPT_V1,
                context=context,
            )
            last_raw = raw
            response = _normalize_bible_response(raw)
            return GeneratedBiblePayload.model_validate(response)
        except (TimeoutError, LLMRequestError) as exc:
            raise BibleGenerationRequestError("Bible generation request failed") from exc
        except (json.JSONDecodeError, InvalidStructuredResponseError) as exc:
            _log.warning("Bible JSON parse failed (attempt %d): %s", attempt + 1, exc)
            continue
        except ValidationError as exc:
            _log.warning("Bible validation failed (attempt %d): %s | keys: %s",
                         attempt + 1, exc, list(last_raw.keys()))
            continue

    # Last resort: build a minimal valid payload from whatever the model returned
    _log.warning("Bible validation failed twice; attempting lenient fallback from: %s",
                 list(last_raw.keys()))
    return _lenient_bible_fallback(last_raw, story)


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

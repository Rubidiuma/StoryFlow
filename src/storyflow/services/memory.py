from __future__ import annotations

"""Pure parsing and application of structured story memory updates."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from storyflow.domain.models import CharacterState, MemorySnapshot, StoryArc, StoryBible
from storyflow.services.context_builder import ForeshadowingMemory, ForeshadowingStatus, SceneMemory

_UPDATE_FIELDS = frozenset(
    {"characters", "active_threads", "foreshadowing", "rolling_summary"}
)
_FORESHADOWING_FIELDS = frozenset({"id", "description", "status"})
_FORESHADOWING_STATUSES = frozenset({"planted", "active", "resolved", "abandoned"})
_CHOICE_EFFECT_FIELDS = frozenset(
    {"route_change", "character_state", "information_state", "relationship_change"}
)
_CHARACTER_PATCH_FIELDS = frozenset(
    {
        "name",
        "role",
        "location",
        "motivation",
        "known_facts",
        "secrets",
        "relationships",
        "alive",
    }
)
_INFORMATION_FIELDS = frozenset({"active_threads", "foreshadowing"})


class _CharacterUpdatePayload(BaseModel):
    """A complete, strict character replacement that cannot invoke domain defaults."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: UUID = Field(strict=False)
    story_id: UUID = Field(strict=False)
    branch_id: UUID = Field(strict=False)
    name: str
    role: str
    location: str
    motivation: str
    known_facts: list[str]
    secrets: list[str]
    relationships: dict[str, str]
    alive: bool
    version: int


@dataclass(frozen=True, slots=True)
class MemoryUpdate:
    """Validated optional changes for one memory snapshot."""

    characters: list[CharacterState] | None = None
    active_threads: list[str] | None = None
    foreshadowing: list[ForeshadowingMemory] | None = None
    rolling_summary: str | None = None


class MemoryService:
    """Validate and apply memory updates without persistence or external calls."""

    @staticmethod
    def parse_update(payload: Mapping[str, object]) -> MemoryUpdate:
        """Parse a provider-neutral mapping into typed memory changes."""
        unknown_fields = set(payload) - _UPDATE_FIELDS
        if unknown_fields:
            raise ValueError(f"memory update has unknown fields: {sorted(unknown_fields)}")

        characters = None
        if "characters" in payload:
            characters = []
            for item in _require_list(payload["characters"], "characters"):
                try:
                    parsed = _CharacterUpdatePayload.model_validate(item)
                    character = CharacterState.model_validate(parsed.model_dump())
                except ValueError as exc:
                    raise ValueError("characters contains a malformed character") from exc
                characters.append(character.model_copy(deep=True))

        active_threads = None
        if "active_threads" in payload:
            raw_threads = _require_list(payload["active_threads"], "active_threads")
            if not all(isinstance(item, str) for item in raw_threads):
                raise ValueError("active_threads must contain only strings")
            active_threads = cast(list[str], raw_threads.copy())

        foreshadowing = None
        if "foreshadowing" in payload:
            foreshadowing = []
            for raw_item in _require_list(payload["foreshadowing"], "foreshadowing"):
                if not isinstance(raw_item, Mapping):
                    raise ValueError(  # noqa: TRY004 - parser contract requires ValueError
                        "foreshadowing entries must be mappings"
                    )
                item = cast(Mapping[str, object], raw_item)
                if set(item) != _FORESHADOWING_FIELDS:
                    raise ValueError(
                        "foreshadowing entries require exactly id, description, and status"
                    )
                clue_id = item["id"]
                description = item["description"]
                status = item["status"]
                if not isinstance(clue_id, str) or not isinstance(description, str):
                    raise ValueError(  # noqa: TRY004 - parser contract requires ValueError
                        "foreshadowing id and description must be strings"
                    )
                if not isinstance(status, str) or status not in _FORESHADOWING_STATUSES:
                    raise ValueError(f"foreshadowing has unknown status: {status!r}")
                foreshadowing.append(
                    ForeshadowingMemory(
                        id=clue_id,
                        description=description,
                        status=cast(ForeshadowingStatus, status),
                    )
                )

        rolling_summary = None
        if "rolling_summary" in payload:
            raw_summary = payload["rolling_summary"]
            if not isinstance(raw_summary, str):
                raise ValueError("rolling_summary must be a string")
            rolling_summary = raw_summary

        return MemoryUpdate(
            characters=characters,
            active_threads=active_threads,
            foreshadowing=foreshadowing,
            rolling_summary=rolling_summary,
        )

    @staticmethod
    def apply_update(snapshot: MemorySnapshot, update: MemoryUpdate) -> MemorySnapshot:
        """Return a detached, incremented snapshot with the supplied changes applied."""
        result = snapshot.model_copy(deep=True)
        if update.characters is not None:
            result.characters = [character.model_copy(deep=True) for character in update.characters]
        if update.active_threads is not None:
            result.active_threads = update.active_threads.copy()
        if update.foreshadowing is not None:
            for clue in update.foreshadowing:
                if clue.status in ("planted", "active"):
                    result.foreshadowing[clue.id] = clue.description
                else:
                    result.foreshadowing.pop(clue.id, None)
        if update.rolling_summary is not None:
            result.rolling_summary = update.rolling_summary
        result.context_version += 1
        return result

    @staticmethod
    def apply_choice_effects(
        snapshot: MemorySnapshot, effects: Mapping[str, object]
    ) -> MemorySnapshot:
        """Merge one normalized choice effect mapping into a detached snapshot."""
        unknown_fields = set(effects) - _CHOICE_EFFECT_FIELDS
        if unknown_fields:
            raise ValueError(f"choice effects have unknown fields: {sorted(unknown_fields)}")
        if not effects:
            raise ValueError("choice effects must not be empty")

        result = snapshot.model_copy(deep=True)
        changed_characters: set[int] = set()
        if "route_change" in effects:
            _append_unique(result.active_threads, _effect_strings(effects["route_change"], "route_change"))
        if "information_state" in effects:
            _merge_information(result, effects["information_state"])
        if "character_state" in effects:
            _merge_character_state(result, effects["character_state"], changed_characters)
        if "relationship_change" in effects:
            _merge_relationships(result, effects["relationship_change"], changed_characters)

        for index in changed_characters:
            character = result.characters[index]
            result.characters[index] = character.model_copy(
                update={"version": character.version + 1}, deep=True
            )
        result.context_version += 1
        return result

    # ─── T13: Rolling summary and arc management ──────────────────────────────

    @staticmethod
    def should_trigger_rolling_summary(scene_sequence: int) -> bool:
        """Return True when scene_sequence is a positive multiple of 5."""
        return scene_sequence > 0 and scene_sequence % 5 == 0

    @staticmethod
    def should_generate_next_arc(arc: StoryArc) -> bool:
        """Return True when the current arc has been completed."""
        return arc.status == "completed"

    @staticmethod
    async def update_rolling_summary(
        snapshot: MemorySnapshot,
        scenes: Sequence[SceneMemory],
        llm_client: object,
    ) -> MemorySnapshot:
        """Compress recent scenes into a new rolling_summary via the LLM.

        On any failure (LLM error, malformed response), returns original snapshot unchanged.
        """
        from storyflow.prompts.memory import ROLLING_SUMMARY_PROMPT_V1

        try:
            response = await llm_client.generate_json(  # type: ignore[union-attr]
                prompt=ROLLING_SUMMARY_PROMPT_V1,
                context={
                    "rolling_summary": snapshot.rolling_summary,
                    "scenes": [
                        {"sequence": s.sequence, "content": s.content, "summary": s.summary}
                        for s in scenes
                    ],
                },
            )
            new_summary = response.get("rolling_summary")
            if not isinstance(new_summary, str):
                return snapshot
        except Exception:  # noqa: BLE001 – best-effort; committed content must survive
            return snapshot
        return snapshot.model_copy(
            update={
                "rolling_summary": new_summary,
                "context_version": snapshot.context_version + 1,
            }
        )

    @staticmethod
    async def generate_next_arc(
        story_id: UUID,
        branch_id: UUID,
        bible: StoryBible,
        snapshot: MemorySnapshot,
        llm_client: object,
    ) -> StoryArc:
        """Generate the next story arc via LLM and return it with story/branch ids set."""
        from storyflow.prompts.memory import NEXT_ARC_PROMPT_V1

        response = await llm_client.generate_json(  # type: ignore[union-attr]
            prompt=NEXT_ARC_PROMPT_V1,
            context={
                "world_rules": bible.world_rules,
                "tone_rules": bible.tone_rules,
                "protagonist_core": bible.protagonist_core,
                "active_threads": snapshot.active_threads,
                "rolling_summary": snapshot.rolling_summary,
            },
        )
        goal = response.get("goal", "")
        conflict = response.get("conflict", "")
        stage = response.get("stage", "rising")
        exit_conditions = response.get("exit_conditions", [])
        summary = response.get("summary", "")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("next arc response missing required 'goal'")
        if not isinstance(conflict, str) or not conflict.strip():
            raise ValueError("next arc response missing required 'conflict'")
        return StoryArc(
            story_id=story_id,
            branch_id=branch_id,
            goal=goal,
            conflict=conflict,
            stage=stage if isinstance(stage, str) else "rising",
            exit_conditions=exit_conditions if isinstance(exit_conditions, list) else [],
            status="active",
            summary=summary if isinstance(summary, str) else "",
        )


def _require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 - parser contract requires ValueError
            f"{field} must be a list"
        )
    return value


def _effect_strings(value: object, field: str) -> list[str]:
    raw_values: Sequence[object]
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        raise ValueError(  # noqa: TRY004 - parser contract exposes one validation type
            f"{field} must be a string or list of strings"
        )
    values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain visible strings")
        values.append(item)
    return values


def _append_unique(target: list[str], additions: Sequence[str]) -> None:
    for item in additions:
        if item not in target:
            target.append(item)


def _merge_information(snapshot: MemorySnapshot, value: object) -> None:
    if isinstance(value, (str, list)):
        _append_unique(snapshot.active_threads, _effect_strings(value, "information_state"))
        return
    if not isinstance(value, Mapping):
        raise ValueError(  # noqa: TRY004 - parser contract exposes one validation type
            "information_state must be text, a list, or a mapping"
        )
    unknown_fields = set(value) - _INFORMATION_FIELDS
    if unknown_fields:
        raise ValueError(
            f"information_state has unknown fields: {sorted(unknown_fields)}"
        )
    if "active_threads" in value:
        _append_unique(
            snapshot.active_threads,
            _effect_strings(value["active_threads"], "information_state.active_threads"),
        )
    if "foreshadowing" in value:
        clues = value["foreshadowing"]
        if not isinstance(clues, Mapping):
            raise ValueError("information_state.foreshadowing must be a mapping")
        for clue_id, description in clues.items():
            if (
                not isinstance(clue_id, str)
                or not clue_id.strip()
                or not isinstance(description, str)
                or not description.strip()
            ):
                raise ValueError("foreshadowing requires visible string keys and values")
            snapshot.foreshadowing[clue_id] = description


def _merge_character_state(
    snapshot: MemorySnapshot,
    value: object,
    changed_characters: set[int],
) -> None:
    patches: list[object]
    if isinstance(value, Mapping):
        patches = [value]
    elif isinstance(value, list):
        patches = value
    else:
        raise ValueError(  # noqa: TRY004 - parser contract exposes one validation type
            "character_state must be a mapping or list of mappings"
        )
    for raw_patch in patches:
        if not isinstance(raw_patch, Mapping):
            raise ValueError(  # noqa: TRY004 - parser contract exposes one validation type
                "character_state entries must be mappings"
            )
        patch = dict(raw_patch)
        unknown_fields = set(patch) - _CHARACTER_PATCH_FIELDS
        if unknown_fields:
            raise ValueError(
                f"character_state has unknown fields: {sorted(unknown_fields)}"
            )
        name = patch.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("character_state requires a visible name")
        index = _character_index(snapshot, name)
        if index is None:
            role = patch.get("role")
            if not isinstance(role, str) or not role.strip():
                raise ValueError("a new character_state requires a visible role")
            try:
                created = CharacterState.model_validate(
                    {
                        "story_id": snapshot.story_id,
                        "branch_id": snapshot.branch_id,
                        **deepcopy(patch),
                    }
                )
            except ValueError as exc:
                raise ValueError("character_state contains malformed fields") from exc
            snapshot.characters.append(created)
            continue

        character = snapshot.characters[index]
        merged = character.model_dump()
        for field, field_value in patch.items():
            if field == "name":
                continue
            if field in ("known_facts", "secrets"):
                additions = _effect_strings(field_value, f"character_state.{field}")
                current = cast(list[str], merged[field])
                _append_unique(current, additions)
            elif field == "relationships":
                if not isinstance(field_value, Mapping) or not all(
                    isinstance(target, str)
                    and target.strip()
                    and isinstance(relation, str)
                    and relation.strip()
                    for target, relation in field_value.items()
                ):
                    raise ValueError("character_state.relationships must map visible strings")
                relationships = cast(dict[str, str], merged["relationships"])
                relationships.update(cast(Mapping[str, str], field_value))
            else:
                merged[field] = deepcopy(field_value)
        try:
            snapshot.characters[index] = CharacterState.model_validate(merged)
        except ValueError as exc:
            raise ValueError("character_state contains malformed fields") from exc
        changed_characters.add(index)


def _merge_relationships(
    snapshot: MemorySnapshot,
    value: object,
    changed_characters: set[int],
) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(  # noqa: TRY004 - parser contract exposes one validation type
            "relationship_change must be a mapping"
        )
    for character_name, raw_relationships in value.items():
        if not isinstance(character_name, str) or not character_name.strip():
            raise ValueError("relationship_change requires visible character names")
        if not isinstance(raw_relationships, Mapping) or not all(
            isinstance(target, str)
            and target.strip()
            and isinstance(relation, str)
            and relation.strip()
            for target, relation in raw_relationships.items()
        ):
            raise ValueError("relationship_change must map visible relationship strings")
        index = _character_index(snapshot, character_name)
        if index is None:
            raise ValueError("relationship_change names an unknown character")
        character = snapshot.characters[index]
        relationships = character.relationships.copy()
        relationships.update(cast(Mapping[str, str], raw_relationships))
        snapshot.characters[index] = character.model_copy(
            update={"relationships": relationships}, deep=True
        )
        changed_characters.add(index)


def _character_index(snapshot: MemorySnapshot, name: str) -> int | None:
    normalized = name.strip().casefold()
    return next(
        (
            index
            for index, character in enumerate(snapshot.characters)
            if character.name.strip().casefold() == normalized
        ),
        None,
    )




def validate_arc_not_contradicting_facts(
    bible: StoryBible,
    arc_payload: Mapping[str, object],
) -> None:
    """Raise ValueError if the arc payload contradicts the bible's world rules.

    Heuristic: extract verbs forbidden by world_rules (via cannot/must not/never patterns)
    and check whether the arc goal or conflict invokes those verbs in any common form.
    """
    import re

    goal = str(arc_payload.get("goal", ""))
    conflict = str(arc_payload.get("conflict", ""))
    arc_text = (goal + " " + conflict).casefold()

    rules_text = bible.world_rules.casefold()

    negated_verbs: list[str] = re.findall(
        r"(?:cannot|can not|may not|must not|never)\s+be\s+(\w+)", rules_text
    )
    negated_verbs += re.findall(
        r"(?:cannot|can not|may not|must not|never)\s+(\w+)", rules_text
    )

    for verb in negated_verbs:
        if not verb or len(verb) <= 2:
            continue
        # Build candidate forms: exact, strip -ed suffix, strip -d suffix
        forms = {verb}
        if verb.endswith("ed") and len(verb) > 4:
            forms.add(verb[:-2])   # melted → melt
        if verb.endswith("d") and len(verb) > 3:
            forms.add(verb[:-1])   # moved → move
        if any(f in arc_text for f in forms):
            raise ValueError(
                f"arc contradicts world rules: '{verb}' is explicitly forbidden but appears in arc"
            )

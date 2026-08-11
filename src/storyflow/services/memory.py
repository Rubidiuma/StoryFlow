"""Pure parsing and application of structured story memory updates."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from storyflow.domain.models import CharacterState, MemorySnapshot
from storyflow.services.context_builder import ForeshadowingMemory, ForeshadowingStatus

_UPDATE_FIELDS = frozenset(
    {"characters", "active_threads", "foreshadowing", "rolling_summary"}
)
_FORESHADOWING_FIELDS = frozenset({"id", "description", "status"})
_FORESHADOWING_STATUSES = frozenset({"planted", "active", "resolved", "abandoned"})


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
                    character = CharacterState.model_validate(item)
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


def _require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 - parser contract requires ValueError
            f"{field} must be a list"
        )
    return value

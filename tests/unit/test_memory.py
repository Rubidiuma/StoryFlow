"""Unit tests for pure parsing and application of structured memory updates."""

from copy import deepcopy

import pytest

from storyflow.domain.models import CharacterState, MemorySnapshot
from storyflow.prompts.memory import MEMORY_UPDATE_PROMPT_V1
from storyflow.services.context_builder import ForeshadowingMemory
from storyflow.services.memory import MemoryService, MemoryUpdate


def test_valid_payload_parses_into_typed_memory_update_without_mutating_input():
    """Losing validated fields or retaining caller aliases would corrupt later snapshots."""
    payload: dict[str, object] = {
        "characters": [
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "story_id": "00000000-0000-0000-0000-000000000001",
                "branch_id": "00000000-0000-0000-0000-000000000002",
                "name": "Mira",
                "role": "engineer",
                "location": "eastern seal",
                "motivation": "keep the city aloft",
                "known_facts": ["the seal is cracked"],
                "secrets": [],
                "relationships": {},
                "alive": True,
                "version": 1,
            }
        ],
        "active_threads": ["Repair the eastern seal"],
        "foreshadowing": [
            {"id": "lens", "description": "The lens hums at midnight", "status": "active"},
            {"id": "map", "description": "The map was false", "status": "resolved"},
        ],
        "rolling_summary": "Mira reached the eastern seal.",
    }
    before = deepcopy(payload)

    update = MemoryService.parse_update(payload)

    assert update.characters is not None
    assert len(update.characters) == 1
    assert update.characters[0].name == "Mira"
    assert update.characters[0].known_facts == ["the seal is cracked"]
    assert update.active_threads == ["Repair the eastern seal"]
    assert update.foreshadowing is not None
    assert [item.status for item in update.foreshadowing] == ["active", "resolved"]
    assert update.rolling_summary == "Mira reached the eastern seal."
    assert payload == before
    assert MemoryService.parse_update({}) == MemoryUpdate()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"unexpected": []}, "unknown fields"),
        ({"characters": "not-a-list"}, "characters"),
        ({"active_threads": "not-a-list"}, "active_threads"),
        ({"active_threads": ["valid", 4]}, "active_threads"),
        (
            {
                "foreshadowing": [
                    {"id": "lens", "description": "A cracked lens", "status": "forgotten"}
                ]
            },
            "foreshadowing",
        ),
        (
            {
                "foreshadowing": [
                    {"id": "lens", "description": "A cracked lens", "status": ["active"]}
                ]
            },
            "foreshadowing",
        ),
        ({"foreshadowing": [{"id": "lens", "status": "active"}]}, "foreshadowing"),
        ({"rolling_summary": 9}, "rolling_summary"),
        (
            {
                "characters": [
                    {
                        "story_id": "00000000-0000-0000-0000-000000000001",
                        "branch_id": "00000000-0000-0000-0000-000000000002",
                        "name": "Mira",
                        "role": "engineer",
                        "location": "eastern seal",
                        "motivation": "keep the city aloft",
                        "known_facts": [],
                        "secrets": [],
                        "relationships": {},
                        "alive": True,
                        "version": 1,
                    }
                ]
            },
            "characters",
        ),
        (
            {
                "characters": [
                    {
                        "id": "00000000-0000-0000-0000-000000000003",
                        "story_id": "00000000-0000-0000-0000-000000000001",
                        "branch_id": "00000000-0000-0000-0000-000000000002",
                        "name": "Mira",
                        "role": "engineer",
                        "location": "eastern seal",
                        "motivation": "keep the city aloft",
                        "known_facts": [],
                        "secrets": [],
                        "relationships": {},
                        "alive": "yes",
                        "version": 1,
                    }
                ]
            },
            "characters",
        ),
        (
            {
                "characters": [
                    {
                        "id": "00000000-0000-0000-0000-000000000003",
                        "story_id": "00000000-0000-0000-0000-000000000001",
                        "branch_id": "00000000-0000-0000-0000-000000000002",
                        "name": "Mira",
                        "role": "engineer",
                        "location": "eastern seal",
                        "motivation": "keep the city aloft",
                        "known_facts": [],
                        "secrets": [],
                        "relationships": {},
                        "alive": True,
                        "version": 1,
                        "unexpected": "field",
                    }
                ]
            },
            "characters",
        ),
    ],
)
def test_malformed_memory_update_fields_raise_clear_value_errors(
    payload: dict[str, object], message: str
):
    """Malformed model output must not become a partially trusted memory update."""
    with pytest.raises(ValueError, match=message):
        MemoryService.parse_update(payload)


def test_apply_update_returns_incremented_snapshot_with_replacements_and_clue_merge():
    """In-place updates, stale versions, or wrong clue lifecycle handling break recovery."""
    old_character = CharacterState(
        id="00000000-0000-0000-0000-000000000003",
        story_id="00000000-0000-0000-0000-000000000001",
        branch_id="00000000-0000-0000-0000-000000000002",
        name="Mira",
        role="engineer",
        location="western ring",
    )
    snapshot = MemorySnapshot(
        id="00000000-0000-0000-0000-000000000004",
        story_id="00000000-0000-0000-0000-000000000001",
        branch_id="00000000-0000-0000-0000-000000000002",
        segment_id="00000000-0000-0000-0000-000000000005",
        characters=[old_character],
        active_threads=["Reach the eastern seal", "Find the map"],
        foreshadowing={
            "lens": "The lens is quiet",
            "map": "The map may be false",
            "bell": "A bell hangs below the city",
        },
        rolling_summary="Mira crossed the western ring.",
        context_version=4,
    )
    replacement_character = old_character.model_copy(
        update={"location": "eastern seal", "known_facts": ["the lens hums"]},
        deep=True,
    )
    update = MemoryUpdate(
        characters=[replacement_character],
        active_threads=["Repair the eastern seal"],
        foreshadowing=[
            ForeshadowingMemory(
                id="lens", description="The lens hums at midnight", status="active"
            ),
            ForeshadowingMemory(
                id="map", description="The map was false", status="resolved"
            ),
            ForeshadowingMemory(
                id="door", description="A door appears at dawn", status="planted"
            ),
        ],
        rolling_summary="Mira reached the eastern seal.",
    )
    before = snapshot.model_dump(mode="json")

    result = MemoryService.apply_update(snapshot, update)

    assert result is not snapshot
    assert result.id == snapshot.id
    assert result.story_id == snapshot.story_id
    assert result.branch_id == snapshot.branch_id
    assert result.segment_id == snapshot.segment_id
    assert result.context_version == 5
    assert [character.location for character in result.characters] == ["eastern seal"]
    assert result.active_threads == ["Repair the eastern seal"]
    assert result.foreshadowing == {
        "lens": "The lens hums at midnight",
        "bell": "A bell hangs below the city",
        "door": "A door appears at dawn",
    }
    assert result.rolling_summary == "Mira reached the eastern seal."
    assert snapshot.model_dump(mode="json") == before

    replacement_character.location = "caller mutation"
    update.active_threads.append("caller mutation")
    assert result.characters[0].location == "eastern seal"
    assert result.active_threads == ["Repair the eastern seal"]


def test_apply_partial_update_deep_copies_unsupplied_snapshot_fields():
    """A new snapshot must not share mutable nested state with the original snapshot."""
    snapshot = MemorySnapshot(
        story_id="00000000-0000-0000-0000-000000000001",
        branch_id="00000000-0000-0000-0000-000000000002",
        characters=[
            CharacterState(
                story_id="00000000-0000-0000-0000-000000000001",
                branch_id="00000000-0000-0000-0000-000000000002",
                name="Mira",
                role="engineer",
                known_facts=["the seal is cracked"],
            )
        ],
        active_threads=["Repair the seal"],
        foreshadowing={"lens": "The lens hums"},
        context_version=1,
    )

    result = MemoryService.apply_update(snapshot, MemoryUpdate(rolling_summary="At the seal."))
    result.characters[0].known_facts.append("result-only fact")
    result.active_threads.append("result-only thread")
    result.foreshadowing["door"] = "result-only clue"

    assert snapshot.characters[0].known_facts == ["the seal is cracked"]
    assert snapshot.active_threads == ["Repair the seal"]
    assert snapshot.foreshadowing == {"lens": "The lens hums"}
    assert result.context_version == 2


def test_versioned_memory_prompt_exposes_the_structured_update_contract():
    """An unversioned or schema-ambiguous prompt cannot feed the deterministic parser safely."""
    assert MEMORY_UPDATE_PROMPT_V1.startswith("[memory_update_v1]")
    assert "characters" in MEMORY_UPDATE_PROMPT_V1
    assert "active_threads" in MEMORY_UPDATE_PROMPT_V1
    assert "foreshadowing" in MEMORY_UPDATE_PROMPT_V1
    assert "rolling_summary" in MEMORY_UPDATE_PROMPT_V1
    assert "planted, active, resolved, or abandoned" in MEMORY_UPDATE_PROMPT_V1

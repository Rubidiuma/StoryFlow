"""T11 integration coverage for atomic preset and custom choice submission."""

from __future__ import annotations

import warnings
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.",
        category=StarletteDeprecationWarning,
    )
    from fastapi.testclient import TestClient

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import ChoiceFrequency, ChoiceType, StoryStatus
from storyflow.domain.models import (
    Branch,
    CharacterState,
    ChoiceOption,
    ChoicePoint,
    MemorySnapshot,
    Story,
    StoryConfig,
    StorySegment,
)
from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app


def make_runtime(
    tmp_path: Path,
    *,
    status: StoryStatus = StoryStatus.WAITING_CHOICE,
    effects: dict[str, Any] | None = None,
    llm_client: FakeLLMClient | None = None,
) -> tuple[Database, StoryRepository, Story, Branch, StorySegment, ChoicePoint, TestClient]:
    """Create one persisted current choice and an earlier memory snapshot."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = repository.create_story(
        Story(
            session_id="choice-session",
            status=status,
            choice_frequency=ChoiceFrequency.MEDIUM,
            config=StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="Floating islands drift above a storm.",
                protagonist_desc="Mira maps roads hidden in the clouds.",
                important_supporting_characters=None,
                style="lyrical",
                choice_frequency=ChoiceFrequency.MEDIUM,
                required_elements=None,
                forbidden_elements=None,
                ending_tendency=None,
            ),
            pause_requested=False,
            version=7,
        )
    )
    branch = repository.create_branch(Branch(story_id=story.id, name="Main"))
    story = repository.set_current_branch(story.id, branch.id)
    segment = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        sequence=1,
        content="Mira reaches a fork above the storm.",
        summary="Mira reaches the fork.",
        generation_key="choice-scene",
        status="completed",
    )
    preset_effects = effects or {
        "route_change": "enter_tavern",
        "character_state": {
            "name": "Mira",
            "location": "Tavern",
            "known_facts": ["The innkeeper hides a silver key"],
            "relationships": {"Ivo": "trusted"},
        },
        "information_state": {
            "active_threads": ["Follow the innkeeper's map"],
            "foreshadowing": {"silver-key": "The silver key hums near the cellar"},
        },
        "relationship_change": {"Mira": {"Innkeeper": "wary ally"}},
    }
    choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="The skyway divides at the storm wall.",
        status="pending",
        options=[
            ChoiceOption(text="Enter the tavern", effects=preset_effects, position=0),
            ChoiceOption(text="Cross the bridge", effects={"route_change": "bridge"}, position=1),
            ChoiceOption(text="Descend below", effects={"route_change": "cloud"}, position=2),
        ],
        version=3,
    )
    repository.commit_segment_bundle(segment, choice)
    loaded_choice = repository.get_choice_point_for_segment(segment.id)
    assert loaded_choice is not None
    repository.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id,
            branch_id=branch.id,
            segment_id=segment.id,
            characters=[
                CharacterState(
                    story_id=story.id,
                    branch_id=branch.id,
                    name="Mira",
                    role="cartographer",
                    location="Skyway",
                    motivation="Find her mentor",
                    known_facts=["The bridge is unstable"],
                    relationships={"Ivo": "stranger"},
                    alive=True,
                    version=4,
                )
            ],
            active_threads=["Find the missing mentor"],
            foreshadowing={"old-map": "The map omits one island"},
            rolling_summary="Mira climbed into the storm.",
            context_version=5,
        )
    )
    client = TestClient(create_app(repository=repository, llm_client=llm_client))
    return database, repository, story, branch, segment, loaded_choice, client


def persisted_state(database: Database, repository: StoryRepository, story: Story, branch: Branch) -> dict[str, object]:
    """Capture every row that a failed submission is forbidden to change."""
    persisted_story = repository.get_story(story.id)
    latest = repository.get_latest_memory_snapshot(branch.id)
    assert persisted_story is not None
    assert latest is not None
    with database.read() as connection:
        choice_rows = [tuple(row) for row in connection.execute(
            "SELECT selected_option_id, payload FROM choice_points ORDER BY rowid"
        )]
        snapshot_rows = [tuple(row) for row in connection.execute(
            "SELECT id, payload FROM memory_snapshots ORDER BY rowid"
        )]
    return {
        "story": persisted_story.model_dump(mode="json"),
        "choice_rows": choice_rows,
        "snapshot_rows": snapshot_rows,
        "latest": latest.model_dump(mode="json"),
    }


def test_preset_choice_atomically_selects_and_merges_route_character_and_information_effects(
    tmp_path: Path,
) -> None:
    """Dropping any effect or overwriting old memory would corrupt the next scene context."""
    _, repository, story, branch, segment, choice, client = make_runtime(tmp_path)

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 3, "option_id": str(choice.options[0].id)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "choice_id": str(choice.id),
        "choice_version": 4,
        "story_status": "IDLE",
    }
    selected = repository.get_choice_point_for_segment(segment.id)
    persisted_story = repository.get_story(story.id)
    snapshot = repository.get_latest_memory_snapshot(branch.id)
    assert selected is not None
    assert persisted_story is not None
    assert snapshot is not None
    assert selected.status == "selected"
    assert selected.selected_option_id == choice.options[0].id
    assert selected.version == 4
    assert persisted_story.status is StoryStatus.IDLE
    assert persisted_story.version == 8
    assert snapshot.segment_id == segment.id
    assert snapshot.context_version == 6
    assert snapshot.active_threads == [
        "Find the missing mentor",
        "enter_tavern",
        "Follow the innkeeper's map",
    ]
    assert snapshot.foreshadowing == {
        "old-map": "The map omits one island",
        "silver-key": "The silver key hums near the cellar",
    }
    assert len(snapshot.characters) == 1
    mira = snapshot.characters[0]
    assert mira.role == "cartographer"
    assert mira.location == "Tavern"
    assert mira.motivation == "Find her mentor"
    assert mira.known_facts == [
        "The bridge is unstable",
        "The innkeeper hides a silver key",
    ]
    assert mira.relationships == {"Ivo": "trusted", "Innkeeper": "wary ally"}
    assert mira.version == 5


def test_same_choice_version_and_option_is_idempotent_without_a_second_effect(
    tmp_path: Path,
) -> None:
    """Replaying the accepted request must not increment versions or append another snapshot."""
    database, repository, story, branch, _, choice, client = make_runtime(tmp_path)
    payload = {"choice_version": 3, "option_id": str(choice.options[0].id)}

    first = client.post(f"/api/choices/{choice.id}/select", json=payload)
    after_first = persisted_state(database, repository, story, branch)
    second = client.post(f"/api/choices/{choice.id}/select", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {
        "status": "duplicate",
        "choice_id": str(choice.id),
        "choice_version": 4,
        "story_status": "IDLE",
    }
    assert persisted_state(database, repository, story, branch) == after_first


def test_wrong_choice_version_is_a_stable_conflict_without_mutation(tmp_path: Path) -> None:
    """Accepting a stale version would let an old page commit against a newer choice."""
    database, repository, story, branch, _, choice, client = make_runtime(tmp_path)
    before = persisted_state(database, repository, story, branch)

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 2, "option_id": str(choice.options[0].id)},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "choice_version_conflict", "retryable": False}
    }
    assert persisted_state(database, repository, story, branch) == before


def test_non_waiting_story_returns_stable_conflict_without_mutation_or_llm_call(
    tmp_path: Path,
) -> None:
    """A missing state guard could select a choice while generation is allowed."""
    llm_client = FakeLLMClient(json_responses=[{"route_change": "unsafe"}])
    database, repository, story, branch, _, choice, client = make_runtime(
        tmp_path,
        status=StoryStatus.IDLE,
        llm_client=llm_client,
    )
    before = persisted_state(database, repository, story, branch)

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 3, "custom_action": "Open the sealed door"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "invalid_choice_state", "retryable": False}
    }
    assert persisted_state(database, repository, story, branch) == before
    assert llm_client.calls == []


@pytest.mark.parametrize("custom_action", ["", "x" * 301])
def test_invalid_custom_action_length_preserves_waiting_choice(
    tmp_path: Path, custom_action: str
) -> None:
    """The 1–300 boundary must reject input before persistence or provider work."""
    llm_client = FakeLLMClient(json_responses=[{"route_change": "unsafe"}])
    database, repository, story, branch, _, choice, client = make_runtime(
        tmp_path, llm_client=llm_client
    )
    before = persisted_state(database, repository, story, branch)

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 3, "custom_action": custom_action},
    )

    assert response.status_code == 422
    assert persisted_state(database, repository, story, branch) == before
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.status is StoryStatus.WAITING_CHOICE
    assert llm_client.calls == []


def test_custom_action_is_parsed_once_persisted_and_applied_as_normalized_effects(
    tmp_path: Path,
) -> None:
    """Skipping parsing or persistence would lose the reader-authored branch direction."""
    llm_client = FakeLLMClient(
        json_responses=[
            {
                "route_change": "climb_bell_tower",
                "information_state": ["Learn why the bells are silent"],
            }
        ]
    )
    _, repository, story, branch, segment, choice, client = make_runtime(
        tmp_path, llm_client=llm_client
    )

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 3, "custom_action": "Climb the silent bell tower"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert len(llm_client.calls) == 1
    assert llm_client.calls[0]["operation"] == "generate_json"
    call_context = llm_client.calls[0]["context"]
    assert isinstance(call_context, dict)
    assert call_context["custom_action"] == "Climb the silent bell tower"
    selected = repository.get_choice_point_for_segment(segment.id)
    snapshot = repository.get_latest_memory_snapshot(branch.id)
    assert selected is not None
    assert snapshot is not None
    assert selected.selected_option_id is None
    assert selected.selected_custom_action == "Climb the silent bell tower"
    assert selected.selected_effects == {
        "route_change": "climb_bell_tower",
        "information_state": ["Learn why the bells are silent"],
    }
    assert snapshot.active_threads == [
        "Find the missing mentor",
        "climb_bell_tower",
        "Learn why the bells are silent",
    ]
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.status is StoryStatus.IDLE


@pytest.mark.parametrize(
    "provider_result",
    [
        RuntimeError("provider=secret-model api_key=top-secret prompt=private"),
        {"unknown_effect": "partial write"},
    ],
)
def test_custom_parse_failure_rolls_back_every_write_and_redacts_internal_details(
    tmp_path: Path, provider_result: object
) -> None:
    """Provider or validation failure must leave choice, story, and memory byte-for-byte stable."""
    llm_client = FakeLLMClient(json_responses=[provider_result])
    database, repository, story, branch, _, choice, client = make_runtime(
        tmp_path, llm_client=llm_client
    )
    before = deepcopy(persisted_state(database, repository, story, branch))

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": 3, "custom_action": "Ask the mirror to reveal the hidden road"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": {"code": "custom_action_parse_failed", "retryable": True}
    }
    assert "secret-model" not in response.text
    assert "top-secret" not in response.text
    assert "private" not in response.text
    assert persisted_state(database, repository, story, branch) == before
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.status is StoryStatus.WAITING_CHOICE

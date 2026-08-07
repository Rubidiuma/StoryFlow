"""Integration tests for the SQLite persistence repositories."""
import sqlite3
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import ChoiceFrequency, ChoiceType
from storyflow.domain.models import (
    Branch,
    ChoiceOption,
    ChoicePoint,
    GenerationEvent,
    MemorySnapshot,
    Story,
    StoryBible,
    StoryConfig,
    StorySegment,
)


def make_story() -> Story:
    """Build a valid story with a small, stable configuration."""
    return Story(
        session_id="session-1",
        choice_frequency=ChoiceFrequency.MEDIUM,
        config=StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="A kingdom beneath floating islands.",
            protagonist_desc="A cartographer seeking her missing mentor.",
            style="lyrical",
            choice_frequency=ChoiceFrequency.MEDIUM,
            required_elements=None,
            forbidden_elements=None,
            ending_tendency=None,
        ),
        pause_requested=False,
        version=1,
    )


def make_repository(tmp_path: Path) -> tuple[Database, StoryRepository, Story, Branch]:
    """Create a database containing a story with an empty root branch."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = repository.create_story(make_story())
    branch = repository.create_branch(Branch(story_id=story.id, name="Main"))
    return database, repository, story, branch


def make_segment(story: Story, branch: Branch, key: str, **changes: object) -> StorySegment:
    """Build a segment suitable for persistence tests."""
    values: dict[str, Any] = {
        "story_id": story.id,
        "branch_id": branch.id,
        "sequence": 1,
        "content": "The map led Mira through a storm of silver ash.",
        "summary": "Mira follows the map.",
        "generation_key": key,
    }
    values.update(changes)
    return StorySegment(**values)


def make_choice() -> ChoicePoint:
    """Build the required three-option choice without a persisted parent."""
    return ChoicePoint(
        type=ChoiceType.DECISION,
        reason="Mira reaches a fork in the skyway.",
        status="pending",
        options=[
            ChoiceOption(text="Follow the lights", effects={"route": "lights"}, position=0),
            ChoiceOption(text="Trust the map", effects={"route": "map"}, position=1),
            ChoiceOption(text="Call for help", effects={"route": "help"}, position=2),
        ],
    )


def make_event(story: Story, branch: Branch, request_id: str) -> GenerationEvent:
    """Build a generation event tied to the test story and branch."""
    return GenerationEvent(
        story_id=story.id,
        branch_id=branch.id,
        event_type="committed",
        request_id=request_id,
        duration_ms=0,
        input_token_estimate=0,
        output_size=0,
    )


def test_initialize_is_idempotent_and_connections_enforce_sqlite_settings(tmp_path: Path) -> None:
    """Initialization preserves the database and every connection enables required pragmas."""
    database = Database(tmp_path / "storyflow.sqlite3")

    database.initialize()
    database.initialize()

    connection = database.connect()
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()


def test_story_and_bible_round_trip_and_missing_records_return_none(tmp_path: Path) -> None:
    """Stories and their one-to-one bibles retain Pydantic values through SQLite."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = make_story()
    bible = StoryBible(
        story_id=story.id,
        world_rules="Magic is paid for with memories.",
        tone_rules="Keep the prose intimate and hopeful.",
        protagonist_core="Mira refuses to abandon a friend.",
        required_elements=["skyships"],
        forbidden_elements=["time travel"],
        version=1,
    )

    assert repository.get_story(story.id) is None
    assert repository.get_bible(story.id) is None
    assert repository.create_story(story) == story
    assert repository.get_story(story.id) == story
    assert repository.save_bible(bible) == bible
    assert repository.get_bible(story.id) == bible


def test_duplicate_generation_key_returns_original_bundle_without_extra_rows(tmp_path: Path) -> None:
    """A retried generation key returns its first committed segment without duplicate children."""
    database, repository, story, branch = make_repository(tmp_path)
    first = make_segment(story, branch, "generation-1")
    second = make_segment(story, branch, "generation-1")

    assert repository.commit_segment_bundle(first, make_choice(), make_event(story, branch, "req-1")) == first
    assert repository.commit_segment_bundle(second, make_choice(), make_event(story, branch, "req-2")) == first
    with database.connect() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 1,
        "choice_points": 1,
        "choice_options": 3,
        "generation_events": 1,
    }


def test_segment_bundle_rejects_missing_parent_segment_or_branch(tmp_path: Path) -> None:
    """SQLite foreign keys reject segment parents and branches that were never persisted."""
    _, repository, story, branch = make_repository(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        repository.commit_segment_bundle(
            make_segment(story, branch, "missing-parent", parent_segment_id=uuid4())
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.commit_segment_bundle(
            make_segment(story, Branch(story_id=story.id), "missing-branch")
        )


def test_event_failure_rolls_back_new_segment_and_choice_rows(tmp_path: Path) -> None:
    """A late duplicate request ID rolls every earlier bundle write back."""
    database, repository, story, branch = make_repository(tmp_path)
    existing = make_segment(story, branch, "existing")
    repository.commit_segment_bundle(existing, event=make_event(story, branch, "request-used"))
    new_segment = make_segment(story, branch, "must-roll-back", sequence=2, parent_segment_id=existing.id)

    with pytest.raises(sqlite3.IntegrityError):
        repository.commit_segment_bundle(
            new_segment,
            make_choice(),
            make_event(story, branch, "request-used"),
        )
    assert repository.get_segment(new_segment.id) is None
    assert repository.get_branch(branch.id) == branch.model_copy(
        update={"head_segment_id": existing.id}
    )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM choice_points").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM choice_options").fetchone()[0] == 0


def test_branch_path_uses_head_and_parent_links_to_keep_only_its_ancestry(tmp_path: Path) -> None:
    """A fork's path contains its shared prefix and own head lineage, never sibling records."""
    _, repository, story, main_branch = make_repository(tmp_path)
    first = make_segment(story, main_branch, "main-1")
    repository.commit_segment_bundle(first)
    second = make_segment(
        story, main_branch, "main-2", sequence=2, parent_segment_id=first.id
    )
    repository.commit_segment_bundle(second)
    fork = repository.create_branch(
        Branch(
            story_id=story.id,
            parent_branch_id=main_branch.id,
            fork_segment_id=second.id,
            head_segment_id=second.id,
            name="What if Mira trusted the storm?",
        )
    )
    third = make_segment(story, fork, "fork-3", sequence=3, parent_segment_id=second.id)
    repository.commit_segment_bundle(third)
    sibling = make_segment(story, main_branch, "main-3", sequence=3, parent_segment_id=second.id)
    repository.commit_segment_bundle(sibling)

    assert repository.get_branch(fork.id) == fork.model_copy(update={"head_segment_id": third.id})
    assert repository.list_branch_path(fork.id) == [first, second, third]
    assert repository.list_branch_path(uuid4()) == []


def test_memory_snapshots_round_trip_and_latest_is_per_branch(tmp_path: Path) -> None:
    """The newest snapshot for a branch can be restored without affecting empty branches."""
    _, repository, story, branch = make_repository(tmp_path)
    first = MemorySnapshot(
        story_id=story.id,
        branch_id=branch.id,
        active_threads=["Find the mentor"],
        rolling_summary="Mira has the map.",
        context_version=1,
    )
    second = MemorySnapshot(
        story_id=story.id,
        branch_id=branch.id,
        active_threads=["Find the mentor", "Survive the storm"],
        rolling_summary="Mira enters the storm.",
        context_version=1,
    )

    assert repository.get_latest_memory_snapshot(branch.id) is None
    assert repository.save_memory_snapshot(first) == first
    assert repository.save_memory_snapshot(second) == second
    assert repository.get_latest_memory_snapshot(branch.id) == second


def test_story_current_branch_and_choice_selection_use_relational_foreign_keys(
    tmp_path: Path,
) -> None:
    """Nullable JSON relation fields are mirrored by enforced relational foreign keys."""
    database, repository, story, branch = make_repository(tmp_path)
    story_with_current_branch = make_story().model_copy(update={"current_branch_id": branch.id})

    assert repository.create_story(story_with_current_branch) == story_with_current_branch
    assert repository.get_story(story_with_current_branch.id) == story_with_current_branch
    with pytest.raises(sqlite3.IntegrityError):
        repository.create_story(make_story().model_copy(update={"current_branch_id": uuid4()}))

    selected_choice = make_choice()
    selected_choice = selected_choice.model_copy(
        update={"selected_option_id": selected_choice.options[0].id}
    )
    selected_segment = make_segment(story, branch, "selected-choice")
    repository.commit_segment_bundle(selected_segment, selected_choice)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT selected_option_id, payload FROM choice_points WHERE id = ?", (str(selected_choice.id),)
        ).fetchone()
    assert row["selected_option_id"] == str(selected_choice.options[0].id)
    assert ChoicePoint.model_validate_json(row["payload"]).selected_option_id == selected_choice.options[0].id

    invalid_choice = make_choice().model_copy(update={"selected_option_id": uuid4()})
    with pytest.raises(sqlite3.IntegrityError):
        repository.commit_segment_bundle(
            make_segment(story, branch, "invalid-selected-choice", sequence=2), invalid_choice
        )


def test_database_reads_explicitly_close_tracked_connections_on_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read connections close deterministically, including when work inside them raises."""
    database, repository, story, _ = make_repository(tmp_path)
    real_connect = sqlite3.connect

    class TrackingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection
            self.closed = False

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def __setattr__(self, name: str, value: object) -> None:
            if name in {"connection", "closed"}:
                object.__setattr__(self, name, value)
            else:
                setattr(self.connection, name, value)

        def close(self) -> None:
            self.closed = True
            self.connection.close()

    tracked: list[TrackingConnection] = []

    def track_connect(path: str, **kwargs: Any) -> TrackingConnection:
        connection = TrackingConnection(real_connect(path, **kwargs))
        tracked.append(connection)
        return connection

    monkeypatch.setattr("storyflow.db.database.sqlite3.connect", track_connect)
    with database.read() as connection:
        connection.execute("SELECT 1")
    assert tracked[-1].closed is True

    with pytest.raises(RuntimeError, match="read failure"), database.read():
        raise RuntimeError("read failure")
    assert tracked[-1].closed is True

    assert repository.get_story(story.id) == story
    assert tracked[-1].closed is True


def test_persisted_domain_datetimes_are_aware_utc_and_round_trip(tmp_path: Path) -> None:
    """Storage retains timezone-aware UTC defaults for created and updated domain records."""
    _, repository, story, branch = make_repository(tmp_path)
    segment = make_segment(story, branch, "aware-datetimes")

    assert story.created_at.tzinfo is UTC
    assert story.updated_at.tzinfo is UTC
    assert branch.created_at.tzinfo is UTC
    assert segment.created_at.tzinfo is UTC
    assert repository.get_story(story.id) == story
    assert repository.commit_segment_bundle(segment) == segment
    assert repository.get_segment(segment.id) == segment

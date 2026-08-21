"""Integration coverage for generation idempotency, concurrency, and recovery."""

import asyncio
import sqlite3
import warnings
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx
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
from storyflow.domain.enums import ChoiceFrequency, StoryStatus
from storyflow.domain.models import Branch, GenerationEvent, Story, StoryConfig, StorySegment
from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app
from storyflow.services import generation as generation_service
from storyflow.services.generation import GenerationRequest, GenerationService


def make_runtime(
    tmp_path: Path,
    *,
    name: str = "main",
) -> tuple[Database, StoryRepository, Story, Branch]:
    """Create one ready story and current branch in shared real SQLite."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = repository.create_story(
        Story(
            session_id=f"generation-recovery-{name}",
            status=StoryStatus.IDLE,
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
            version=1,
        )
    )
    branch = repository.create_branch(Branch(story_id=story.id, name=name))
    story = repository.set_current_branch(story.id, branch.id)
    return database, repository, story, branch


def valid_plan() -> dict[str, object]:
    """Return one hand-authored Director response."""
    return {
        "goal": "Reach the observatory before sunset.",
        "conflict": "A storm erases the only visible path.",
        "beats": ["Mira finds a signal fire.", "The bridge begins to collapse."],
        "choice_suggestion": None,
    }


class BlockingFirstDirectorLLM:
    """Block only the first Director call so concurrency is event-driven."""

    def __init__(self) -> None:
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.calls: list[tuple[str, str]] = []
        self._director_calls = 0

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        marker = str(context["marker"])
        self.calls.append(("generate_json", marker))
        self._director_calls += 1
        if self._director_calls == 1:
            self.first_started.set()
            await self.release_first.wait()
        return valid_plan()

    async def stream_text(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> AsyncIterator[str]:
        marker = str(context["marker"])
        self.calls.append(("stream_text", marker))
        yield f"A complete scene for {marker}."


@pytest.mark.asyncio
async def test_same_branch_rejects_overlapping_generation_but_other_branch_proceeds(
    tmp_path: Path,
) -> None:
    """Removing the branch guard would spend a second same-branch model call."""
    _, repository, first_story, first_branch = make_runtime(tmp_path, name="first")
    _, repository, other_story, other_branch = make_runtime(tmp_path, name="other")
    llm_client = BlockingFirstDirectorLLM()
    service = GenerationService(repository, llm_client)
    first_request = GenerationRequest(
        story_id=first_story.id,
        branch_id=first_branch.id,
        generation_key="first-active",
        context={"marker": "first"},
    )

    first_task = asyncio.create_task(service.generate(first_request))
    await llm_client.first_started.wait()
    first_story_while_blocked = repository.get_story(first_story.id)

    conflict = await service.generate(
        GenerationRequest(
            story_id=first_story.id,
            branch_id=first_branch.id,
            generation_key="same-branch-overlap",
            context={"marker": "conflict"},
        )
    )
    independent = await service.generate(
        GenerationRequest(
            story_id=other_story.id,
            branch_id=other_branch.id,
            generation_key="other-branch",
            context={"marker": "other"},
        )
    )

    assert conflict.error_code == "generation_conflict"
    assert conflict.segment is None
    assert repository.get_story(first_story.id) == first_story_while_blocked
    assert independent.segment is not None
    assert independent.content == "A complete scene for other."
    assert ("generate_json", "conflict") not in llm_client.calls
    llm_client.release_first.set()
    first = await first_task
    assert first.segment is not None


@pytest.mark.asyncio
async def test_overlapping_http_request_returns_json_409_before_llm(tmp_path: Path) -> None:
    """Moving conflict detection inside SSE would return 200 or call the provider twice."""
    _, repository, story, branch = make_runtime(tmp_path)
    llm_client = BlockingFirstDirectorLLM()
    app = create_app(repository=repository, llm_client=llm_client)
    transport = httpx.ASGITransport(app=app)
    first_payload = {
        "branch_id": str(branch.id),
        "generation_key": "http-first-active",
        "context": {"marker": "first"},
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first_task = asyncio.create_task(
            client.post(f"/api/stories/{story.id}/generate", json=first_payload)
        )
        await llm_client.first_started.wait()
        conflict = await client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "http-overlap",
                "context": {"marker": "conflict"},
            },
        )
        assert conflict.status_code == 409
        assert conflict.json() == {
            "detail": {"code": "generation_conflict", "retryable": True}
        }
        assert conflict.headers["content-type"] == "application/json"
        assert ("generate_json", "conflict") not in llm_client.calls
        llm_client.release_first.set()
        first = await first_task

    assert first.status_code == 200
    assert "event: committed" in first.text


@pytest.mark.asyncio
async def test_idempotent_replay_cannot_release_an_active_request_reservation(
    tmp_path: Path,
) -> None:
    """A replay owns no reservation and must not release another request's guard."""
    _, repository, story, branch = make_runtime(tmp_path)
    seed = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        sequence=1,
        content="The already committed scene.",
        generation_key="committed-replay",
        status="completed",
    )
    repository.commit_segment_bundle(seed)
    llm_client = BlockingFirstDirectorLLM()
    app = create_app(repository=repository, llm_client=llm_client)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        active_task = asyncio.create_task(
            client.post(
                f"/api/stories/{story.id}/generate",
                json={
                    "branch_id": str(branch.id),
                    "generation_key": "active-after-commit",
                    "context": {"marker": "first"},
                },
            )
        )
        await llm_client.first_started.wait()
        replay = await client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "committed-replay",
                "context": {"marker": "replay"},
            },
        )
        overlap = await client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "must-still-conflict",
                "context": {"marker": "overlap"},
            },
        )
        assert replay.status_code == 200
        assert "event: committed" in replay.text
        assert overlap.status_code == 409
        assert overlap.json() == {
            "detail": {"code": "generation_conflict", "retryable": True}
        }
        assert ("generate_json", "overlap") not in llm_client.calls
        llm_client.release_first.set()
        active = await active_task

    assert active.status_code == 200
    assert "event: committed" in active.text


@pytest.mark.asyncio
async def test_twenty_sequential_duplicates_return_one_stable_bundle(tmp_path: Path) -> None:
    """Bypassing the idempotency lookup would append scenes, events, and versions."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Only the first request may write this scene."]],
    )
    service = GenerationService(repository, llm_client)
    request = GenerationRequest(
        story_id=story.id,
        branch_id=branch.id,
        generation_key="twenty-identical-requests",
        context={"marker": "same"},
    )

    results = [await service.generate(request) for _ in range(20)]

    assert results[0].segment is not None
    assert all(result == results[0] for result in results)
    # Only the first request does model work: Director + Writer + memory update.
    # The remaining nineteen are deduplicated with no model calls.
    assert len(llm_client.calls) == 3
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.version == story.version + 4
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 1


def test_generation_key_owned_by_other_story_or_branch_is_json_409_before_llm(
    tmp_path: Path,
) -> None:
    """Returning the owned segment would disclose another aggregate's committed result."""
    _, repository, owner_story, owner_branch = make_runtime(tmp_path, name="owner")
    owner_llm = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Private committed content for the owning branch."]],
    )
    owner_result = asyncio.run(
        GenerationService(repository, owner_llm).generate(
            GenerationRequest(
                story_id=owner_story.id,
                branch_id=owner_branch.id,
                generation_key="globally-owned-http-key",
                context={"marker": "owner"},
            )
        )
    )
    assert owner_result.segment is not None
    other_branch = repository.create_branch(Branch(story_id=owner_story.id, name="sibling"))
    _, repository, other_story, other_story_branch = make_runtime(tmp_path, name="other-story")
    rejecting_llm = FakeLLMClient()
    payloads = (
        (owner_story.id, other_branch.id),
        (other_story.id, other_story_branch.id),
    )

    with TestClient(create_app(repository=repository, llm_client=rejecting_llm)) as client:
        responses = [
            client.post(
                f"/api/stories/{story_id}/generate",
                json={
                    "branch_id": str(branch_id),
                    "generation_key": "globally-owned-http-key",
                    "context": {"marker": "must-not-run"},
                },
            )
            for story_id, branch_id in payloads
        ]

    assert all(response.status_code == 409 for response in responses)
    assert all(
        response.json()
        == {"detail": {"code": "invalid_generation_state", "retryable": False}}
        for response in responses
    )
    assert all("Private committed content" not in response.text for response in responses)
    assert rejecting_llm.calls == []


@pytest.mark.asyncio
async def test_writer_cancellation_discards_partial_content_and_new_key_retries_cleanly(
    tmp_path: Path,
) -> None:
    """Treating cancellation as success would commit or reuse a transient prefix."""
    database, repository, story, branch = make_runtime(tmp_path)
    story_before = repository.get_story(story.id)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan(), valid_plan()],
        text_responses=[
            ["This prefix must disappear. ", asyncio.CancelledError()],
            ["The retry starts from a clean writer buffer."],
        ],
    )
    service = GenerationService(repository, llm_client)
    interrupted_deltas: list[str] = []

    interrupted = await service.generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="cancelled-writer",
            context={"marker": "cancelled"},
        ),
        on_delta=lambda text: _capture_delta(interrupted_deltas, text),
    )

    assert interrupted.error_code == "generation_interrupted"
    assert interrupted.status is StoryStatus.ERROR
    assert interrupted.segment is None
    assert interrupted.choice_point is None
    assert interrupted.content == ""
    assert interrupted_deltas == ["This prefix must disappear. "]
    assert repository.get_story(story.id) == story_before
    with database.read() as connection:
        counts_after_interruption = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts_after_interruption == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }

    retry = await service.generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="clean-retry",
            context={"marker": "retry"},
        )
    )

    assert retry.error_code is None
    assert retry.segment is not None
    assert retry.content == "The retry starts from a clean writer buffer."
    assert "This prefix must disappear" not in retry.content
    assert repository.get_segment_by_generation_key("cancelled-writer") is None


@pytest.mark.asyncio
async def test_writer_cancellation_emits_one_error_without_success_terminal_event(
    tmp_path: Path,
) -> None:
    """Letting cancellation escape would terminate SSE without its stable error frame."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[
            ["Transient SSE delta. ", asyncio.CancelledError("private transport detail")]
        ],
    )
    app = create_app(repository=repository, llm_client=llm_client)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "cancelled-sse",
                "context": {"marker": "cancelled"},
            },
        )

    assert response.status_code == 200
    assert response.text.count("event: error") == 1
    assert '"code":"generation_interrupted"' in response.text
    assert "private transport detail" not in response.text
    assert "event: committed" not in response.text
    assert "event: continue" not in response.text
    assert "event: choice" not in response.text
    assert "event: paused" not in response.text
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM choice_points").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 0


async def _capture_delta(deltas: list[str], text: str) -> None:
    """Record an emitted delta without replacing production behavior."""
    deltas.append(text)


def test_startup_recovery_marks_only_active_stories_once_without_llm(tmp_path: Path) -> None:
    """Omitting startup recovery would leave paid, abandoned work looking active forever."""
    active_statuses = (
        StoryStatus.PLANNING,
        StoryStatus.STREAMING,
        StoryStatus.COMMITTING,
    )
    untouched_statuses = (
        StoryStatus.DRAFT,
        StoryStatus.IDLE,
        StoryStatus.WAITING_CHOICE,
        StoryStatus.PAUSED,
        StoryStatus.ERROR,
    )
    database: Database | None = None
    repository: StoryRepository | None = None
    stories: dict[StoryStatus, Story] = {}
    for status in (*active_statuses, *untouched_statuses):
        database, repository, story, _ = make_runtime(tmp_path, name=status.value.lower())
        persisted = story.model_copy(update={"status": status})
        with database.transaction() as connection:
            connection.execute(
                "UPDATE stories SET payload = ? WHERE id = ?",
                (persisted.model_dump_json(), str(story.id)),
            )
        stories[status] = persisted
    assert database is not None
    assert repository is not None
    llm_client = FakeLLMClient()

    with TestClient(create_app(repository=repository, llm_client=llm_client)):
        pass

    for status in active_statuses:
        recovered = repository.get_story(stories[status].id)
        assert recovered is not None
        assert recovered.status is StoryStatus.ERROR
        assert recovered.version == stories[status].version + 1
    for status in untouched_statuses:
        assert repository.get_story(stories[status].id) == stories[status]
    assert llm_client.calls == []
    with database.read() as connection:
        event_rows = connection.execute(
            "SELECT payload FROM generation_events ORDER BY rowid"
        ).fetchall()
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 0
    events = [GenerationEvent.model_validate_json(row["payload"]) for row in event_rows]
    assert len(events) == 3
    assert [event.state_sequence[0] for event in events] == list(active_statuses)
    assert all(event.event_type == "error" for event in events)
    assert all(event.error_code == "generation_interrupted" for event in events)
    assert all(event.state_sequence[-1] is StoryStatus.ERROR for event in events)

    recovered_again = generation_service.recover_interrupted_generations(repository)

    assert recovered_again == []
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 3


def test_startup_recovery_marks_active_stories_without_a_valid_branch(
    tmp_path: Path,
) -> None:
    """Missing branch metadata must not leave an interrupted Story permanently active."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    no_branch = repository.create_story(
        _make_story(status=StoryStatus.PLANNING, name="no-branch")
    )
    orphaned = repository.create_story(_make_story(status=StoryStatus.IDLE, name="orphaned"))
    orphaned_branch = repository.create_branch(Branch(story_id=orphaned.id, name="orphaned"))
    orphaned = repository.set_current_branch(orphaned.id, orphaned_branch.id).model_copy(
        update={"status": StoryStatus.STREAMING}
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE stories SET payload = ? WHERE id = ?",
            (orphaned.model_dump_json(), str(orphaned.id)),
        )
    raw_connection = sqlite3.connect(database.path)
    try:
        raw_connection.execute("PRAGMA foreign_keys = OFF")
        raw_connection.execute("DELETE FROM branches WHERE id = ?", (str(orphaned_branch.id),))
        raw_connection.commit()
    finally:
        raw_connection.close()

    recovered = repository.recover_interrupted_generations()

    assert {story.id for story in recovered} == {no_branch.id, orphaned.id}
    for interrupted in (no_branch, orphaned):
        persisted = repository.get_story(interrupted.id)
        assert persisted is not None
        assert persisted.status is StoryStatus.ERROR
        assert persisted.version == interrupted.version + 1
    with database.read() as connection:
        rows = connection.execute(
            "SELECT branch_id, payload FROM generation_events ORDER BY rowid"
        ).fetchall()
    assert [row["branch_id"] for row in rows] == [None, None]
    events = [GenerationEvent.model_validate_json(row["payload"]) for row in rows]
    assert len(events) == 2
    assert all(event.branch_id is None for event in events)
    assert all(event.error_code == "generation_interrupted" for event in events)
    assert repository.recover_interrupted_generations() == []


def test_database_initialize_migrates_recovery_event_branch_to_nullable(
    tmp_path: Path,
) -> None:
    """Restarting an existing T09 database must retain events and permit branchless recovery."""
    database, repository, story, branch = make_runtime(tmp_path)
    segment = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        sequence=1,
        content="A committed scene that predates recovery migration.",
        generation_key="pre-migration",
        status="completed",
    )
    event = GenerationEvent(
        story_id=story.id,
        branch_id=branch.id,
        event_type="committed",
        request_id="pre-migration",
        duration_ms=0,
        input_token_estimate=0,
        output_size=len(segment.content),
    )
    repository.commit_segment_bundle(segment, event=event)
    connection = database.connect()
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            BEGIN;
            ALTER TABLE generation_events RENAME TO generation_events_nullable;
            CREATE TABLE generation_events (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL REFERENCES stories(id),
                branch_id TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                FOREIGN KEY (branch_id, story_id) REFERENCES branches(id, story_id)
            );
            INSERT INTO generation_events (id, story_id, branch_id, request_id, payload)
            SELECT id, story_id, branch_id, request_id, payload
            FROM generation_events_nullable;
            DROP TABLE generation_events_nullable;
            COMMIT;
            """
        )
        connection.execute("PRAGMA foreign_keys = ON")
    finally:
        connection.close()
    with database.read() as connection:
        before = connection.execute(
            "SELECT payload FROM generation_events WHERE id = ?", (str(event.id),)
        ).fetchone()["payload"]
        branch_column = next(
            row for row in connection.execute("PRAGMA table_info(generation_events)")
            if row["name"] == "branch_id"
        )
    assert branch_column["notnull"] == 1

    database.initialize()

    with database.read() as connection:
        after = connection.execute(
            "SELECT payload FROM generation_events WHERE id = ?", (str(event.id),)
        ).fetchone()["payload"]
        migrated_column = next(
            row for row in connection.execute("PRAGMA table_info(generation_events)")
            if row["name"] == "branch_id"
        )
    assert migrated_column["notnull"] == 0
    assert after == before


def _make_story(*, status: StoryStatus, name: str) -> Story:
    """Build a Story without requiring a current branch."""
    return Story(
        session_id=f"recovery-{name}",
        status=status,
        choice_frequency=ChoiceFrequency.MEDIUM,
        config=StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="A damaged persisted world.",
            protagonist_desc="Mira waits for recovery.",
            important_supporting_characters=None,
            style="lyrical",
            choice_frequency=ChoiceFrequency.MEDIUM,
            required_elements=None,
            forbidden_elements=None,
            ending_tendency=None,
        ),
        pause_requested=False,
        version=1,
    )

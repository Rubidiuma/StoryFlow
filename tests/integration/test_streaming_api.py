"""Integration coverage for the versioned generation SSE endpoint."""

import json
import warnings
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from storyflow.domain.models import Branch, Story, StoryConfig, StorySegment
from storyflow.llm.fake import FakeLLMClient, StreamInterruptedError
from storyflow.main import create_app


class VisibilityCheckingFakeLLMClient(FakeLLMClient):
    """Record formal-row visibility after each fake Writer chunk is published."""

    def __init__(self, repository: StoryRepository, *, text_responses: list[list[str]]) -> None:
        super().__init__(json_responses=[valid_plan()], text_responses=text_responses)
        self.repository = repository
        self.visible_segment_counts: list[int] = []

    async def stream_text(
        self,
        *,
        prompt: str,
        context: Mapping[str, Any],
    ) -> AsyncIterator[str]:
        async for chunk in super().stream_text(prompt=prompt, context=context):
            yield chunk
            with self.repository.database.read() as connection:
                count = connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0]
            self.visible_segment_counts.append(count)


def make_runtime(
    tmp_path: Path,
    *,
    choice_frequency: ChoiceFrequency = ChoiceFrequency.MEDIUM,
    status: StoryStatus = StoryStatus.IDLE,
) -> tuple[Database, StoryRepository, Story, Branch]:
    """Create one ready story and current branch in real SQLite."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = repository.create_story(
        Story(
            session_id="streaming-session",
            status=status,
            choice_frequency=choice_frequency,
            config=StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="Floating islands drift above a storm.",
                protagonist_desc="Mira maps roads hidden in the clouds.",
                important_supporting_characters=None,
                style="lyrical",
                choice_frequency=choice_frequency,
                required_elements=None,
                forbidden_elements=None,
                ending_tendency=None,
            ),
            pause_requested=False,
            version=1,
        )
    )
    branch = repository.create_branch(Branch(story_id=story.id, name="Main"))
    story = repository.set_current_branch(story.id, branch.id)
    return database, repository, story, branch


def valid_plan(*, choice_suggestion: object = None) -> dict[str, object]:
    """Return a hand-authored provider payload accepted by ScenePlan."""
    return {
        "goal": "Reach the observatory before sunset.",
        "conflict": "A storm erases the only visible path.",
        "beats": ["Mira finds a signal fire.", "The bridge begins to collapse."],
        "choice_suggestion": choice_suggestion,
    }


def valid_choice_suggestion() -> dict[str, object]:
    """Return three distinct public labels with structured hidden effects."""
    return {
        "type": "decision",
        "reason": "The storm closes both known roads.",
        "options": [
            {"text": "Follow the signal fire", "effects": {"route": "fire"}, "position": 0},
            {"text": "Cross the broken bridge", "effects": {"route": "bridge"}, "position": 1},
            {"text": "Descend into the cloud", "effects": {"route": "cloud"}, "position": 2},
        ],
    }


def parse_sse(response_text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse the endpoint's deliberately small SSE frame subset."""
    frames: list[tuple[str, dict[str, Any]]] = []
    for raw_frame in response_text.strip().split("\n\n"):
        lines = raw_frame.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        name = lines[0].removeprefix("event: ")
        payload = json.loads(lines[1][6:])
        assert type(payload["version"]) is int
        assert payload["version"] == 1
        assert payload["event"] == name
        assert isinstance(payload["data"], dict)
        frames.append((name, payload))
    return frames


def test_no_choice_generation_streams_versioned_frames_and_commits(
    tmp_path: Path,
) -> None:
    """A missing route or broken event order prevents a client from rendering a scene."""
    _, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["The storm opened ", "", "a silver road."]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "request-1",
                "context": {"arc": "rising"},
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == [
        "planning",
        "delta",
        "delta",
        "committed",
        "continue",
    ]
    assert [payload["data"]["text"] for name, payload in frames if name == "delta"] == [
        "The storm opened ",
        "a silver road.",
    ]
    committed = frames[-2][1]["data"]
    assert committed["status"] == "IDLE"
    persisted = repository.get_segment_by_generation_key("request-1")
    assert persisted is not None
    assert committed["segment_id"] == str(persisted.id)
    assert persisted.content == "The storm opened a silver road."


def test_choice_options_are_emitted_only_after_the_scene_is_committed(tmp_path: Path) -> None:
    """Publishing options before commit can let a reader act on a scene that rolls back."""
    _, repository, story, branch = make_runtime(
        tmp_path,
        choice_frequency=ChoiceFrequency.MANY,
    )
    previous = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        sequence=1,
        content="Mira left the harbor.",
        generation_key="seed-scene",
        status="completed",
    )
    repository.commit_segment_bundle(previous)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan(choice_suggestion=valid_choice_suggestion())],
        text_responses=[["Mira reached the broken bridge."]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "choice-request",
                "context": {},
            },
        )

    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == ["planning", "delta", "committed", "choice"]
    assert all("options" not in payload["data"] for _, payload in frames[:-1])
    assert frames[-2][1]["data"]["status"] == "WAITING_CHOICE"
    assert [option["text"] for option in frames[-1][1]["data"]["options"]] == [
        "Follow the signal fire",
        "Cross the broken bridge",
        "Descend into the cloud",
    ]
    assert all("effects" not in option for option in frames[-1][1]["data"]["options"])
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.status is StoryStatus.WAITING_CHOICE


def test_safety_pause_is_the_only_control_event_after_commit(tmp_path: Path) -> None:
    """Mapping a policy pause to continue would start another unsafe generation."""
    _, repository, story, branch = make_runtime(
        tmp_path,
        choice_frequency=ChoiceFrequency.MANY,
    )
    first = repository.commit_segment_bundle(
        StorySegment(
            story_id=story.id,
            branch_id=branch.id,
            sequence=1,
            content="The first road vanished.",
            generation_key="pause-seed-1",
            status="completed",
        )
    )
    repository.commit_segment_bundle(
        StorySegment(
            story_id=story.id,
            branch_id=branch.id,
            parent_segment_id=first.id,
            sequence=2,
            content="The second road vanished.",
            generation_key="pause-seed-2",
            status="completed",
        )
    )
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Mira stopped at the cloud's edge."]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "pause-request",
                "context": {},
            },
        )

    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == ["planning", "delta", "committed", "paused"]
    assert frames[-2][1]["data"]["status"] == "PAUSED"
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.status is StoryStatus.PAUSED


def test_explicit_heartbeat_is_empty_and_never_becomes_story_content(tmp_path: Path) -> None:
    """Treating a heartbeat as writer text corrupts both deltas and the formal scene."""
    _, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Only narrative text is formal content."]],
    )

    with TestClient(
        create_app(
            repository=repository,
            llm_client=llm_client,
            emit_generation_heartbeat=True,
        )
    ) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "heartbeat-request",
                "context": {},
            },
        )

    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == [
        "planning",
        "heartbeat",
        "delta",
        "committed",
        "continue",
    ]
    heartbeat = frames[1][1]
    assert heartbeat == {
        "version": 1,
        "event": "heartbeat",
        "data": {"text": ""},
    }
    assert [payload["data"]["text"] for name, payload in frames if name == "delta"] == [
        "Only narrative text is formal content."
    ]
    persisted = repository.get_segment_by_generation_key("heartbeat-request")
    assert persisted is not None
    assert persisted.content == "Only narrative text is formal content."


def test_writer_interruption_emits_one_redacted_error_and_no_formal_scene(
    tmp_path: Path,
) -> None:
    """A partial provider stream must end as a stable error without a formal row."""
    database, repository, story, branch = make_runtime(tmp_path)
    story_before = repository.get_story(story.id)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[
            [
                "Visible transient prefix. ",
                StreamInterruptedError("provider token=writer-secret"),
            ]
        ],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "writer-error-request",
                "context": {"private_prompt": "never-return-this"},
            },
        )

    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == ["planning", "delta", "error"]
    assert sum(name == "error" for name, _ in frames) == 1
    assert frames[-1][1]["data"] == {"code": "writer_failed", "retryable": True}
    assert "writer-secret" not in response.text
    assert "never-return-this" not in response.text
    assert "Visible transient prefix" not in json.dumps(frames[-1][1]["data"])
    assert repository.get_story(story.id) == story_before
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("json_responses", "expected_code", "retryable", "expected_calls"),
    [
        (
            [
                {"goal": "", "conflict": "provider-secret-one", "beats": ["Beat"]},
                {"goal": "Goal", "conflict": "provider-secret-two", "beats": []},
            ],
            "director_invalid",
            False,
            2,
        ),
        (
            [TimeoutError("provider token=director-secret")],
            "director_failed",
            True,
            1,
        ),
    ],
    ids=["invalid", "request-failed"],
)
def test_director_errors_emit_only_stable_redacted_data(
    tmp_path: Path,
    json_responses: list[object],
    expected_code: str,
    retryable: bool,
    expected_calls: int,
) -> None:
    """Director data and exception text must never cross the SSE error boundary."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(json_responses=json_responses)

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": f"{expected_code}-request",
                "context": {"private_prompt": "prompt-secret"},
            },
        )

    frames = parse_sse(response.text)
    assert [name for name, _ in frames] == ["planning", "error"]
    assert frames[-1][1]["data"] == {"code": expected_code, "retryable": retryable}
    assert "provider-secret" not in response.text
    assert "director-secret" not in response.text
    assert "prompt-secret" not in response.text
    assert len(llm_client.calls) == expected_calls
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 0


def test_pause_and_resume_endpoints_persist_the_reader_control_state(tmp_path: Path) -> None:
    database, repository, story, _ = make_runtime(tmp_path)
    client = TestClient(create_app(repository=repository, llm_client=FakeLLMClient()))

    paused = client.post(f"/api/stories/{story.id}/pause")

    assert paused.status_code == 200
    assert paused.json()["pause_requested"] is True
    repository_story = repository.get_story(story.id)
    assert repository_story is not None and repository_story.pause_requested is True

    paused_story = repository_story.model_copy(
        update={"status": StoryStatus.PAUSED}
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE stories SET payload = ? WHERE id = ?",
            (paused_story.model_dump_json(), str(story.id)),
        )
    resumed = client.post(f"/api/stories/{story.id}/resume")

    assert resumed.status_code == 200
    assert resumed.json()["status"] == "IDLE"
    assert resumed.json()["pause_requested"] is False


def test_missing_story_or_branch_returns_json_404_before_llm(tmp_path: Path) -> None:
    """Missing aggregate resources must not open a stream or spend a provider call."""
    _, repository, story, _ = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["must not run"]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        missing_story = client.post(
            f"/api/stories/{uuid4()}/generate",
            json={
                "branch_id": str(uuid4()),
                "generation_key": "missing-story",
                "context": {},
            },
        )
        missing_branch = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(uuid4()),
                "generation_key": "missing-branch",
                "context": {},
            },
        )

    assert missing_story.status_code == 404
    assert missing_story.json() == {
        "detail": {"code": "story_not_found", "retryable": False}
    }
    assert missing_branch.status_code == 404
    assert missing_branch.json() == {
        "detail": {"code": "branch_not_found", "retryable": False}
    }
    assert missing_story.headers["content-type"] == "application/json"
    assert missing_branch.headers["content-type"] == "application/json"
    assert llm_client.calls == []


def test_cross_story_branch_non_idle_story_and_invalid_body_never_start_stream(
    tmp_path: Path,
) -> None:
    """Invalid ownership, state, or body must be rejected before any model invocation."""
    _, repository, story, _ = make_runtime(tmp_path)
    _, repository, other_story, other_branch = make_runtime(tmp_path)
    _, repository, waiting_story, waiting_branch = make_runtime(
        tmp_path,
        status=StoryStatus.WAITING_CHOICE,
    )
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["must not run"]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        cross_story = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(other_branch.id),
                "generation_key": "cross-story",
                "context": {},
            },
        )
        non_idle = client.post(
            f"/api/stories/{waiting_story.id}/generate",
            json={
                "branch_id": str(waiting_branch.id),
                "generation_key": "non-idle",
                "context": {},
            },
        )
        invalid_body = client.post(
            f"/api/stories/{other_story.id}/generate",
            json={"branch_id": str(other_branch.id), "generation_key": "   ", "context": {}},
        )

    assert cross_story.status_code == 409
    assert cross_story.json() == {
        "detail": {"code": "invalid_generation_state", "retryable": False}
    }
    assert non_idle.status_code == 409
    assert non_idle.json() == {
        "detail": {"code": "invalid_generation_state", "retryable": False}
    }
    assert invalid_body.status_code == 422
    assert all(
        response.headers["content-type"] == "application/json"
        for response in (cross_story, non_idle, invalid_body)
    )
    assert llm_client.calls == []


def test_published_deltas_have_no_formal_row_until_writer_completion(tmp_path: Path) -> None:
    """A client-visible prefix must remain transient until the entire Writer stream ends."""
    _, repository, story, branch = make_runtime(tmp_path)
    llm_client = VisibilityCheckingFakeLLMClient(
        repository,
        text_responses=[["First transient chunk. ", "Second transient chunk."]],
    )

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        response = client.post(
            f"/api/stories/{story.id}/generate",
            json={
                "branch_id": str(branch.id),
                "generation_key": "visibility-request",
                "context": {},
            },
        )

    assert [name for name, _ in parse_sse(response.text)] == [
        "planning",
        "delta",
        "delta",
        "committed",
        "continue",
    ]
    assert llm_client.visible_segment_counts == [0, 0]
    assert repository.get_segment_by_generation_key("visibility-request") is not None


def test_unconfigured_app_returns_normal_retryable_json_error() -> None:
    """The module-level app must never attempt a network call without injected dependencies."""
    with TestClient(create_app()) as client:
        response = client.post(
            f"/api/stories/{uuid4()}/generate",
            json={
                "branch_id": str(uuid4()),
                "generation_key": "unconfigured-request",
                "context": {},
            },
        )

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "detail": {"code": "generation_service_unavailable", "retryable": True}
    }


def test_committed_generation_key_replays_without_duplicate_work_or_rows(tmp_path: Path) -> None:
    """Replaying a committed key must preserve T08 idempotency through the HTTP boundary."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["The scene exists only once."]],
    )
    payload = {
        "branch_id": str(branch.id),
        "generation_key": "replayed-request",
        "context": {},
    }

    with TestClient(create_app(repository=repository, llm_client=llm_client)) as client:
        first = client.post(f"/api/stories/{story.id}/generate", json=payload)
        second = client.post(f"/api/stories/{story.id}/generate", json=payload)

    assert [name for name, _ in parse_sse(first.text)] == [
        "planning",
        "delta",
        "committed",
        "continue",
    ]
    assert [name for name, _ in parse_sse(second.text)] == [
        "planning",
        "delta",
        "committed",
        "continue",
    ]
    assert len(llm_client.calls) == 2
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 1

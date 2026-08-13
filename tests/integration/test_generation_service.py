"""Integration coverage for the deterministic single-scene generation coordinator."""

from copy import deepcopy
from pathlib import Path

import pytest

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import ChoiceFrequency, StoryStatus
from storyflow.domain.models import (
    Branch,
    GenerationEvent,
    MemorySnapshot,
    Story,
    StoryConfig,
    StorySegment,
)
from storyflow.llm.fake import FakeLLMClient, StreamInterruptedError
from storyflow.services.generation import GenerationRequest, GenerationService


def make_runtime(
    tmp_path: Path,
    *,
    status: StoryStatus = StoryStatus.IDLE,
) -> tuple[Database, StoryRepository, Story, Branch]:
    """Create one ready story and its empty current branch in real SQLite."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    repository = StoryRepository(database)
    story = repository.create_story(
        Story(
            session_id="generation-session",
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
    """Return three distinct provider options with structured hidden effects."""
    return {
        "type": "decision",
        "reason": "The storm closes both known roads.",
        "options": [
            {"text": "Follow the signal fire", "effects": {"route": "fire"}, "position": 0},
            {"text": "Cross the broken bridge", "effects": {"route": "bridge"}, "position": 1},
            {"text": "Descend into the cloud", "effects": {"route": "cloud"}, "position": 2},
        ],
    }


@pytest.mark.asyncio
async def test_fifth_committed_scene_updates_the_branch_rolling_summary(tmp_path: Path) -> None:
    _, repository, story, branch = make_runtime(tmp_path)
    for sequence in range(1, 5):
        current = repository.get_branch(branch.id)
        assert current is not None
        repository.commit_segment_bundle(
            StorySegment(
                story_id=story.id,
                branch_id=branch.id,
                parent_segment_id=current.head_segment_id,
                sequence=sequence,
                content=f"场景 {sequence}",
                summary=f"摘要 {sequence}",
                generation_key=f"summary-seed-{sequence}",
                status="completed",
            )
        )
    repository.save_memory_snapshot(
        MemorySnapshot(story_id=story.id, branch_id=branch.id, rolling_summary="旧摘要")
    )
    llm_client = FakeLLMClient(
        json_responses=[valid_plan(), {"rolling_summary": "前五幕压缩摘要"}],
        text_responses=[["第五个场景。"]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="summary-scene-5",
            context={},
        )
    )

    latest = repository.get_latest_memory_snapshot(branch.id)
    assert result.segment is not None and result.segment.sequence == 5
    assert latest is not None
    assert latest.segment_id == result.segment.id
    assert latest.rolling_summary == "前五幕压缩摘要"


@pytest.mark.asyncio
async def test_pause_request_stops_after_committing_the_current_scene(tmp_path: Path) -> None:
    _, repository, story, branch = make_runtime(tmp_path)
    repository.request_pause(story.id)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["当前场景仍然完整保存。"]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="pause-after-scene",
            context={},
        )
    )

    persisted = repository.get_story(story.id)
    assert result.segment is not None
    assert result.content == "当前场景仍然完整保存。"
    assert result.status is StoryStatus.PAUSED
    assert persisted is not None
    assert persisted.status is StoryStatus.PAUSED
    assert persisted.pause_requested is False


@pytest.mark.asyncio
async def test_valid_no_choice_flow_records_states_and_commits_one_bundle(
    tmp_path: Path,
) -> None:
    """Dropping a phase, chunk, segment, or event breaks one complete scene generation."""
    database, repository, story, branch = make_runtime(tmp_path)
    context = {"story_bible": {"tone": "hopeful"}, "recent_scenes": ["Opening"]}
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["The storm opened ", "a silver road."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="scene-1",
            context=context,
        )
    )

    assert result.status is StoryStatus.IDLE
    assert result.content == "The storm opened a silver road."
    assert result.error_code is None
    assert result.choice_point is None
    assert result.segment is not None
    assert result.segment.content == result.content
    assert result.segment.sequence == 1
    assert result.segment.parent_segment_id is None
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.status is StoryStatus.IDLE
    assert repository.get_branch(branch.id) == branch.model_copy(
        update={"head_segment_id": result.segment.id}
    )
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM choice_points").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 1
        event_row = connection.execute("SELECT payload FROM generation_events").fetchone()
    event = GenerationEvent.model_validate_json(event_row["payload"])
    assert event.event_type == "committed"
    assert event.state_sequence == [
        StoryStatus.IDLE,
        StoryStatus.PLANNING,
        StoryStatus.STREAMING,
        StoryStatus.COMMITTING,
        StoryStatus.IDLE,
    ]
    assert event.output_size == len(result.content)
    assert [call["operation"] for call in llm_client.calls] == [
        "generate_json",
        "stream_text",
    ]
    assert "scene_director_v1" in str(llm_client.calls[0]["prompt"])
    assert llm_client.calls[0]["context"] == context
    assert "scene_writer_v1" in str(llm_client.calls[1]["prompt"])
    writer_context = llm_client.calls[1]["context"]
    assert isinstance(writer_context, dict)
    assert writer_context["story_bible"] == {"tone": "hopeful"}
    assert writer_context["scene_plan"] == {
        **valid_plan(),
        "scene_complete": True,
    }
    assert context == {
        "story_bible": {"tone": "hopeful"},
        "recent_scenes": ["Opening"],
    }


@pytest.mark.asyncio
async def test_valid_choice_flow_commits_exactly_three_options_and_waits(
    tmp_path: Path,
) -> None:
    """Ignoring an eligible validated suggestion loses the required reader decision."""
    database, repository, story, branch = make_runtime(tmp_path)
    suggestion = valid_choice_suggestion()
    llm_client = FakeLLMClient(
        json_responses=[valid_plan(choice_suggestion=suggestion)],
        text_responses=[["Mira reached the broken bridge."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="choice-scene",
            context={"arc": "Find the observatory"},
            scenes_since_last_choice=2,
        )
    )

    assert result.status is StoryStatus.WAITING_CHOICE
    assert result.error_code is None
    assert result.segment is not None
    assert result.choice_point is not None
    assert result.choice_point.segment_id == result.segment.id
    assert [option.text for option in result.choice_point.options] == [
        "Follow the signal fire",
        "Cross the broken bridge",
        "Descend into the cloud",
    ]
    assert all(
        option.choice_point_id == result.choice_point.id
        for option in result.choice_point.options
    )
    persisted_story = repository.get_story(story.id)
    assert persisted_story is not None
    assert persisted_story.status is StoryStatus.WAITING_CHOICE
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
        event_row = connection.execute("SELECT payload FROM generation_events").fetchone()
    assert counts == {
        "story_segments": 1,
        "choice_points": 1,
        "choice_options": 3,
        "generation_events": 1,
    }
    event = GenerationEvent.model_validate_json(event_row["payload"])
    assert event.state_sequence == [
        StoryStatus.IDLE,
        StoryStatus.PLANNING,
        StoryStatus.STREAMING,
        StoryStatus.COMMITTING,
        StoryStatus.WAITING_CHOICE,
    ]
    writer_plan = llm_client.calls[1]["context"]
    assert isinstance(writer_plan, dict)
    scene_plan = writer_plan["scene_plan"]
    assert isinstance(scene_plan, dict)
    writer_choice = scene_plan["choice_suggestion"]
    assert isinstance(writer_choice, dict)
    assert writer_choice["reason"] == suggestion["reason"]
    assert [option["text"] for option in writer_choice["options"]] == [
        "Follow the signal fire",
        "Cross the broken bridge",
        "Descend into the cloud",
    ]


@pytest.mark.parametrize(
    "start_status",
    [StoryStatus.DRAFT, StoryStatus.WAITING_CHOICE, StoryStatus.PAUSED],
)
@pytest.mark.asyncio
async def test_invalid_start_states_reject_before_llm_and_preserve_story(
    tmp_path: Path,
    start_status: StoryStatus,
) -> None:
    """Permitting a non-IDLE start can consume a model call or overwrite aggregate state."""
    database, repository, story, branch = make_runtime(tmp_path, status=start_status)
    before = story.model_dump(mode="json")
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["This must never be generated."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key=f"rejected-{start_status.value}",
            context={"provider_secret": "must-not-be-sent"},
        )
    )

    assert result.status is start_status
    assert result.error_code == "invalid_generation_state"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert llm_client.calls == []
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == before
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }


@pytest.mark.asyncio
async def test_first_invalid_director_plan_retries_once_then_commits(
    tmp_path: Path,
) -> None:
    """Failing to retry one structural response loses an otherwise valid single scene."""
    database, repository, story, branch = make_runtime(tmp_path)
    context = {"arc": {"stage": "rising"}}
    llm_client = FakeLLMClient(
        json_responses=[
            {"goal": "   ", "conflict": "A storm", "beats": ["A signal appears."]},
            valid_plan(),
        ],
        text_responses=[["The second plan became a complete scene."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="director-retry",
            context=context,
        )
    )

    assert result.status is StoryStatus.IDLE
    assert result.error_code is None
    assert result.segment is not None
    assert [call["operation"] for call in llm_client.calls] == [
        "generate_json",
        "generate_json",
        "stream_text",
    ]
    assert [call["context"] for call in llm_client.calls[:2]] == [context, context]
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_two_invalid_director_plans_return_stable_error_without_formal_rows(
    tmp_path: Path,
) -> None:
    """Accepting or leaking an exhausted invalid plan could expose malformed provider data."""
    database, repository, story, branch = make_runtime(tmp_path)
    before = story.model_dump(mode="json")
    llm_client = FakeLLMClient(
        json_responses=[
            {"goal": "", "conflict": "provider-secret-one", "beats": ["Beat"]},
            {"goal": "Goal", "conflict": "provider-secret-two", "beats": []},
        ]
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="director-invalid",
            context={"prompt_secret": "never-return-this"},
        )
    )

    assert result.status is StoryStatus.ERROR
    assert result.error_code == "director_invalid"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert "provider-secret" not in result.error_code
    assert "prompt_secret" not in result.error_code
    assert [call["operation"] for call in llm_client.calls] == [
        "generate_json",
        "generate_json",
    ]
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == before
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }


@pytest.mark.asyncio
async def test_writer_stream_failure_discards_partial_content_and_returns_stable_error(
    tmp_path: Path,
) -> None:
    """A yielded prefix must not become formal content when the Writer stream interrupts."""
    database, repository, story, branch = make_runtime(tmp_path)
    before = story.model_dump(mode="json")
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[
            [
                "This partial text must disappear. ",
                StreamInterruptedError("provider credential=writer-secret"),
            ]
        ],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="writer-failed",
            context={"prompt": "private writer instructions"},
        )
    )

    assert result.status is StoryStatus.ERROR
    assert result.error_code == "writer_failed"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert "writer-secret" not in result.error_code
    assert "private writer instructions" not in result.error_code
    assert [call["operation"] for call in llm_client.calls] == [
        "generate_json",
        "stream_text",
    ]
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == before
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }


@pytest.mark.asyncio
async def test_duplicate_generation_key_returns_existing_scene_without_new_work(
    tmp_path: Path,
) -> None:
    """Re-running a committed key must not call the model or duplicate formal records."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Only one formal scene is written."]],
    )
    service = GenerationService(repository, llm_client)
    request = GenerationRequest(
        story_id=story.id,
        branch_id=branch.id,
        generation_key="same-generation-key",
        context={"arc": "first"},
    )

    first = await service.generate(request)
    story_after_first = repository.get_story(story.id)
    second = await service.generate(request)

    assert first.segment is not None
    assert second.segment == first.segment
    assert second.content == first.content
    assert second.status is StoryStatus.IDLE
    assert second.error_code is None
    assert len(llm_client.calls) == 2
    assert repository.get_story(story.id) == story_after_first
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 1,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 1,
    }


@pytest.mark.asyncio
async def test_generation_key_owned_by_another_story_is_rejected_before_llm(
    tmp_path: Path,
) -> None:
    """A global key collision must never return or overwrite another story's formal scene."""
    _, first_repository, first_story, first_branch = make_runtime(tmp_path)
    first_segment = StorySegment(
        story_id=first_story.id,
        branch_id=first_branch.id,
        sequence=1,
        content="This scene belongs only to the first story.",
        generation_key="globally-owned-key",
        status="completed",
    )
    first_repository.commit_segment_bundle(first_segment)
    database, repository, story, branch = make_runtime(tmp_path)
    story_before = repository.get_story(story.id)
    llm_client = FakeLLMClient()

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="globally-owned-key",
            context={"story": "second"},
        )
    )

    assert result.status is StoryStatus.IDLE
    assert result.error_code == "invalid_generation_state"
    assert result.segment is None
    assert result.content == ""
    assert llm_client.calls == []
    assert repository.get_story(story.id) == story_before
    assert repository.get_segment(first_segment.id) == first_segment
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_segments").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM generation_events").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_director_request_exception_is_redacted_and_does_not_mutate_inputs(
    tmp_path: Path,
) -> None:
    """A provider failure must not escape with secrets or alter caller-owned context."""
    database, repository, story, branch = make_runtime(tmp_path)
    context = {
        "fixed_memory": {"secret": "prompt-only-value"},
        "characters": [{"name": "Mira", "facts": ["has a map"]}],
    }
    context_before = deepcopy(context)
    story_before = story.model_dump(mode="json")
    request = GenerationRequest(
        story_id=story.id,
        branch_id=branch.id,
        generation_key="director-request-failed",
        context=context,
    )
    llm_client = FakeLLMClient(
        json_responses=[TimeoutError("provider token=director-secret timed out")]
    )

    result = await GenerationService(repository, llm_client).generate(request)

    assert result.status is StoryStatus.ERROR
    assert result.error_code == "director_failed"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert "director-secret" not in result.error_code
    assert "prompt-only-value" not in result.error_code
    assert context == context_before
    assert request.context is context
    assert [call["operation"] for call in llm_client.calls] == ["generate_json"]
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == story_before
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }


@pytest.mark.asyncio
async def test_unexpected_director_exception_is_classified_and_redacted(
    tmp_path: Path,
) -> None:
    """An untyped provider crash must not escape the stable GenerationResult boundary."""
    database, repository, story, branch = make_runtime(tmp_path)
    story_before = story.model_dump(mode="json")
    llm_client = FakeLLMClient(
        json_responses=[RuntimeError("unexpected provider secret=director-crash-secret")]
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="unexpected-director-failed",
            context={"private_prompt": "must-not-leak"},
        )
    )

    assert result.status is StoryStatus.ERROR
    assert result.error_code == "director_failed"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert "director-crash-secret" not in result.error_code
    assert "must-not-leak" not in result.error_code
    assert [call["operation"] for call in llm_client.calls] == ["generate_json"]
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == story_before
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts == {
        "story_segments": 0,
        "choice_points": 0,
        "choice_options": 0,
        "generation_events": 0,
    }


@pytest.mark.asyncio
async def test_late_commit_failure_rolls_back_story_state_scene_and_branch_head(
    tmp_path: Path,
) -> None:
    """A late event collision must undo intermediate status writes and the scene insert."""
    database, repository, story, branch = make_runtime(tmp_path)
    seed = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        sequence=1,
        content="An existing formal scene.",
        generation_key="seed-scene",
        status="completed",
    )
    repository.commit_segment_bundle(
        seed,
        event=GenerationEvent(
            story_id=story.id,
            branch_id=branch.id,
            event_type="committed",
            request_id="late-event-collision",
            duration_ms=0,
            input_token_estimate=0,
            output_size=len(seed.content),
        ),
    )
    story_before = repository.get_story(story.id)
    branch_before = repository.get_branch(branch.id)
    assert story_before is not None
    assert branch_before is not None
    with database.read() as connection:
        counts_before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["This complete buffer must still be rolled back."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="late-event-collision",
            context={"arc": "collision"},
        )
    )

    assert result.status is StoryStatus.ERROR
    assert result.error_code == "commit_failed"
    assert result.segment is None
    assert result.choice_point is None
    assert result.content == ""
    assert repository.get_story(story.id) == story_before
    assert repository.get_branch(branch.id) == branch_before
    assert repository.get_segment_by_generation_key("late-event-collision") is None
    with database.read() as connection:
        counts_after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_segments", "choice_points", "choice_options", "generation_events")
        }
    assert counts_after == counts_before


@pytest.mark.asyncio
async def test_choice_policy_pause_commits_scene_without_a_choice_and_pauses(
    tmp_path: Path,
) -> None:
    """Ignoring the policy's maximum-interval pause would allow unsafe continuation."""
    database, repository, story, branch = make_runtime(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[valid_plan()],
        text_responses=[["Mira stopped where the road vanished."]],
    )

    result = await GenerationService(repository, llm_client).generate(
        GenerationRequest(
            story_id=story.id,
            branch_id=branch.id,
            generation_key="policy-pause",
            context={"arc": "rising"},
            scenes_since_last_choice=3,
        )
    )

    assert result.status is StoryStatus.PAUSED
    assert result.error_code is None
    assert result.segment is not None
    assert result.choice_point is None
    persisted = repository.get_story(story.id)
    assert persisted is not None
    assert persisted.status is StoryStatus.PAUSED
    with database.read() as connection:
        event_row = connection.execute("SELECT payload FROM generation_events").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM choice_points").fetchone()[0] == 0
    event = GenerationEvent.model_validate_json(event_row["payload"])
    assert event.state_sequence == [
        StoryStatus.IDLE,
        StoryStatus.PLANNING,
        StoryStatus.STREAMING,
        StoryStatus.COMMITTING,
        StoryStatus.PAUSED,
    ]

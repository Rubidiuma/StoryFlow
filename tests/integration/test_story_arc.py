"""T13 integration coverage for dynamic story arcs and rolling summary compression."""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from uuid import uuid4

import pytest

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import ChoiceFrequency, StoryStatus
from storyflow.domain.models import (
    Branch,
    CharacterState,
    MemorySnapshot,
    Story,
    StoryArc,
    StoryBible,
    StoryConfig,
    StorySegment,
)
from storyflow.llm.fake import FakeLLMClient
from storyflow.services.context_builder import SceneMemory
from storyflow.services.memory import MemoryService


_CONFIG = StoryConfig(
    genre="fantasy",
    structure="three_act",
    world_background="A world of moving glaciers.",
    protagonist_desc="Zara, a glacier surveyor.",
    important_supporting_characters=None,
    style="terse",
    choice_frequency=ChoiceFrequency.FEW,
    required_elements=None,
    forbidden_elements=None,
    ending_tendency=None,
)


def _setup(tmp_path: Path) -> tuple[Database, StoryRepository, Story, Branch]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    repo = StoryRepository(db)
    story = repo.create_story(
        Story(
            session_id="arc-test",
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.FEW,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    story = repo.set_current_branch(story.id, branch.id)
    return db, repo, story, branch


def _make_snapshot(
    story: Story, branch: Branch, threads: list[str] | None = None, summary: str = ""
) -> MemorySnapshot:
    return MemorySnapshot(
        story_id=story.id,
        branch_id=branch.id,
        characters=[
            CharacterState(
                story_id=story.id,
                branch_id=branch.id,
                name="Zara",
                role="surveyor",
                location="Glacier",
                motivation="Map the ice",
                known_facts=[],
                relationships={},
                alive=True,
            )
        ],
        active_threads=threads or ["Map the glacier"],
        rolling_summary=summary,
        context_version=1,
    )


def _scene(seq: int) -> SceneMemory:
    return SceneMemory(sequence=seq, content=f"Scene {seq} content.", summary=f"S{seq}.")


# ─── Rolling summary trigger ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sequence, expected",
    [
        (0, False),
        (1, False),
        (2, False),
        (3, False),
        (4, False),
        (5, True),
        (6, False),
        (9, False),
        (10, True),
        (15, True),
        (20, True),
    ],
)
def test_rolling_summary_triggers_at_multiples_of_five_only(
    sequence: int, expected: bool
) -> None:
    """Compression must fire exactly at scene 5, 10, 15... and nowhere else."""
    assert MemoryService.should_trigger_rolling_summary(sequence) == expected


# ─── Rolling summary update ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rolling_summary_update_compresses_scenes_and_returns_new_snapshot(
    tmp_path: Path,
) -> None:
    """LLM response replaces the rolling_summary field in the returned snapshot."""
    _, repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, summary="Old summary.")
    scenes = [_scene(i) for i in range(1, 6)]
    llm = FakeLLMClient(json_responses=[{"rolling_summary": "前五个场景的压缩摘要。"}])

    updated = await MemoryService.update_rolling_summary(snapshot, scenes, llm)

    assert updated.rolling_summary == "前五个场景的压缩摘要。"
    assert updated.active_threads == snapshot.active_threads
    assert updated.context_version == snapshot.context_version + 1
    assert len(llm.calls) == 1
    assert llm.calls[0]["operation"] == "generate_json"


@pytest.mark.asyncio
async def test_committed_content_preserved_when_summary_update_fails(
    tmp_path: Path,
) -> None:
    """LLM failure during summary update must leave the original snapshot unchanged."""
    _, repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, summary="Original.")
    scenes = [_scene(i) for i in range(1, 6)]
    llm = FakeLLMClient(json_responses=[RuntimeError("LLM down")])

    updated = await MemoryService.update_rolling_summary(snapshot, scenes, llm)

    # Returns original snapshot unchanged when LLM fails
    assert updated.rolling_summary == "Original."
    assert updated.context_version == snapshot.context_version


@pytest.mark.asyncio
async def test_malformed_summary_response_returns_original_snapshot(
    tmp_path: Path,
) -> None:
    """Non-string or missing 'rolling_summary' in response falls back to original."""
    _, repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, summary="Preserved.")
    scenes = [_scene(1)]
    llm = FakeLLMClient(json_responses=[{"wrong_key": "data"}])

    updated = await MemoryService.update_rolling_summary(snapshot, scenes, llm)

    assert updated.rolling_summary == "Preserved."
    assert updated.context_version == snapshot.context_version


# ─── Per-scene structured memory (continuity / causality) ───────────────────────


@pytest.mark.asyncio
async def test_scene_memory_update_evolves_threads_and_clues(tmp_path: Path) -> None:
    """A committed scene evolves active threads and foreshadowing for later scenes."""
    _, _repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, threads=["Map the glacier"])
    llm = FakeLLMClient(
        json_responses=[
            {
                "active_threads": ["Reach the frozen archive"],
                "foreshadowing": [
                    {"id": "lantern", "description": "A lantern burns under the ice", "status": "planted"}
                ],
            }
        ]
    )

    updated = await MemoryService.update_from_scene(
        snapshot, "Zara descended into the glacier and saw a distant light.", llm
    )

    assert updated is not snapshot
    assert updated.active_threads == ["Reach the frozen archive"]
    assert updated.foreshadowing == {"lantern": "A lantern burns under the ice"}
    assert updated.context_version == snapshot.context_version + 1
    assert len(llm.calls) == 1
    assert "memory_update_v1" in str(llm.calls[0]["prompt"])


@pytest.mark.asyncio
async def test_scene_memory_update_no_change_returns_same_snapshot(tmp_path: Path) -> None:
    """An empty update leaves the snapshot untouched so no redundant version is stored."""
    _, _repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch)
    llm = FakeLLMClient(json_responses=[{}])

    updated = await MemoryService.update_from_scene(snapshot, "A quiet scene.", llm)

    assert updated is snapshot


@pytest.mark.asyncio
async def test_scene_memory_update_survives_llm_failure(tmp_path: Path) -> None:
    """An LLM failure during memory extraction must not disturb committed memory."""
    _, _repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, threads=["Original thread"])
    llm = FakeLLMClient(json_responses=[RuntimeError("provider down")])

    updated = await MemoryService.update_from_scene(snapshot, "A scene.", llm)

    assert updated is snapshot
    assert updated.active_threads == ["Original thread"]


@pytest.mark.asyncio
async def test_scene_memory_update_skips_empty_scene(tmp_path: Path) -> None:
    """An empty scene never calls the model."""
    _, _repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch)
    llm = FakeLLMClient(json_responses=[])

    updated = await MemoryService.update_from_scene(snapshot, "   ", llm)

    assert updated is snapshot
    assert llm.calls == []


# ─── Arc management ────────────────────────────────────────────────────────────


def test_active_arc_does_not_trigger_next_arc(tmp_path: Path) -> None:
    """An arc with status 'active' must not prompt arc generation."""
    _, repo, story, branch = _setup(tmp_path)
    arc = StoryArc(
        story_id=story.id,
        branch_id=branch.id,
        goal="Reach the glacier summit.",
        conflict="The route is blocked by a crevasse.",
        status="active",
        exit_conditions=["Summit reached"],
    )
    assert MemoryService.should_generate_next_arc(arc) is False


def test_completed_arc_triggers_next_arc(tmp_path: Path) -> None:
    """An arc with status 'completed' must trigger next-arc generation."""
    _, repo, story, branch = _setup(tmp_path)
    arc = StoryArc(
        story_id=story.id,
        branch_id=branch.id,
        goal="Reach the summit.",
        conflict="The crevasse.",
        status="completed",
    )
    assert MemoryService.should_generate_next_arc(arc) is True


@pytest.mark.asyncio
async def test_generate_next_arc_creates_valid_arc_from_llm_response(
    tmp_path: Path,
) -> None:
    """Next arc generated from LLM response has story_id/branch_id set and status 'active'."""
    _, repo, story, branch = _setup(tmp_path)
    bible = StoryBible(
        story_id=story.id,
        world_rules="Glaciers are alive.",
        tone_rules="Terse and cold.",
        protagonist_core="Zara is stoic.",
    )
    snapshot = _make_snapshot(story, branch, threads=["Find the hidden pass"])
    llm = FakeLLMClient(
        json_responses=[
            {
                "goal": "Descend into the glacier cave.",
                "conflict": "The ice is cracking.",
                "stage": "rising",
                "exit_conditions": ["Cave explored"],
                "summary": "",
            }
        ]
    )

    new_arc = await MemoryService.generate_next_arc(story.id, branch.id, bible, snapshot, llm)

    assert new_arc.story_id == story.id
    assert new_arc.branch_id == branch.id
    assert new_arc.status == "active"
    assert new_arc.goal == "Descend into the glacier cave."
    assert new_arc.conflict == "The ice is cracking."
    assert len(llm.calls) == 1


def test_arc_payload_contradicting_world_rules_raises_value_error() -> None:
    """A new arc that negates a fixed world rule must be rejected."""
    from storyflow.services.memory import validate_arc_not_contradicting_facts

    bible = StoryBible(
        story_id=uuid4(),
        world_rules="Glaciers cannot be melted by fire.",
        tone_rules="Terse.",
        protagonist_core="Stoic.",
    )
    contradicting_arc = {
        "goal": "Melt the glacier with fire.",
        "conflict": "The fire is not hot enough.",
    }
    with pytest.raises(ValueError, match="contradicts"):
        validate_arc_not_contradicting_facts(bible, contradicting_arc)


def test_arc_payload_consistent_with_world_rules_passes() -> None:
    """An arc consistent with world rules and facts must not raise."""
    from storyflow.services.memory import validate_arc_not_contradicting_facts

    bible = StoryBible(
        story_id=uuid4(),
        world_rules="Glaciers cannot be melted by fire.",
        tone_rules="Terse.",
        protagonist_core="Stoic.",
    )
    valid_arc = {
        "goal": "Navigate around the glacier using ice bridges.",
        "conflict": "The bridges are unstable.",
    }
    validate_arc_not_contradicting_facts(bible, valid_arc)  # Must not raise


# ─── End-to-end: 12 consecutive scenes trigger summary at scene 5 and 10 ────────


@pytest.mark.asyncio
async def test_rolling_summary_triggered_at_scene_5_and_10_in_sequence(
    tmp_path: Path,
) -> None:
    """Simulate 12 scene commits; rolling summary must be invoked at sequences 5 and 10."""
    _, repo, story, branch = _setup(tmp_path)
    snapshot = _make_snapshot(story, branch, summary="Initial.")
    repo.save_memory_snapshot(snapshot)

    summary_call_count = 0
    for seq in range(1, 13):
        # Commit a segment
        parent_id = repo.get_branch(branch.id).head_segment_id  # type: ignore[union-attr]
        seg = StorySegment(
            story_id=story.id,
            branch_id=branch.id,
            parent_segment_id=parent_id,
            sequence=seq,
            content=f"Scene {seq}.",
            summary=f"S{seq}.",
            generation_key=f"key-{seq}",
            status="completed",
        )
        repo.commit_segment_bundle(seg, None)

        # Simulate post-commit rolling summary check
        if MemoryService.should_trigger_rolling_summary(seq):
            summary_call_count += 1
            scenes = [_scene(i) for i in range(max(1, seq - 4), seq + 1)]
            latest = repo.get_latest_memory_snapshot(branch.id)
            assert latest is not None
            llm = FakeLLMClient(
                json_responses=[{"rolling_summary": f"第 {seq} 个场景后的摘要。"}]
            )
            updated = await MemoryService.update_rolling_summary(latest, scenes, llm)
            repo.save_memory_snapshot(
                updated.model_copy(update={"id": uuid4(), "segment_id": seg.id}, deep=True)
            )

    assert summary_call_count == 2  # triggered at seq=5 and seq=10
    final_snapshot = repo.get_latest_memory_snapshot(branch.id)
    assert final_snapshot is not None
    assert final_snapshot.rolling_summary == "第 10 个场景后的摘要。"

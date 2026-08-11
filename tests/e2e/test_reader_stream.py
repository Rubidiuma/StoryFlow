"""T15 e2e coverage: streaming reader page and auto-continue logic."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

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
    ChoiceOption,
    ChoicePoint,
    Story,
    StoryConfig,
    StorySegment,
)
from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app


_CONFIG = StoryConfig(
    genre="奇幻",
    structure="三幕式",
    world_background="浮动的冰川帝国。",
    protagonist_desc="卡尔，地图绘制者。",
    important_supporting_characters=None,
    style="克制",
    choice_frequency=ChoiceFrequency.FEW,
    required_elements=None,
    forbidden_elements=None,
    ending_tendency=None,
)


def _setup(tmp_path: Path) -> tuple[Database, StoryRepository]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    return db, StoryRepository(db)


def _make_idle_story(repo: StoryRepository) -> tuple[Story, Branch]:
    story = repo.create_story(
        Story(
            session_id="reader-e2e",
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.FEW,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    story = repo.set_current_branch(story.id, branch.id)
    return story, repo.get_branch(branch.id)  # type: ignore[return-value]


def _commit_segment(
    repo: StoryRepository, story: Story, branch: Branch, seq: int, key: str
) -> StorySegment:
    seg = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        parent_segment_id=branch.head_segment_id,
        sequence=seq,
        content=f"场景 {seq} 正文内容。",
        summary=f"摘要 {seq}。",
        generation_key=key,
        status="completed",
    )
    repo.commit_segment_bundle(seg, None)
    updated = repo.get_branch(branch.id)
    assert updated is not None
    return repo.get_segment(updated.head_segment_id)  # type: ignore[arg-type]


def _force_status(db: Database, story: Story, status: StoryStatus) -> Story:
    updated = story.model_copy(update={"status": status, "version": story.version + 1})
    with db.transaction() as conn:
        conn.execute("UPDATE stories SET payload = ? WHERE id = ?",
                     (updated.model_dump_json(), str(story.id)))
    return updated


# ─── T15 Tests ────────────────────────────────────────────────────────────────


def test_reader_page_renders_with_generation_data_attributes(tmp_path: Path) -> None:
    """Reader page must expose story-id, branch-id and status for reader.js."""
    _, repo = _setup(tmp_path)
    story, branch = _make_idle_story(repo)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f'data-story-id="{story.id}"' in response.text
    assert f'data-branch-id="{branch.id}"' in response.text
    assert 'data-story-status="IDLE"' in response.text


def test_reader_shows_committed_segments_in_sequence_order(tmp_path: Path) -> None:
    """All committed segments appear in the reader in ascending sequence."""
    _, repo = _setup(tmp_path)
    story, branch = _make_idle_story(repo)
    for seq in range(1, 4):
        branch = repo.get_branch(branch.id)  # type: ignore[assignment]
        _commit_segment(repo, story, branch, seq, f"k-{seq}")
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader")

    assert response.status_code == 200
    for seq in range(1, 4):
        assert f'data-sequence="{seq}"' in response.text
        assert f"场景 {seq} 正文内容。" in response.text
    # Sequence order preserved: pos of seq 1 < seq 2 < seq 3
    pos1 = response.text.index('data-sequence="1"')
    pos2 = response.text.index('data-sequence="2"')
    pos3 = response.text.index('data-sequence="3"')
    assert pos1 < pos2 < pos3


def test_sse_delivers_planning_delta_committed_continue_in_order(tmp_path: Path) -> None:
    """Generation SSE must deliver planning, delta(s), committed, then continue."""
    _, repo = _setup(tmp_path)
    story, branch = _make_idle_story(repo)
    llm = FakeLLMClient(
        json_responses=[{
            "goal": "登顶冰川",
            "conflict": "裂缝挡路",
            "beats": ["卡尔观察路线", "她找到冰桥"],
            "scene_complete": True,
        }],
        text_responses=[["冰冷的", "风", "呼啸着。"]],
    )
    client = TestClient(create_app(repository=repo, llm_client=llm))

    with client.stream("POST", f"/api/stories/{story.id}/generate", json={
        "branch_id": str(branch.id),
        "generation_key": "e2e-gen-1",
        "context": {"story": "brief"},
    }) as resp:
        raw = resp.read().decode()

    events = _parse_sse(raw)
    names = [e["event"] for e in events]
    assert names[0] == "planning"
    assert "delta" in names
    assert "committed" in names
    terminal = names[-1]
    assert terminal in ("continue", "choice", "paused", "error")
    assert terminal == "continue"  # No choice suggestion → continue


def test_idle_reader_has_autogenerate_attribute(tmp_path: Path) -> None:
    """IDLE story reader must carry the data-autogenerate hook for reader.js."""
    _, repo = _setup(tmp_path)
    story, branch = _make_idle_story(repo)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader")

    assert 'data-autogenerate="true"' in response.text


def test_waiting_choice_reader_shows_three_options_and_custom_input(
    tmp_path: Path,
) -> None:
    """WAITING_CHOICE reader shows exactly 3 option buttons + custom action input."""
    db, repo = _setup(tmp_path)
    story, branch = _make_idle_story(repo)
    choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="十字路口。",
        status="pending",
        options=[
            ChoiceOption(text="向左走", effects={"route_change": "left"}, position=0),
            ChoiceOption(text="向右走", effects={"route_change": "right"}, position=1),
            ChoiceOption(text="原地休息", effects={"route_change": "rest"}, position=2),
        ],
    )
    seg = StorySegment(
        story_id=story.id, branch_id=branch.id,
        sequence=1, content="抵达岔路口。", summary="岔路口。",
        generation_key="k-choice", status="completed",
    )
    repo.commit_segment_bundle(seg, choice)
    story = _force_status(db, story, StoryStatus.WAITING_CHOICE)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader")

    assert response.status_code == 200
    assert 'data-view="choice-panel"' in response.text
    option_count = response.text.count("data-choice-option-id")
    assert option_count == 3
    assert 'name="custom_action"' in response.text


# ─── Helper ───────────────────────────────────────────────────────────────────


def _parse_sse(raw: str) -> list[dict[str, object]]:
    """Parse raw SSE wire bytes into a list of event envelopes."""
    events: list[dict[str, object]] = []
    for block in raw.strip().split("\n\n"):
        data_line = next((l for l in block.splitlines() if l.startswith("data:")), None)
        if data_line:
            events.append(json.loads(data_line[5:].strip()))
    return events

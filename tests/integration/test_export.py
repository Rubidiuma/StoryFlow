"""T20 integration coverage for Markdown export of the current branch path."""

from __future__ import annotations

import warnings
from pathlib import Path

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
from storyflow.main import create_app

_CONFIG = StoryConfig(
    genre="奇幻",
    structure="三幕式",
    world_background="浮岛漂浮在永恒的云海上方。",
    protagonist_desc="弥拉，制图师。",
    important_supporting_characters="向导洛恩。",
    style="克制而明亮",
    choice_frequency=ChoiceFrequency.FEW,
    required_elements="飞艇",
    forbidden_elements=None,
    ending_tendency="保留希望",
)


def _setup(tmp_path: Path) -> tuple[Database, StoryRepository, Story, Branch]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    repo = StoryRepository(db)
    story = repo.create_story(
        Story(
            session_id="export-session",
            title="云海尽头",
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.FEW,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    story = repo.set_current_branch(story.id, branch.id)
    return db, repo, story, repo.get_branch(branch.id)  # type: ignore[return-value]


def _add_segment(
    repo: StoryRepository,
    story: Story,
    branch: Branch,
    seq: int,
    content: str,
    choice: ChoicePoint | None = None,
) -> StorySegment:
    parent = repo.get_branch(branch.id)
    assert parent is not None
    seg = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        parent_segment_id=parent.head_segment_id,
        sequence=seq,
        content=content,
        summary=f"摘要{seq}",
        generation_key=f"key-{seq}",
        status="completed",
    )
    repo.commit_segment_bundle(seg, choice)
    updated = repo.get_branch(branch.id)
    assert updated is not None
    return repo.get_segment(updated.head_segment_id)  # type: ignore[arg-type]


# ─── T20 Tests ────────────────────────────────────────────────────────────────


def test_export_contains_title_and_genre_setting(tmp_path: Path) -> None:
    """Exported Markdown must include the story title and genre from the config."""
    db, repo, story, branch = _setup(tmp_path)
    _add_segment(repo, story, branch, 1, "弥拉跨越了第一道云桥。")
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/api/stories/{story.id}/export.md?branch={branch.id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "云海尽头" in response.text
    assert "奇幻" in response.text


def test_export_contains_segments_in_sequence_order(tmp_path: Path) -> None:
    """Segments must appear in sequence order, not insertion order."""
    db, repo, story, branch = _setup(tmp_path)
    _add_segment(repo, story, branch, 1, "第一场景：弥拉出发了。")
    branch = repo.get_branch(branch.id)  # type: ignore[assignment]
    _add_segment(repo, story, branch, 2, "第二场景：她到达了云海边缘。")
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/api/stories/{story.id}/export.md?branch={branch.id}")

    text = response.text
    assert "第一场景：弥拉出发了。" in text
    assert "第二场景：她到达了云海边缘。" in text
    assert text.index("第一场景") < text.index("第二场景")


def test_export_includes_selected_choice_text_but_not_effects(tmp_path: Path) -> None:
    """Exported Markdown shows the chosen option text; hidden effects must not appear."""
    db, repo, story, branch = _setup(tmp_path)
    choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="路口分叉。",
        status="pending",
        options=[
            ChoiceOption(
                text="进入酒馆",
                effects={"route_change": "tavern"},
                position=0,
            ),
            ChoiceOption(text="越过桥", effects={"route_change": "bridge"}, position=1),
            ChoiceOption(text="原地休息", effects={"route_change": "rest"}, position=2),
        ],
    )
    seg = _add_segment(repo, story, branch, 1, "弥拉到达了路口。", choice)

    # submit the choice so it's "selected"
    loaded = repo.get_choice_point_for_segment(seg.id)
    assert loaded is not None
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id, branch_id=branch.id, segment_id=seg.id,
            characters=[CharacterState(story_id=story.id, branch_id=branch.id,
                                       name="弥拉", role="protagonist",
                                       location="路口", motivation="找到失踪的导师",
                                       known_facts=[], relationships={}, alive=True)],
            active_threads=["寻找导师"],
            context_version=1,
        )
    )
    with db.transaction() as conn:
        updated = story.model_copy(update={"status": StoryStatus.WAITING_CHOICE, "version": story.version + 1})
        conn.execute("UPDATE stories SET payload = ? WHERE id = ?",
                     (updated.model_dump_json(), str(story.id)))
    repo.submit_choice(loaded.id, loaded.version, option_id=loaded.options[0].id)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/api/stories/{story.id}/export.md")

    assert response.status_code == 200
    assert "进入酒馆" in response.text
    assert "tavern" not in response.text  # effects must be hidden
    assert "route_change" not in response.text


def test_export_excludes_sibling_branch_segments(tmp_path: Path) -> None:
    """Sibling branch segments created after fork must not appear in the export."""
    db, repo, story, branch = _setup(tmp_path)
    choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="关键选择。",
        status="pending",
        options=[
            ChoiceOption(text="选A", effects={"route_change": "a"}, position=0),
            ChoiceOption(text="选B", effects={"route_change": "b"}, position=1),
            ChoiceOption(text="选C", effects={"route_change": "c"}, position=2),
        ],
    )
    seg = _add_segment(repo, story, branch, 1, "共同起点。", choice)
    loaded = repo.get_choice_point_for_segment(seg.id)
    assert loaded is not None
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id, branch_id=branch.id, segment_id=seg.id,
            characters=[], active_threads=[], context_version=1,
        )
    )
    with db.transaction() as conn:
        upd = story.model_copy(update={"status": StoryStatus.WAITING_CHOICE, "version": story.version + 1})
        conn.execute("UPDATE stories SET payload = ? WHERE id = ?",
                     (upd.model_dump_json(), str(story.id)))
    repo.submit_choice(loaded.id, loaded.version, option_id=loaded.options[0].id)

    # Create sibling fork branch and add a segment ONLY to the sibling
    sibling, _ = repo.fork_at_choice(loaded.id, branch_name="Fork")
    sibling_seg = StorySegment(
        story_id=story.id, branch_id=sibling.id,
        parent_segment_id=sibling.head_segment_id,
        sequence=2, content="这是另一条路的内容，不应出现。",
        summary="fork分支", generation_key="fork-key", status="completed",
    )
    repo.commit_segment_bundle(sibling_seg, None)

    client = TestClient(create_app(repository=repo))
    response = client.get(
        f"/api/stories/{story.id}/export.md?branch={branch.id}"
    )

    assert response.status_code == 200
    assert "共同起点。" in response.text
    assert "这是另一条路的内容，不应出现。" not in response.text

    fork_response = client.get(
        f"/api/stories/{story.id}/export.md?branch={sibling.id}"
    )
    assert fork_response.status_code == 200
    assert "这是另一条路的内容，不应出现。" in fork_response.text


def test_export_rejects_branch_from_another_story(tmp_path: Path) -> None:
    _, repo, story, _ = _setup(tmp_path)
    other = repo.create_story(
        Story(
            session_id="other",
            title="其他故事",
            choice_frequency=_CONFIG.choice_frequency,
            config=_CONFIG,
        )
    )
    other_branch = repo.create_branch(Branch(story_id=other.id, name="Other"))
    client = TestClient(create_app(repository=repo))

    response = client.get(
        f"/api/stories/{story.id}/export.md?branch={other_branch.id}"
    )

    assert response.status_code == 404


def test_export_returns_404_for_missing_story(tmp_path: Path) -> None:
    """Export endpoint must return 404 for unknown story IDs."""
    from uuid import uuid4
    db, repo, story, branch = _setup(tmp_path)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/api/stories/{uuid4()}/export.md")

    assert response.status_code == 404

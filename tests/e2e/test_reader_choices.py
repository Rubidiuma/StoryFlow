"""T16 e2e coverage: choice submission, pause/resume, and branch UI."""

from __future__ import annotations

import warnings
from pathlib import Path
from uuid import UUID

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
    genre="悬疑",
    structure="三幕式",
    world_background="海底废弃基地。",
    protagonist_desc="水下考古学家李云。",
    important_supporting_characters=None,
    style="紧张",
    choice_frequency=ChoiceFrequency.MEDIUM,
    required_elements=None,
    forbidden_elements=None,
    ending_tendency=None,
)


def _setup(tmp_path: Path) -> tuple[Database, StoryRepository]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    return db, StoryRepository(db)


def _make_story_with_branch(repo: StoryRepository) -> tuple[Story, Branch]:
    story = repo.create_story(
        Story(
            session_id="reader-choices-e2e",
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.MEDIUM,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    story = repo.set_current_branch(story.id, branch.id)
    return story, repo.get_branch(branch.id)  # type: ignore[return-value]


def _force_status(db: Database, story: Story, status: StoryStatus) -> Story:
    updated = story.model_copy(update={"status": status, "version": story.version + 1})
    with db.transaction() as conn:
        conn.execute("UPDATE stories SET payload = ? WHERE id = ?",
                     (updated.model_dump_json(), str(story.id)))
    return updated


def _commit_choice_segment(
    repo: StoryRepository, story: Story, branch: Branch
) -> tuple[StorySegment, ChoicePoint]:
    """Commit one segment with a 3-option choice point."""
    seg = StorySegment(
        story_id=story.id, branch_id=branch.id,
        sequence=1, content="抵达岔路口。", summary="岔路口。",
        generation_key="k-ch", status="completed",
    )
    choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="两条路，一条通向实验室，一条通向出口。",
        status="pending",
        options=[
            ChoiceOption(text="进入实验室", effects={"route_change": "lab"}, position=0),
            ChoiceOption(text="径直出口", effects={"route_change": "exit"}, position=1),
            ChoiceOption(text="观察后决定", effects={"route_change": "observe"}, position=2),
        ],
    )
    repo.commit_segment_bundle(seg, choice)
    loaded = repo.get_choice_point_for_segment(seg.id)
    assert loaded is not None
    branch_updated = repo.get_branch(branch.id)
    assert branch_updated is not None
    seg_updated = repo.get_segment(branch_updated.head_segment_id)  # type: ignore[arg-type]
    assert seg_updated is not None
    return seg_updated, loaded


# ─── T16 Tests ────────────────────────────────────────────────────────────────


def test_choice_submission_transitions_story_to_idle(tmp_path: Path) -> None:
    """POST select on a WAITING_CHOICE story must return IDLE in the response."""
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    seg, choice = _commit_choice_segment(repo, story, branch)
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id, branch_id=branch.id, segment_id=seg.id,
            characters=[
                CharacterState(story_id=story.id, branch_id=branch.id,
                               name="李云", role="考古学家",
                               location="走廊", motivation="找到出口",
                               known_facts=[], relationships={}, alive=True)
            ],
            active_threads=["调查基地"],
            context_version=1,
        )
    )
    story = _force_status(db, story, StoryStatus.WAITING_CHOICE)
    client = TestClient(create_app(repository=repo))

    response = client.post(
        f"/api/choices/{choice.id}/select",
        json={"choice_version": choice.version, "option_id": str(choice.options[0].id)},
    )

    assert response.status_code == 200
    assert response.json()["story_status"] == "IDLE"
    assert response.json()["status"] == "success"


def test_paused_reader_has_resume_not_autogenerate(tmp_path: Path) -> None:
    """PAUSED story reader shows resume button and omits data-autogenerate."""
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    story = _force_status(db, story, StoryStatus.PAUSED)
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader")

    assert response.status_code == 200
    assert "data-resume" in response.text
    assert "data-autogenerate" not in response.text


def test_reader_exposes_summary_export_and_historical_branch_action(tmp_path: Path) -> None:
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    seg, choice = _commit_choice_segment(repo, story, branch)
    story = _force_status(db, story, StoryStatus.WAITING_CHOICE)
    repo.submit_choice(choice.id, choice.version, option_id=choice.options[0].id)
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id,
            branch_id=branch.id,
            segment_id=seg.id,
            rolling_summary="李云已经进入海底基地。",
        )
    )
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader?branch={branch.id}")

    assert response.status_code == 200
    assert "剧情摘要" in response.text
    assert "李云已经进入海底基地。" in response.text
    assert "导出 Markdown" in response.text
    assert f"/api/stories/{story.id}/export.md?branch={branch.id}" in response.text
    assert "从这里重新选择" in response.text
    assert choice.options[0].text in response.text
    assert "route_change" not in response.text


def test_branch_fork_api_returns_new_branch_id(tmp_path: Path) -> None:
    """POST /api/choices/{id}/branch on a selected choice returns a new branch."""
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    seg, choice = _commit_choice_segment(repo, story, branch)
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id, branch_id=branch.id, segment_id=seg.id,
            characters=[],
            active_threads=["调查基地"],
            context_version=1,
        )
    )
    story = _force_status(db, story, StoryStatus.WAITING_CHOICE)
    repo.submit_choice(choice.id, choice.version, option_id=choice.options[0].id)
    client = TestClient(create_app(repository=repo))

    response = client.post(
        f"/api/choices/{choice.id}/branch",
        json={"name": "备用路径"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "branch_id" in data
    assert "choice_id" in data
    assert data["story_id"] == str(story.id)
    assert data["fork_segment_id"] == str(seg.id)
    updated_story = repo.get_story(story.id)
    pending_choice = repo.get_current_choice_for_branch(data["branch_id"])
    assert updated_story is not None
    assert updated_story.current_branch_id == UUID(data["branch_id"])
    assert updated_story.status is StoryStatus.WAITING_CHOICE
    assert pending_choice is not None
    assert data["choice_id"] == str(pending_choice.id)


def test_reader_with_branch_param_shows_correct_branch(tmp_path: Path) -> None:
    """GET /stories/{id}/reader?branch=<id> displays data-branch-id of the requested branch."""
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    seg, choice = _commit_choice_segment(repo, story, branch)
    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id, branch_id=branch.id, segment_id=seg.id,
            characters=[],
            active_threads=["调查基地"],
            context_version=1,
        )
    )
    story = _force_status(db, story, StoryStatus.WAITING_CHOICE)
    repo.submit_choice(choice.id, choice.version, option_id=choice.options[0].id)
    fork_response = repo.fork_at_choice(choice.id, branch_name="备用路径")
    new_branch = fork_response[0]
    client = TestClient(create_app(repository=repo))

    response = client.get(f"/stories/{story.id}/reader?branch={new_branch.id}")

    assert response.status_code == 200
    assert f'data-branch-id="{new_branch.id}"' in response.text


def test_forked_historical_choice_can_select_a_different_option(tmp_path: Path) -> None:
    db, repo = _setup(tmp_path)
    story, branch = _make_story_with_branch(repo)
    seg, choice = _commit_choice_segment(repo, story, branch)
    repo.save_memory_snapshot(
        MemorySnapshot(story_id=story.id, branch_id=branch.id, segment_id=seg.id)
    )
    _force_status(db, story, StoryStatus.WAITING_CHOICE)
    repo.submit_choice(choice.id, choice.version, option_id=choice.options[0].id)
    client = TestClient(create_app(repository=repo))
    fork = client.post(f"/api/choices/{choice.id}/branch", json={"name": "另一条路"})
    pending = repo.get_current_choice_for_branch(UUID(fork.json()["branch_id"]))
    assert pending is not None

    response = client.post(
        f"/api/choices/{pending.id}/select",
        json={"choice_version": pending.version, "option_id": str(pending.options[1].id)},
    )

    assert response.status_code == 200
    assert response.json()["story_status"] == "IDLE"
    selected = repo.get_current_choice_for_branch(UUID(fork.json()["branch_id"]))
    assert selected is not None
    assert selected.selected_option_id == pending.options[1].id

"""T17 integration coverage for anonymous session isolation."""

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
from storyflow.domain.enums import ChoiceFrequency, StoryStatus
from storyflow.domain.models import Branch, Story, StoryConfig
from storyflow.main import create_app


_CONFIG = StoryConfig(
    genre="奇幻",
    structure="三幕式",
    world_background="云海帝国。",
    protagonist_desc="卡尔。",
    important_supporting_characters=None,
    style="克制",
    choice_frequency=ChoiceFrequency.FEW,
    required_elements=None,
    forbidden_elements=None,
    ending_tendency=None,
)


def _setup(tmp_path: Path) -> tuple[StoryRepository, TestClient]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    repo = StoryRepository(db)
    return repo, TestClient(create_app(repository=repo))


def _create_story(repo: StoryRepository, session_id: str) -> Story:
    story = repo.create_story(
        Story(
            session_id=session_id,
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.FEW,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    return repo.set_current_branch(story.id, branch.id)


# ─── T17 Tests ────────────────────────────────────────────────────────────────


def test_session_a_can_read_its_own_story(tmp_path: Path) -> None:
    """A session can always access stories it created."""
    repo, client = _setup(tmp_path)
    story = _create_story(repo, "session-a")

    response = client.get(
        f"/api/stories/{story.id}",
        headers={"X-Session-ID": "session-a"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(story.id)


def test_session_b_cannot_read_session_a_story(tmp_path: Path) -> None:
    """A different session must receive 404 for another session's story."""
    repo, client = _setup(tmp_path)
    story = _create_story(repo, "session-a")

    response = client.get(
        f"/api/stories/{story.id}",
        headers={"X-Session-ID": "session-b"},
    )

    assert response.status_code == 404


def test_no_session_header_allows_access_for_backward_compatibility(
    tmp_path: Path,
) -> None:
    """Requests without a session header bypass isolation (API / test clients)."""
    repo, client = _setup(tmp_path)
    story = _create_story(repo, "session-a")

    response = client.get(f"/api/stories/{story.id}")

    assert response.status_code == 200


def test_session_b_cannot_generate_on_session_a_story(tmp_path: Path) -> None:
    """Generation endpoint must reject cross-session requests."""
    repo, client = _setup(tmp_path)
    story = _create_story(repo, "session-a")
    branch_id = story.current_branch_id
    assert branch_id is not None

    response = client.post(
        f"/api/stories/{story.id}/generate",
        json={"branch_id": str(branch_id), "generation_key": "k1", "context": {}},
        headers={"X-Session-ID": "session-b"},
    )

    assert response.status_code == 404


def test_session_b_cannot_export_session_a_story(tmp_path: Path) -> None:
    """Export endpoint must reject cross-session requests."""
    repo, client = _setup(tmp_path)
    story = _create_story(repo, "session-a")

    response = client.get(
        f"/api/stories/{story.id}/export.md",
        headers={"X-Session-ID": "session-b"},
    )

    assert response.status_code == 404

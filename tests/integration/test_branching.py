"""T12 integration coverage for branch creation and memory snapshot recovery."""

from __future__ import annotations

import uuid
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
    genre="fantasy",
    structure="three_act",
    world_background="An empire of floating citadels above a frozen sea.",
    protagonist_desc="Kael, a cartographer mapping forgotten routes.",
    important_supporting_characters=None,
    style="lyrical",
    choice_frequency=ChoiceFrequency.FEW,
    required_elements=None,
    forbidden_elements=None,
    ending_tendency=None,
)


def _setup_db(tmp_path: Path) -> tuple[Database, StoryRepository]:
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    return db, StoryRepository(db)


def _make_story_and_branch(repo: StoryRepository) -> tuple[Story, Branch]:
    story = repo.create_story(
        Story(
            session_id="branch-test",
            status=StoryStatus.IDLE,
            choice_frequency=ChoiceFrequency.FEW,
            config=_CONFIG,
        )
    )
    branch = repo.create_branch(Branch(story_id=story.id, name="Main"))
    story = repo.set_current_branch(story.id, branch.id)
    return story, branch


def _commit_segment(
    repo: StoryRepository,
    story: Story,
    branch: Branch,
    seq: int,
    key: str,
    choice: ChoicePoint | None = None,
) -> StorySegment:
    """Commit a segment, return the reloaded persisted copy."""
    parent_id = branch.head_segment_id
    seg = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        parent_segment_id=parent_id,
        sequence=seq,
        content=f"Content of scene {seq}.",
        summary=f"Summary of scene {seq}.",
        generation_key=key,
        status="completed",
    )
    repo.commit_segment_bundle(seg, choice)
    updated = repo.get_branch(branch.id)
    assert updated is not None and updated.head_segment_id is not None
    result = repo.get_segment(updated.head_segment_id)
    assert result is not None
    return result


def _set_story_waiting_choice(db: Database, story: Story) -> Story:
    """Force story status to WAITING_CHOICE without the generation service."""
    updated = story.model_copy(
        update={"status": StoryStatus.WAITING_CHOICE, "version": story.version + 1}
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE stories SET payload = ? WHERE id = ?",
            (updated.model_dump_json(), str(story.id)),
        )
    return updated


def _make_full_fixture(
    tmp_path: Path,
) -> tuple[Database, StoryRepository, Story, Branch, StorySegment, ChoicePoint, TestClient]:
    """
    Create: story → branch B → seg1 (with memory snapshot) → seg2 (with selected choice).

    The pre-choice snapshot for B has active_threads=["Find the lost route"].
    The post-choice snapshot for B adds "left" and "Left path leads to ruins".
    """
    db, repo = _setup_db(tmp_path)
    story, branch = _make_story_and_branch(repo)

    # seg1 – no choice; save an explicit pre-branch memory snapshot
    seg1 = _commit_segment(repo, story, branch, 1, "k-seg1")
    branch = repo.get_branch(branch.id)  # type: ignore[assignment]
    assert branch is not None

    repo.save_memory_snapshot(
        MemorySnapshot(
            story_id=story.id,
            branch_id=branch.id,
            segment_id=seg1.id,
            characters=[
                CharacterState(
                    story_id=story.id,
                    branch_id=branch.id,
                    name="Kael",
                    role="cartographer",
                    location="Ice Bridge",
                    motivation="Find the lost route",
                    known_facts=["Northern citadel is abandoned"],
                    relationships={},
                    alive=True,
                )
            ],
            active_threads=["Find the lost route"],
            foreshadowing={"cracked-map": "The cracked map hides a second path"},
            rolling_summary="Kael crossed the ice bridge.",
            context_version=1,
        )
    )

    # seg2 – has a choice; we'll select option 0
    choice_point = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="The road splits at the ice spire.",
        status="pending",
        options=[
            ChoiceOption(
                text="Take the left road",
                effects={
                    "route_change": "left",
                    "information_state": {"active_threads": ["Left path leads to ruins"]},
                },
                position=0,
            ),
            ChoiceOption(text="Take the right road", effects={"route_change": "right"}, position=1),
            ChoiceOption(text="Rest and observe", effects={"route_change": "rest"}, position=2),
        ],
    )
    seg2 = _commit_segment(repo, story, branch, 2, "k-seg2", choice_point)
    branch = repo.get_branch(branch.id)  # type: ignore[assignment]
    assert branch is not None

    loaded_choice = repo.get_choice_point_for_segment(seg2.id)
    assert loaded_choice is not None

    # Submit the choice (select "left road")
    story = _set_story_waiting_choice(db, story)
    result = repo.submit_choice(
        loaded_choice.id,
        loaded_choice.version,
        option_id=loaded_choice.options[0].id,
    )
    story = result.story

    client = TestClient(create_app(repository=repo, llm_client=None))
    return db, repo, story, branch, seg2, loaded_choice, client


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_create_fork_returns_correct_parent_and_fork_segment(tmp_path: Path) -> None:
    """Fork branch must reference the parent branch and the choice's segment."""
    _, repo, story, branch, seg2, choice, client = _make_full_fixture(tmp_path)

    response = client.post(
        f"/api/choices/{choice.id}/branch",
        json={"name": "Alternate Left"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["story_id"] == str(story.id)
    assert data["fork_segment_id"] == str(seg2.id)

    new_branch = repo.get_branch(data["branch_id"])
    assert new_branch is not None
    assert str(new_branch.parent_branch_id) == str(branch.id)
    assert str(new_branch.fork_segment_id) == str(seg2.id)
    # head must equal fork_segment so the generation chain is rooted at the fork point
    assert str(new_branch.head_segment_id) == str(seg2.id)


def test_original_branch_head_unchanged_after_fork(tmp_path: Path) -> None:
    """Creating a fork must not move the original branch's head pointer."""
    _, repo, story, branch, seg2, choice, client = _make_full_fixture(tmp_path)
    original_head = branch.head_segment_id

    client.post(f"/api/choices/{choice.id}/branch", json={"name": "Fork"})

    branch_after = repo.get_branch(branch.id)
    assert branch_after is not None
    assert branch_after.head_segment_id == original_head


def test_new_branch_restores_pre_choice_memory_snapshot(tmp_path: Path) -> None:
    """Fork branch memory must reflect state BEFORE the choice effects were applied."""
    _, repo, story, branch, seg2, choice, client = _make_full_fixture(tmp_path)

    response = client.post(f"/api/choices/{choice.id}/branch", json={"name": "Fork"})

    assert response.status_code == 200
    data = response.json()
    new_snapshot = repo.get_latest_memory_snapshot(data["branch_id"])
    assert new_snapshot is not None
    # Pre-choice state had only this thread; choice effects added "left" and "Left path leads to ruins"
    assert "Find the lost route" in new_snapshot.active_threads
    assert "left" not in new_snapshot.active_threads
    assert "Left path leads to ruins" not in new_snapshot.active_threads


def test_fork_path_includes_pre_fork_segments_but_not_sibling_post_fork(
    tmp_path: Path,
) -> None:
    """Pre-fork segments are shared via parent links; sibling post-fork segments are excluded."""
    _, repo, story, branch, seg2, choice, client = _make_full_fixture(tmp_path)

    response = client.post(f"/api/choices/{choice.id}/branch", json={"name": "Fork"})
    assert response.status_code == 200
    new_branch_id = uuid.UUID(response.json()["branch_id"])

    # Add a new segment to the ORIGINAL branch (post-fork sibling)
    reloaded_branch = repo.get_branch(branch.id)
    assert reloaded_branch is not None
    seg3_orig = StorySegment(
        story_id=story.id,
        branch_id=branch.id,
        parent_segment_id=reloaded_branch.head_segment_id,
        sequence=3,
        content="Original path continues.",
        summary="Seg3 in original.",
        generation_key="k-orig-seg3",
        status="completed",
    )
    repo.commit_segment_bundle(seg3_orig, None)

    fork_path = repo.list_branch_path(new_branch_id)
    fork_ids = {str(s.id) for s in fork_path}

    # Fork path includes the fork segment and its predecessors
    assert str(seg2.id) in fork_ids
    # But NOT the sibling segment added after the fork
    assert str(seg3_orig.id) not in fork_ids


def test_fork_at_pending_choice_returns_409(tmp_path: Path) -> None:
    """Cannot fork at a choice that has not yet been selected."""
    db, repo = _setup_db(tmp_path)
    story, branch = _make_story_and_branch(repo)

    pending_choice = ChoicePoint(
        type=ChoiceType.DECISION,
        reason="Pending decision.",
        status="pending",
        options=[
            ChoiceOption(text="A", effects={"route_change": "a"}, position=0),
            ChoiceOption(text="B", effects={"route_change": "b"}, position=1),
            ChoiceOption(text="C", effects={"route_change": "c"}, position=2),
        ],
    )
    seg = StorySegment(
        story_id=story.id, branch_id=branch.id,
        sequence=1, content="C1.", summary="S1.", generation_key="k-p", status="completed",
    )
    repo.commit_segment_bundle(seg, pending_choice)
    loaded = repo.get_choice_point_for_segment(seg.id)
    assert loaded is not None

    client = TestClient(create_app(repository=repo, llm_client=None))
    response = client.post(f"/api/choices/{loaded.id}/branch", json={"name": "Fork"})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "choice_not_selected"


def test_fork_at_nonexistent_choice_returns_404(tmp_path: Path) -> None:
    """Fork request for an unknown choice ID must return 404."""
    db, repo = _setup_db(tmp_path)
    client = TestClient(create_app(repository=repo, llm_client=None))

    response = client.post(f"/api/choices/{uuid.uuid4()}/branch", json={"name": "Fork"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "choice_not_found"

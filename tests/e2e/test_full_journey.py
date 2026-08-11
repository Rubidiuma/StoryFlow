"""T21 full-journey test: Create → Bible → scenes → choice → branch → export."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from uuid import UUID

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
from storyflow.domain.models import Branch, Story, StoryConfig
from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app

_SCRIPT_PATH = Path(__file__).parent.parent / "fixtures" / "story_script.json"


def _load_script() -> dict:
    return json.loads(_SCRIPT_PATH.read_text(encoding="utf-8"))


def _parse_sse_events(raw: str) -> list[dict]:
    events = []
    for block in raw.strip().split("\n\n"):
        data_line = next((l for l in block.splitlines() if l.startswith("data:")), None)
        if data_line:
            events.append(json.loads(data_line[5:].strip()))
    return events


def _setup_app(tmp_path: Path, script: dict) -> tuple[StoryRepository, FakeLLMClient, TestClient]:
    """Build app with a deterministic fake LLM loaded from the fixture script."""
    db = Database(tmp_path / "storyflow.sqlite3")
    db.initialize()
    repo = StoryRepository(db)

    # Bible generation: generate_json → plan, generate_json → characters
    # Each scene: generate_json → ScenePlan, stream_text → scene text
    b = script["bible_response"]
    bible_plan = {
        "world_rules": b["world_rules"],
        "tone_rules": b["tone_rules"],
        "protagonist_core": b["protagonist_core"],
        "required_elements": b.get("required_elements", []),
        "forbidden_elements": b.get("forbidden_elements", []),
        "first_arc": b["first_arc"],
        "characters": b["characters"],
    }
    llm = FakeLLMClient(
        json_responses=[
            bible_plan,                       # bible generate
            script["scene1_plan"],            # scene 1 director
            script["scene2_plan"],            # scene 2 director (with choice)
            script["scene3_plan"],            # scene 3 director (post-choice)
        ],
        text_responses=[
            [script["scene1_text"]],
            [script["scene2_text"]],
            [script["scene3_text"]],
        ],
    )
    client = TestClient(create_app(repository=repo, llm_client=llm))
    return repo, llm, client


# ─── Full Journey ─────────────────────────────────────────────────────────────


def test_full_journey_create_bible_scenes_choice_branch_export(
    tmp_path: Path,
) -> None:
    """
    Complete core flow:
      1. Create story draft
      2. Generate + confirm Bible
      3. Auto-generate 2 scenes; scene 2 ends with a choice
      4. Submit preset choice → story returns to IDLE
      5. Generate scene 3 (post-choice direction)
      6. Create fork branch from the original choice
      7. Export current branch → excludes fork segment
    """
    script = _load_script()
    repo, llm, client = _setup_app(tmp_path, script)

    # ── 1. Create story ────────────────────────────────────────────────────
    create_resp = client.post("/stories", json={
        "session_id": "demo-session",
        "title": "云海尽头",
        "config": {
            "genre": "奇幻", "structure": "三幕式",
            "world_background": "浮岛漂浮在永恒的云海上方。",
            "protagonist_desc": "弥拉，年轻的制图师。",
            "important_supporting_characters": "向导洛恩",
            "style": "克制而明亮",
            "choice_frequency": "多",
            "required_elements": "飞艇",
            "forbidden_elements": None,
            "ending_tendency": "保留希望",
        },
    })
    assert create_resp.status_code == 201
    story_id = UUID(create_resp.json()["id"])
    assert create_resp.json()["status"] == "DRAFT"

    # ── 2. Generate Bible ──────────────────────────────────────────────────
    bible_resp = client.post(f"/stories/{story_id}/bible/generate")
    assert bible_resp.status_code == 200
    assert "world_rules" in bible_resp.json()["bible"]

    # ── 3a. Confirm Bible → story becomes IDLE ──────────────────────────
    confirm_resp = client.post(f"/stories/{story_id}/bible/confirm")
    assert confirm_resp.status_code == 200
    story = confirm_resp.json()
    assert story["status"] == "IDLE"
    branch_id = UUID(story["current_branch_id"])

    # ── 3b. Generate scene 1 (no choice) ──────────────────────────────────
    with client.stream("POST", f"/api/stories/{story_id}/generate", json={
        "branch_id": str(branch_id),
        "generation_key": "scene-1",
        "context": {"story": "brief"},
    }) as resp:
        events1 = _parse_sse_events(resp.read().decode())
    terminal1 = events1[-1]["event"]
    assert terminal1 == "continue"

    # Story is IDLE after scene 1
    story_after_1 = repo.get_story(story_id)
    assert story_after_1 is not None
    assert story_after_1.status is StoryStatus.IDLE

    # ── 3c. Generate scene 2 (ends with choice) ────────────────────────────
    with client.stream("POST", f"/api/stories/{story_id}/generate", json={
        "branch_id": str(branch_id),
        "generation_key": "scene-2",
        "context": {"story": "brief"},
    }) as resp:
        events2 = _parse_sse_events(resp.read().decode())
    terminal2 = events2[-1]["event"]
    assert terminal2 == "choice"
    choice_data = events2[-1]["data"]
    choice_id = UUID(choice_data["choice_point_id"])
    assert len(choice_data["options"]) == 3

    # ── 4. Submit preset choice (option 0 = negotiate) ─────────────────────
    option_id = UUID(choice_data["options"][0]["id"])
    story_waiting = repo.get_story(story_id)
    assert story_waiting is not None
    assert story_waiting.status is StoryStatus.WAITING_CHOICE

    choice_resp = client.post(f"/api/choices/{choice_id}/select", json={
        "choice_version": 1,
        "option_id": str(option_id),
    })
    assert choice_resp.status_code == 200
    assert choice_resp.json()["story_status"] == "IDLE"

    # ── 5. Generate scene 3 (new direction after choice) ───────────────────
    with client.stream("POST", f"/api/stories/{story_id}/generate", json={
        "branch_id": str(branch_id),
        "generation_key": "scene-3",
        "context": {"story": "brief"},
    }) as resp:
        events3 = _parse_sse_events(resp.read().decode())
    assert events3[-1]["event"] == "continue"

    # ── 6. Fork branch from the original choice ────────────────────────────
    fork_resp = client.post(f"/api/choices/{choice_id}/branch", json={"name": "备用路线"})
    assert fork_resp.status_code == 200
    fork_data = fork_resp.json()
    fork_branch_id = UUID(fork_data["branch_id"])
    assert fork_data["fork_segment_id"] == str(events2[-2]["data"]["segment_id"])

    # Original branch path has 3 segments
    original_path = repo.list_branch_path(branch_id)
    assert len(original_path) == 3

    # Fork branch shares up to scene-2; head = fork segment (scene-2)
    fork_branch = repo.get_branch(fork_branch_id)
    assert fork_branch is not None
    assert fork_branch.parent_branch_id == branch_id

    # ── 7. Export current branch ───────────────────────────────────────────
    export_resp = client.get(f"/api/stories/{story_id}/export.md")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("text/markdown")
    text = export_resp.text
    assert "云海尽头" in text
    assert script["scene1_text"][:20] in text
    assert script["scene2_text"][:20] in text
    assert script["scene3_text"][:20] in text
    # Selected choice text appears; its effects key does not
    assert "用制图师身份正面交涉" in text
    assert "negotiate" not in text

    # ── 8. Cross-session isolation ─────────────────────────────────────────
    isolation_resp = client.get(
        f"/api/stories/{story_id}",
        headers={"X-Session-ID": "intruder-session"},
    )
    assert isolation_resp.status_code == 404

    # ── 9. Idempotent replay: same generation key returns same segment ──────
    with client.stream("POST", f"/api/stories/{story_id}/generate", json={
        "branch_id": str(branch_id),
        "generation_key": "scene-1",  # already committed
        "context": {"story": "brief"},
    }) as resp:
        replay_events = _parse_sse_events(resp.read().decode())
    committed_ids = [e["data"]["segment_id"] for e in replay_events if e["event"] == "committed"]
    original_id = str(original_path[0].id)
    assert committed_ids and committed_ids[0] == original_id


def test_full_journey_runs_three_times_identically(tmp_path: Path) -> None:
    """Three independent runs with the same script must produce identical stories."""
    script = _load_script()
    segment_contents: list[list[str]] = []

    for run in range(3):
        run_path = tmp_path / f"run-{run}"
        run_path.mkdir()
        repo, _, client = _setup_app(run_path, script)

        create_resp = client.post("/stories", json={
            "session_id": f"determinism-{run}",
            "title": "一致性测试",
            "config": {
                "genre": "奇幻", "structure": "三幕式",
                "world_background": "浮岛漂浮在永恒的云海上方。",
                "protagonist_desc": "弥拉，制图师。",
                "important_supporting_characters": None,
                "style": "克制", "choice_frequency": "多",
                "required_elements": None, "forbidden_elements": None,
                "ending_tendency": None,
            },
        })
        story_id = UUID(create_resp.json()["id"])
        client.post(f"/stories/{story_id}/bible/generate")
        confirm = client.post(f"/stories/{story_id}/bible/confirm")
        branch_id = UUID(confirm.json()["current_branch_id"])

        with client.stream("POST", f"/api/stories/{story_id}/generate", json={
            "branch_id": str(branch_id), "generation_key": "s1", "context": {},
        }) as resp:
            resp.read()

        path = repo.list_branch_path(branch_id)
        segment_contents.append([s.content for s in path])

    assert segment_contents[0] == segment_contents[1] == segment_contents[2]

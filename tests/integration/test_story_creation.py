"""Integration tests for draft creation and the generated Bible lifecycle."""

import asyncio
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import StoryStatus
from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app


def valid_story_request() -> dict[str, Any]:
    """Return a complete request payload with stable literal values."""
    return {
        "session_id": "session-123",
        "title": "The Lantern Road",
        "config": {
            "genre": "奇幻",
            "structure": "三幕式",
            "world_background": "群岛漂浮在终年不散的云海上。",
            "protagonist_desc": "失去导师的年轻制图师。",
            "important_supporting_characters": None,
            "style": "克制而明亮",
            "choice_frequency": "中",
            "required_elements": None,
            "forbidden_elements": None,
            "ending_tendency": None,
        },
    }


def valid_bible_generation() -> dict[str, Any]:
    """Return a structurally complete provider response with stable literal values."""
    return {
        "world_rules": "每次使用云海魔法都会遗失一段记忆。",
        "tone_rules": "保持亲密、克制与希望。",
        "protagonist_core": "弥拉绝不抛弃同伴。",
        "required_elements": ["飞艇", "失落地图"],
        "forbidden_elements": ["时间旅行"],
        "characters": [
            {
                "name": "弥拉",
                "role": "protagonist",
                "location": "浮岛港",
                "motivation": "找到失踪的导师",
                "known_facts": ["地图会发光"],
                "secrets": [],
                "relationships": {"洛恩": "不信任的向导"},
                "alive": True,
                "version": 1,
            },
            {"name": "洛恩", "role": "ally"},
        ],
        "first_arc": {
            "goal": "穿过封锁的云海",
            "conflict": "港务官扣押了唯一的飞艇",
            "stage": "rising",
            "exit_conditions": ["取得飞艇"],
            "status": "active",
            "summary": "",
        },
    }


def make_repository(tmp_path: Path) -> tuple[Database, StoryRepository]:
    """Create the real initialized SQLite repository used by API tests."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    return database, StoryRepository(database)


class BlockingSecondFakeLLMClient(FakeLLMClient):
    """Pause the second structured call so a concurrent confirmation can commit first."""

    def __init__(self, *, json_responses: list[object]) -> None:
        super().__init__(json_responses=json_responses)
        self.second_call_started = asyncio.Event()
        self.release_second_call = asyncio.Event()

    async def generate_json(
        self, *, prompt: str, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        if len(self.calls) == 1:
            self.second_call_started.set()
            await self.release_second_call.wait()
        return await super().generate_json(prompt=prompt, context=context)


@pytest.mark.asyncio
async def test_create_story_draft_persists_canonical_config(tmp_path: Path) -> None:
    """POST /stories persists a DRAFT and derives the compatibility frequency."""
    _, repository = make_repository(tmp_path)
    transport = httpx.ASGITransport(app=create_app(repository=repository))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/stories", json=valid_story_request())

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == "session-123"
    assert body["title"] == "The Lantern Road"
    assert body["status"] == "DRAFT"
    assert body["choice_frequency"] == "中"
    assert body["config"] == valid_story_request()["config"]
    assert body["current_branch_id"] is None
    assert body["version"] == 1
    persisted = repository.get_story(body["id"])
    assert persisted is not None
    assert persisted.model_dump(mode="json") == body


@pytest.mark.asyncio
async def test_invalid_required_or_oversized_config_creates_no_story(tmp_path: Path) -> None:
    """Missing, visibly blank, and cumulatively oversized input is rejected before persistence."""
    database, repository = make_repository(tmp_path)
    transport = httpx.ASGITransport(app=create_app(repository=repository))
    invalid_requests: list[dict[str, object]] = []

    missing = valid_story_request()
    del missing["config"]["genre"]
    invalid_requests.append(missing)

    for field in ("genre", "structure", "world_background", "protagonist_desc", "style"):
        blank = valid_story_request()
        blank["config"][field] = "   "
        invalid_requests.append(blank)

    oversized = valid_story_request()
    oversized["config"].update(
        {
            "world_background": "w" * 2000,
            "protagonist_desc": "p" * 2000,
            "important_supporting_characters": "c" * 1000,
            "style": "s" * 500,
            "required_elements": "r" * 496,
        }
    )
    invalid_requests.append(oversized)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await client.post("/stories", json=payload) for payload in invalid_requests]

    assert [response.status_code for response in responses] == [422] * 7
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_two_invalid_bible_responses_return_502_and_preserve_only_draft(
    tmp_path: Path,
) -> None:
    """Exhausted structural retries leave the draft available for a later retry."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[
            '{"world_rules": ',
            {
                "world_rules": "   ",
                "tone_rules": "克制",
                "protagonist_core": "不放弃同伴",
                "required_elements": [],
                "forbidden_elements": [],
                "characters": [],
                "first_arc": {"goal": "找到导师", "conflict": "云海封锁"},
            },
        ]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        response = await client.post(f"/stories/{story_id}/bible/generate")

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "BIBLE_GENERATION_INVALID_RESPONSE",
            "message": "Generated Bible could not be validated.",
            "retryable": True,
        }
    }
    assert len(llm_client.calls) == 2
    expected_context = {
        "genre": "奇幻",
        "structure": "三幕式",
        "world_background": "群岛漂浮在终年不散的云海上。",
        "protagonist_desc": "失去导师的年轻制图师。",
        "important_supporting_characters": None,
        "style": "克制而明亮",
        "choice_frequency": "中",
        "required_elements": None,
        "forbidden_elements": None,
        "ending_tendency": None,
    }
    assert [call["context"] for call in llm_client.calls] == [
        expected_context,
        expected_context,
    ]
    assert all("story_bible_v1" in str(call["prompt"]) for call in llm_client.calls)
    persisted = repository.get_story(story_id)
    assert persisted is not None
    assert persisted.status.value == "DRAFT"
    assert persisted.current_branch_id is None
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_bibles").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 0


@pytest.mark.parametrize("error_type", [TypeError, ValueError], ids=["type", "value"])
@pytest.mark.asyncio
async def test_non_structured_llm_errors_are_not_retried(
    tmp_path: Path,
    error_type: type[Exception],
) -> None:
    """Client implementation failures are not model-output validation failures."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(
        json_responses=[
            error_type("client implementation failure"),
            valid_bible_generation(),
        ]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        with pytest.raises(error_type, match="client implementation failure"):
            await client.post(f"/stories/{story_id}/bible/generate")

    assert len(llm_client.calls) == 1
    story = repository.get_story(story_id)
    assert story is not None
    assert story.status.value == "DRAFT"
    assert story.current_branch_id is None
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 0,
        "branches": 0,
        "character_states": 0,
        "story_arcs": 0,
    }


@pytest.mark.asyncio
async def test_invalid_then_valid_generation_persists_one_complete_related_bundle(
    tmp_path: Path,
) -> None:
    """The second valid result atomically binds every generated record to one root branch."""
    database, repository = make_repository(tmp_path)
    valid_generation = valid_bible_generation()
    llm_client = FakeLLMClient(
        json_responses=[
            {**valid_generation, "characters": []},
            valid_generation,
        ]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        response = await client.post(f"/stories/{story_id}/bible/generate")

    assert response.status_code == 200
    assert len(llm_client.calls) == 2
    body = response.json()
    branch_id = body["initial_branch_id"]
    assert body["bible"] == {
        "story_id": story_id,
        "world_rules": "每次使用云海魔法都会遗失一段记忆。",
        "tone_rules": "保持亲密、克制与希望。",
        "protagonist_core": "弥拉绝不抛弃同伴。",
        "required_elements": ["飞艇", "失落地图"],
        "forbidden_elements": ["时间旅行"],
        "version": 1,
    }
    assert [(item["name"], item["role"]) for item in body["characters"]] == [
        ("弥拉", "protagonist"),
        ("洛恩", "ally"),
    ]
    assert all(item["story_id"] == story_id for item in body["characters"])
    assert all(item["branch_id"] == branch_id for item in body["characters"])
    assert body["first_arc"]["story_id"] == story_id
    assert body["first_arc"]["branch_id"] == branch_id
    assert body["first_arc"]["goal"] == "穿过封锁的云海"
    persisted_bible = repository.get_bible(story_id)
    assert persisted_bible is not None
    assert persisted_bible.model_dump(mode="json") == body["bible"]
    assert [
        character.model_dump(mode="json")
        for character in repository.list_character_states(story_id)
    ] == body["characters"]
    assert [arc.model_dump(mode="json") for arc in repository.list_story_arcs(story_id)] == [
        body["first_arc"]
    ]
    branch = repository.get_branch(branch_id)
    assert branch is not None
    assert branch.name == "Main"
    assert str(branch.story_id) == story_id
    story = repository.get_story(story_id)
    assert story is not None
    assert str(story.current_branch_id) == branch_id
    assert story.status.value == "DRAFT"
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 1,
        "branches": 1,
        "character_states": 2,
        "story_arcs": 1,
    }


@pytest.mark.asyncio
async def test_persistence_failure_rolls_back_every_generated_record(tmp_path: Path) -> None:
    """A late SQLite failure cannot expose a partial Bible aggregate."""
    database, repository = make_repository(tmp_path)
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER force_story_arc_failure
            BEFORE INSERT ON story_arcs
            BEGIN
                SELECT RAISE(ABORT, 'forced story arc persistence failure');
            END
            """
        )
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        with pytest.raises(sqlite3.IntegrityError, match="forced story arc"):
            await client.post(f"/stories/{story_id}/bible/generate")

    story = repository.get_story(story_id)
    assert story is not None
    assert story.status.value == "DRAFT"
    assert story.current_branch_id is None
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 0,
        "branches": 0,
        "character_states": 0,
        "story_arcs": 0,
    }


@pytest.mark.asyncio
async def test_regeneration_replaces_initial_bundle_without_duplicate_rows(
    tmp_path: Path,
) -> None:
    """A second pre-confirmation generation removes every record from the first bundle."""
    database, repository = make_repository(tmp_path)
    replacement = valid_bible_generation()
    replacement.update(
        {
            "world_rules": "星光魔法只能在云海之上使用。",
            "characters": [{"name": "索拉", "role": "protagonist"}],
            "first_arc": {
                "goal": "修复坠毁的飞艇",
                "conflict": "风暴正在逼近残骸",
            },
        }
    )
    llm_client = FakeLLMClient(
        json_responses=[valid_bible_generation(), replacement]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        first_response = await client.post(f"/stories/{story_id}/bible/generate")
        first_body = first_response.json()
        response = await client.post(f"/stories/{story_id}/bible/generate")

    assert response.status_code == 200
    body = response.json()
    assert body["initial_branch_id"] != first_body["initial_branch_id"]
    assert body["bible"]["world_rules"] == "星光魔法只能在云海之上使用。"
    assert [(item["name"], item["role"]) for item in body["characters"]] == [
        ("索拉", "protagonist")
    ]
    assert body["first_arc"]["goal"] == "修复坠毁的飞艇"
    assert repository.get_branch(first_body["initial_branch_id"]) is None
    story = repository.get_story(story_id)
    assert story is not None
    assert str(story.current_branch_id) == body["initial_branch_id"]
    assert story.status.value == "DRAFT"
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 1,
        "branches": 1,
        "character_states": 1,
        "story_arcs": 1,
    }


@pytest.mark.asyncio
async def test_generation_rejects_confirmed_story_before_calling_llm(tmp_path: Path) -> None:
    """A confirmed Bible cannot be regenerated or consume another model response."""
    database, repository = make_repository(tmp_path)
    replacement = valid_bible_generation()
    replacement["world_rules"] = "This confirmed foundation must not be persisted."
    llm_client = FakeLLMClient(
        json_responses=[valid_bible_generation(), replacement]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        generation_response = await client.post(f"/stories/{story_id}/bible/generate")
        initial_bundle = generation_response.json()
        confirmation_response = await client.post(f"/stories/{story_id}/bible/confirm")
        response = await client.post(f"/stories/{story_id}/bible/generate")

    assert confirmation_response.status_code == 200
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_GENERATION_CONFLICT",
            "message": "Story cannot generate a Bible from its current state or version.",
        }
    }
    assert len(llm_client.calls) == 1
    story = repository.get_story(story_id)
    assert story is not None
    assert story.status.value == "IDLE"
    assert str(story.current_branch_id) == initial_bundle["initial_branch_id"]
    bible = repository.get_bible(story_id)
    assert bible is not None
    assert bible.world_rules == "每次使用云海魔法都会遗失一段记忆。"
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 1,
        "branches": 1,
        "character_states": 2,
        "story_arcs": 1,
    }


@pytest.mark.asyncio
async def test_generation_cannot_commit_after_concurrent_confirmation(tmp_path: Path) -> None:
    """A stale in-flight generation cannot replace the bundle that was just confirmed."""
    database, repository = make_repository(tmp_path)
    replacement = valid_bible_generation()
    replacement.update(
        {
            "world_rules": "This stale replacement must be discarded.",
            "characters": [{"name": "迟到者", "role": "protagonist"}],
        }
    )
    llm_client = BlockingSecondFakeLLMClient(
        json_responses=[valid_bible_generation(), replacement]
    )
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        initial_response = await client.post(f"/stories/{story_id}/bible/generate")
        initial_bundle = initial_response.json()
        generation_task = asyncio.create_task(
            client.post(f"/stories/{story_id}/bible/generate")
        )
        await asyncio.wait_for(llm_client.second_call_started.wait(), timeout=1)
        confirmation_response = await client.post(f"/stories/{story_id}/bible/confirm")
        llm_client.release_second_call.set()
        response = await generation_task

    assert confirmation_response.status_code == 200
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_GENERATION_CONFLICT",
            "message": "Story cannot generate a Bible from its current state or version.",
        }
    }
    assert len(llm_client.calls) == 2
    story = repository.get_story(story_id)
    assert story is not None
    assert story.status.value == "IDLE"
    assert story.version == 2
    assert str(story.current_branch_id) == initial_bundle["initial_branch_id"]
    bible = repository.get_bible(story_id)
    assert bible is not None
    assert bible.model_dump(mode="json") == initial_bundle["bible"]
    assert [
        character.model_dump(mode="json")
        for character in repository.list_character_states(story_id)
    ] == initial_bundle["characters"]
    assert [arc.model_dump(mode="json") for arc in repository.list_story_arcs(story_id)] == [
        initial_bundle["first_arc"]
    ]
    assert repository.get_branch(initial_bundle["initial_branch_id"]) is not None
    with database.read() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts == {
        "story_bibles": 1,
        "branches": 1,
        "character_states": 2,
        "story_arcs": 1,
    }


@pytest.mark.parametrize(
    "missing_component",
    ["whole_bundle", "story_bibles", "character_states", "story_arcs", "current_branch"],
)
@pytest.mark.asyncio
async def test_confirmation_rejects_each_incomplete_bundle_without_story_mutation(
    tmp_path: Path,
    missing_component: str,
) -> None:
    """Every required persisted component gates the DRAFT-to-IDLE transition."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        if missing_component != "whole_bundle":
            generation_response = await client.post(f"/stories/{story_id}/bible/generate")
            assert generation_response.status_code == 200
            with database.transaction() as connection:
                if missing_component == "current_branch":
                    story = repository.get_story(story_id)
                    assert story is not None
                    unbound = story.model_copy(update={"current_branch_id": None})
                    connection.execute(
                        "UPDATE stories SET current_branch_id = NULL, payload = ? WHERE id = ?",
                        (unbound.model_dump_json(), story_id),
                    )
                else:
                    connection.execute(
                        f"DELETE FROM {missing_component} WHERE story_id = ?",
                        (story_id,),
                    )
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_BUNDLE_INCOMPLETE",
            "message": "A complete generated Bible bundle is required.",
        }
    }
    persisted = repository.get_story(story_id)
    assert persisted is not None
    assert persisted.status.value == "DRAFT"
    assert persisted.version == 1


@pytest.mark.asyncio
async def test_confirmation_rejects_relational_payload_branch_mismatch(tmp_path: Path) -> None:
    """Confirmation cannot trust a relational branch pointer absent from the Story payload."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        generation_response = await client.post(f"/stories/{story_id}/bible/generate")
        branch_id = generation_response.json()["initial_branch_id"]
        story = repository.get_story(story_id)
        assert story is not None
        mismatched_story = story.model_copy(update={"current_branch_id": None})
        with database.transaction() as connection:
            connection.execute(
                "UPDATE stories SET payload = ? WHERE id = ?",
                (mismatched_story.model_dump_json(), story_id),
            )
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_BUNDLE_INCOMPLETE",
            "message": "A complete generated Bible bundle is required.",
        }
    }
    assert repository.get_story(story_id) == mismatched_story
    with database.read() as connection:
        relational_branch_id = connection.execute(
            "SELECT current_branch_id FROM stories WHERE id = ?", (story_id,)
        ).fetchone()[0]
    assert relational_branch_id == branch_id


@pytest.mark.asyncio
async def test_confirm_complete_bible_transitions_draft_to_idle(tmp_path: Path) -> None:
    """A complete bundle is atomically confirmed with the domain transition and one version bump."""
    _, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        generation_response = await client.post(f"/stories/{story_id}/bible/generate")
        branch_id = generation_response.json()["initial_branch_id"]
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == story_id
    assert body["status"] == "IDLE"
    assert body["version"] == 2
    assert body["current_branch_id"] == branch_id
    persisted = repository.get_story(story_id)
    assert persisted is not None
    assert persisted.model_dump(mode="json") == body


@pytest.mark.asyncio
async def test_repeated_confirmation_returns_unchanged_story_without_new_records(
    tmp_path: Path,
) -> None:
    """Confirming an already-IDLE story is an exact idempotent read."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        await client.post(f"/stories/{story_id}/bible/generate")
        first_response = await client.post(f"/stories/{story_id}/bible/confirm")
        with database.read() as connection:
            counts_before = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("story_bibles", "branches", "character_states", "story_arcs")
            }
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert response.status_code == 200
    assert response.json() == first_response.json()
    assert response.json()["version"] == 2
    with database.read() as connection:
        counts_after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("story_bibles", "branches", "character_states", "story_arcs")
        }
    assert counts_after == counts_before


@pytest.mark.asyncio
async def test_repeated_confirmation_rejects_incomplete_idle_bundle(tmp_path: Path) -> None:
    """IDLE idempotency applies only while the complete confirmed bundle still exists."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        await client.post(f"/stories/{story_id}/bible/generate")
        confirmation_response = await client.post(f"/stories/{story_id}/bible/confirm")
        confirmed_story = repository.get_story(story_id)
        assert confirmed_story is not None
        with database.transaction() as connection:
            connection.execute("DELETE FROM story_arcs WHERE story_id = ?", (story_id,))
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert confirmation_response.status_code == 200
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_BUNDLE_INCOMPLETE",
            "message": "A complete generated Bible bundle is required.",
        }
    }
    assert repository.get_story(story_id) == confirmed_story


@pytest.mark.asyncio
async def test_confirmation_rejects_other_source_state_without_mutation(tmp_path: Path) -> None:
    """Only DRAFT and already-IDLE stories may pass through confirmation."""
    database, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft_response = await client.post("/stories", json=valid_story_request())
        story_id = draft_response.json()["id"]
        await client.post(f"/stories/{story_id}/bible/generate")
        story = repository.get_story(story_id)
        assert story is not None
        paused = story.model_copy(update={"status": StoryStatus.PAUSED, "version": 7})
        with database.transaction() as connection:
            connection.execute(
                "UPDATE stories SET payload = ? WHERE id = ?",
                (paused.model_dump_json(), story_id),
            )
        response = await client.post(f"/stories/{story_id}/bible/confirm")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "BIBLE_CONFIRMATION_CONFLICT",
            "message": "Story cannot be confirmed from its current state.",
        }
    }
    assert repository.get_story(story_id) == paused


@pytest.mark.asyncio
async def test_missing_story_returns_404_without_calling_llm(tmp_path: Path) -> None:
    """Both Bible operations distinguish an absent Story from service unavailability."""
    _, repository = make_repository(tmp_path)
    llm_client = FakeLLMClient(json_responses=[valid_bible_generation()])
    missing_id = uuid4()
    transport = httpx.ASGITransport(
        app=create_app(repository=repository, llm_client=llm_client)
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generate_response = await client.post(f"/stories/{missing_id}/bible/generate")
        confirm_response = await client.post(f"/stories/{missing_id}/bible/confirm")

    assert generate_response.status_code == 404
    assert confirm_response.status_code == 404
    assert llm_client.calls == []


@pytest.mark.asyncio
async def test_unconfigured_app_story_routes_return_503() -> None:
    """The default app never invents persistence or an external model dependency."""
    missing_id = uuid4()
    transport = httpx.ASGITransport(app=create_app())

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/stories", json=valid_story_request())
        generate_response = await client.post(f"/stories/{missing_id}/bible/generate")
        confirm_response = await client.post(f"/stories/{missing_id}/bible/confirm")

    assert [
        create_response.status_code,
        generate_response.status_code,
        confirm_response.status_code,
    ] == [503, 503, 503]

"""Page-level integration tests for the creation wizard and bookshelf."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from storyflow.db.database import Database
from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import ChoiceFrequency, StoryStatus
from storyflow.domain.models import Story, StoryBible, StoryConfig
from storyflow.main import create_app


class FormFieldParser(HTMLParser):
    """Collect named form controls and their browser validation attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, dict[str, str | None]] = {}
        self.forms: list[dict[str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.forms.append(attributes)
        if tag in {"input", "select", "textarea"} and "name" in attributes:
            name = attributes["name"]
            assert name is not None
            self.fields[name] = attributes


def make_repository(tmp_path: Path) -> StoryRepository:
    """Create the initialized repository used by real page requests."""
    database = Database(tmp_path / "storyflow.sqlite3")
    database.initialize()
    return StoryRepository(database)


def story_config() -> StoryConfig:
    """Return a complete, literal creation configuration."""
    return StoryConfig(
        genre="奇幻",
        structure="三幕式",
        world_background="群岛漂浮在终年不散的云海上。",
        protagonist_desc="失去导师的年轻制图师。",
        important_supporting_characters="寡言的云海向导洛恩。",
        style="克制而明亮",
        choice_frequency=ChoiceFrequency.MEDIUM,
        required_elements="飞艇、失落地图",
        forbidden_elements="时间旅行",
        ending_tendency="保留希望",
    )


def persist_story(
    repository: StoryRepository,
    *,
    title: str,
    status: StoryStatus = StoryStatus.DRAFT,
) -> Story:
    """Persist a story in the requested visible lifecycle state."""
    config = story_config()
    return repository.create_story(
        Story(
            session_id="browser-session",
            title=title,
            status=status,
            choice_frequency=config.choice_frequency,
            config=config,
            pause_requested=False,
            version=1,
        )
    )


def test_bookshelf_and_create_pages_are_html_documents(tmp_path: Path) -> None:
    """Removing either page route must break a browser-visible 200 response."""
    repository = make_repository(tmp_path)

    with TestClient(create_app(repository=repository)) as client:
        bookshelf = client.get("/")
        create = client.get("/create")

    assert bookshelf.status_code == 200
    assert create.status_code == 200
    assert bookshelf.headers["content-type"].startswith("text/html")
    assert create.headers["content-type"].startswith("text/html")
    assert "StoryFlow" in bookshelf.text
    assert "创建小说" in create.text


def test_create_form_matches_api_fields_and_length_constraints(tmp_path: Path) -> None:
    """Dropping an API field or weakening a browser limit must fail the page contract."""
    repository = make_repository(tmp_path)

    with TestClient(create_app(repository=repository)) as client:
        response = client.get("/create")

    parser = FormFieldParser()
    parser.feed(response.text)
    assert set(parser.fields) == {
        "session_id",
        "title",
        "genre",
        "structure",
        "world_background",
        "protagonist_desc",
        "important_supporting_characters",
        "style",
        "choice_frequency",
        "required_elements",
        "forbidden_elements",
        "ending_tendency",
    }
    for name in (
        "session_id",
        "genre",
        "structure",
        "world_background",
        "protagonist_desc",
        "style",
        "choice_frequency",
    ):
        assert "required" in parser.fields[name]
    assert {
        name: parser.fields[name].get("maxlength")
        for name in (
            "world_background",
            "protagonist_desc",
            "important_supporting_characters",
            "style",
            "required_elements",
            "forbidden_elements",
            "ending_tendency",
        )
    } == {
        "world_background": "2000",
        "protagonist_desc": "2000",
        "important_supporting_characters": "1000",
        "style": "500",
        "required_elements": "1000",
        "forbidden_elements": "1000",
        "ending_tendency": "1000",
    }
    assert parser.forms[0]["data-total-maxlength"] == "6000"


def test_bookshelf_lists_stories_with_recent_status_and_resume_links(tmp_path: Path) -> None:
    """Removing persisted stories or their lifecycle state must break bookshelf recovery."""
    repository = make_repository(tmp_path)
    draft = persist_story(repository, title="云海地图")
    confirmed = persist_story(
        repository,
        title="灯塔之外",
        status=StoryStatus.IDLE,
    )

    with TestClient(create_app(repository=repository)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "云海地图" in response.text
    assert "灯塔之外" in response.text
    assert f'href="/stories/{draft.id}"' in response.text
    assert f'href="/stories/{confirmed.id}"' in response.text
    assert 'data-status="DRAFT"' in response.text
    assert 'data-status="IDLE"' in response.text
    assert "最近更新" in response.text


def test_missing_story_page_returns_stable_html_404(tmp_path: Path) -> None:
    """Falling through to an API-shaped response must break the browser 404 contract."""
    repository = make_repository(tmp_path)
    missing_id = uuid4()

    with TestClient(create_app(repository=repository)) as client:
        response = client.get(f"/stories/{missing_id}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "故事不存在" in response.text
    assert 'href="/"' in response.text


def test_draft_story_with_bible_shows_preview_and_confirmation_not_reader(
    tmp_path: Path,
) -> None:
    """Routing an unconfirmed Bible into the reader must fail this lifecycle guard."""
    repository = make_repository(tmp_path)
    draft = persist_story(repository, title="云海地图")
    repository.save_bible(
        StoryBible(
            story_id=draft.id,
            world_rules="云海魔法会交换一段记忆。",
            tone_rules="亲密、克制，并保留希望。",
            protagonist_core="弥拉绝不抛弃同伴。",
            required_elements=["飞艇", "失落地图"],
            forbidden_elements=["时间旅行"],
            version=1,
        )
    )

    with TestClient(create_app(repository=repository)) as client:
        response = client.get(f"/stories/{draft.id}")

    assert response.status_code == 200
    assert 'data-view="bible-confirmation"' in response.text
    assert "云海魔法会交换一段记忆。" in response.text
    assert "确认故事圣经" in response.text
    assert "修改创作设定" in response.text
    assert 'data-view="reader-entry"' not in response.text


def test_confirmed_story_shows_reader_entry_and_recent_status(tmp_path: Path) -> None:
    """Treating a confirmed story as a draft must hide its intended resume action."""
    repository = make_repository(tmp_path)
    confirmed = persist_story(
        repository,
        title="灯塔之外",
        status=StoryStatus.IDLE,
    )

    with TestClient(create_app(repository=repository)) as client:
        response = client.get(f"/stories/{confirmed.id}")

    assert response.status_code == 200
    assert 'data-view="reader-entry"' in response.text
    assert "继续阅读" in response.text
    assert "IDLE" in response.text
    assert 'data-view="bible-confirmation"' not in response.text


def test_page_static_assets_are_served_by_the_application(tmp_path: Path) -> None:
    """A missing static mount must fail before the browser receives styling or behavior."""
    repository = make_repository(tmp_path)

    with TestClient(create_app(repository=repository)) as client:
        responses = {
            path: client.get(path)
            for path in (
                "/static/css/app.css",
                "/static/js/api.js",
                "/static/js/create.js",
            )
        }

    assert {path: response.status_code for path, response in responses.items()} == {
        "/static/css/app.css": 200,
        "/static/js/api.js": 200,
        "/static/js/create.js": 200,
    }
    assert responses["/static/css/app.css"].headers["content-type"].startswith("text/css")
    assert all(
        responses[path].headers["content-type"].startswith("text/javascript")
        for path in ("/static/js/api.js", "/static/js/create.js")
    )

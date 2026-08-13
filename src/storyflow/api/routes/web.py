from __future__ import annotations

"""Server-rendered entry pages for the StoryFlow browser experience."""

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from storyflow.db.repositories import StoryRepository
from storyflow.domain.enums import StoryStatus
from storyflow.services.reader_view import build_history_choices, build_visible_summary

_log = logging.getLogger(__name__)

PACKAGE_DIRECTORY = Path(__file__).resolve().parents[2]
WEB_STATIC_DIRECTORY = PACKAGE_DIRECTORY / "static"
templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")

STATUS_LABELS = {
    StoryStatus.DRAFT: "待确认设定",
    StoryStatus.IDLE: "可继续",
    StoryStatus.PLANNING: "规划中",
    StoryStatus.STREAMING: "生成中",
    StoryStatus.COMMITTING: "保存中",
    StoryStatus.WAITING_CHOICE: "等待选择",
    StoryStatus.PAUSED: "已暂停",
    StoryStatus.ERROR: "需要重试",
}


def create_web_router(repository: StoryRepository | None) -> APIRouter:
    """Build HTML routes while keeping JSON API routes unchanged."""
    router = APIRouter(tags=["web"])

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    def bookshelf(request: Request) -> HTMLResponse:
        stories = repository.list_stories() if repository is not None else []
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"stories": stories, "status_labels": STATUS_LABELS},
        )

    @router.get("/create", response_class=HTMLResponse, include_in_schema=False)
    def create_page(request: Request, copy_from: UUID | None = None) -> HTMLResponse:
        source_story = repository.get_story(copy_from) if repository and copy_from else None
        return templates.TemplateResponse(
            request=request,
            name="create.html",
            context={"source_story": source_story},
        )

    @router.get(
        "/stories/{story_id}", response_class=HTMLResponse, include_in_schema=False
    )
    def story_page(request: Request, story_id: UUID) -> HTMLResponse:
        if repository is None:
            _log.warning("story_page: repository is None, returning 503")
            return templates.TemplateResponse(
                request=request,
                name="story.html",
                context={"story": None, "bible": None, "status_labels": STATUS_LABELS},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        story = repository.get_story(story_id)
        if story is None:
            _log.warning("story_page: story %s not found", story_id)
            return templates.TemplateResponse(
                request=request,
                name="story.html",
                context={"story": None, "bible": None, "status_labels": STATUS_LABELS},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        assert repository is not None
        bible = repository.get_bible(story_id) if story.status is StoryStatus.DRAFT else None
        return templates.TemplateResponse(
            request=request,
            name="story.html",
            context={"story": story, "bible": bible, "status_labels": STATUS_LABELS},
        )

    @router.get(
        "/stories/{story_id}/reader", response_class=HTMLResponse, include_in_schema=False
    )
    def reader_page(
        request: Request, story_id: UUID, branch: UUID | None = None
    ) -> HTMLResponse:
        if repository is None:
            _log.warning("reader_page: repository is None, returning 503")
            return templates.TemplateResponse(
                request=request,
                name="reader.html",
                context={"story": None, "branch": None, "segments": [],
                         "current_choice": None, "branches": [],
                         "history_choices": {}, "visible_summary": "",
                         "summary_source": "empty",
                         "status_labels": STATUS_LABELS},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        story = repository.get_story(story_id)
        if story is None:
            _log.warning("reader_page: story %s not found", story_id)
            return templates.TemplateResponse(
                request=request,
                name="reader.html",
                context={"story": None, "branch": None, "segments": [],
                         "current_choice": None, "branches": [],
                         "history_choices": {}, "visible_summary": "",
                         "summary_source": "empty",
                         "status_labels": STATUS_LABELS},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        assert repository is not None
        target_branch_id = branch or story.current_branch_id
        branch_obj = repository.get_branch(target_branch_id) if target_branch_id else None
        segments = repository.list_branch_path(target_branch_id) if target_branch_id else []
        current_choice = None
        if (
            story.status is StoryStatus.WAITING_CHOICE
            and target_branch_id is not None
            and target_branch_id == story.current_branch_id
            and segments
        ):
            current_choice = repository.get_current_choice_for_branch(target_branch_id)
        branches = repository.list_branches(story_id)
        history_choices = build_history_choices(repository, segments)
        memory = (
            repository.get_latest_memory_snapshot(target_branch_id)
            if target_branch_id is not None
            else None
        )
        visible_summary, summary_source = build_visible_summary(memory, segments)
        return templates.TemplateResponse(
            request=request,
            name="reader.html",
            context={
                "story": story,
                "branch": branch_obj,
                "segments": segments,
                "current_choice": current_choice,
                "branches": branches,
                "history_choices": history_choices,
                "visible_summary": visible_summary,
                "summary_source": summary_source,
                "status_labels": STATUS_LABELS,
            },
        )

    return router

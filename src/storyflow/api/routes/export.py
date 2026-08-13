from __future__ import annotations

"""Markdown export and story read endpoints under /api/stories."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from storyflow.api.dependencies import optional_session_id
from storyflow.db.repositories import StoryRepository
from storyflow.domain.models import Story
from storyflow.services.export import export_branch_markdown, safe_filename


def create_export_router(repository: StoryRepository | None) -> APIRouter:
    router = APIRouter(prefix="/api/stories", tags=["export"])

    @router.get("/{story_id}", response_model=Story)
    def get_story_api(
        story_id: UUID,
        request: Request,
        session_id: str | None = Depends(optional_session_id),
    ) -> Story:
        if repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        story = repository.get_story(story_id)
        if story is None or (session_id is not None and story.session_id != session_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"code": "story_not_found"})
        return story

    @router.get("/{story_id}/export.md")
    def export_story(
        story_id: UUID,
        request: Request,
        branch: UUID | None = None,
        session_id: str | None = Depends(optional_session_id),
    ) -> Response:
        if repository is None:
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        story = repository.get_story(story_id)
        if story is None:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        if session_id is not None and story.session_id != session_id:
            return Response(status_code=status.HTTP_404_NOT_FOUND)
        target_branch_id = branch or story.current_branch_id
        if target_branch_id is not None:
            target_branch = repository.get_branch(target_branch_id)
            if target_branch is None or target_branch.story_id != story.id:
                return Response(status_code=status.HTTP_404_NOT_FOUND)
        content = export_branch_markdown(repository, story, target_branch_id)
        filename = safe_filename(story.title or "story")
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )

    return router


__all__ = ["create_export_router"]

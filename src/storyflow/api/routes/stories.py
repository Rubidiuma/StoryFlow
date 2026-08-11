from __future__ import annotations

"""Story draft and Bible lifecycle routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from storyflow.api.dependencies import optional_session_id
from storyflow.db.repositories import (
    IllegalStoryStateError,
    IncompleteBibleBundleError,
    StoryNotFoundError,
    StoryRepository,
)
from storyflow.domain.enums import StoryStatus
from storyflow.domain.models import Story, StoryConfig
from storyflow.llm.base import LLMClient
from storyflow.services.bible import (
    BibleGenerationRequestError,
    BibleGenerationValidationError,
    PersistedBibleBundle,
    generate_validated_bible,
    persist_generated_bible,
)


class CreateStoryRequest(BaseModel):
    """Input accepted when starting a new story draft."""

    session_id: str
    title: str = "Untitled"
    config: StoryConfig


def create_story_router(
    repository: StoryRepository | None, llm_client: LLMClient | None = None
) -> APIRouter:
    """Build story routes around explicitly configured persistence."""
    router = APIRouter(prefix="/stories", tags=["stories"])

    @router.get("/{story_id}", response_model=Story)
    def get_story(
        story_id: UUID,
        request: Request,
        session_id: str | None = Depends(optional_session_id),
    ) -> Story:
        if repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail={"code": "STORY_SERVICE_UNAVAILABLE", "retryable": True})
        story = repository.get_story(story_id)
        if story is None or (session_id is not None and story.session_id != session_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"code": "story_not_found"})
        return story

    @router.post("", response_model=Story, status_code=status.HTTP_201_CREATED)
    def create_story(request: CreateStoryRequest) -> Story:
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORY_SERVICE_UNAVAILABLE", "retryable": True},
            )
        story = Story(
            session_id=request.session_id,
            title=request.title,
            choice_frequency=request.config.choice_frequency,
            config=request.config,
            pause_requested=False,
            version=1,
        )
        return repository.create_story(story)

    @router.post("/{story_id}/bible/generate", response_model=PersistedBibleBundle)
    async def generate_bible(story_id: UUID) -> PersistedBibleBundle:
        if repository is None or llm_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORY_SERVICE_UNAVAILABLE", "retryable": True},
            )
        story = repository.get_story(story_id)
        if story is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
        if story.status != StoryStatus.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BIBLE_GENERATION_CONFLICT",
                    "message": "Story cannot generate a Bible from its current state or version.",
                },
            )
        try:
            generated = await generate_validated_bible(story, llm_client)
        except BibleGenerationValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "BIBLE_GENERATION_INVALID_RESPONSE",
                    "message": "Generated Bible could not be validated.",
                    "retryable": True,
                },
            ) from exc
        except BibleGenerationRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "BIBLE_GENERATION_REQUEST_FAILED",
                    "message": "Story Bible generation request failed.",
                    "retryable": True,
                },
            ) from exc
        try:
            return persist_generated_bible(story, generated, repository)
        except IllegalStoryStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BIBLE_GENERATION_CONFLICT",
                    "message": "Story cannot generate a Bible from its current state or version.",
                },
            ) from exc

    @router.post("/{story_id}/bible/confirm", response_model=Story)
    def confirm_bible(story_id: UUID) -> Story:
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORY_SERVICE_UNAVAILABLE", "retryable": True},
            )
        try:
            return repository.confirm_bible(story_id)
        except StoryNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Story not found"
            ) from exc
        except IncompleteBibleBundleError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BIBLE_BUNDLE_INCOMPLETE",
                    "message": "A complete generated Bible bundle is required.",
                },
            ) from exc
        except IllegalStoryStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BIBLE_CONFIRMATION_CONFLICT",
                    "message": "Story cannot be confirmed from its current state.",
                },
            ) from exc

    return router

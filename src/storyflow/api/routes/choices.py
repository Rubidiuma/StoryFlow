from __future__ import annotations

"""Atomic preset and custom choice submission routes."""

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator

_log = logging.getLogger(__name__)

from storyflow.db.repositories import (
    ChoiceNotFoundError,
    ChoiceNotSelectedError,
    ChoiceOptionNotFoundError,
    ChoiceSubmissionResult,
    ChoiceVersionConflictError,
    InvalidChoiceEffectsError,
    InvalidChoiceStateError,
    StoryRepository,
)
from storyflow.domain.enums import StoryStatus
from storyflow.domain.models import CustomAction
from storyflow.llm.base import LLMClient
from storyflow.prompts.choice import CUSTOM_ACTION_EFFECTS_PROMPT_V1


class SelectChoiceRequest(BaseModel):
    """Exactly one preset option or bounded custom action at one choice version."""

    choice_version: int = Field(ge=1)
    option_id: UUID | None = None
    custom_action: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def exactly_one_selection(self) -> SelectChoiceRequest:
        if (self.option_id is None) == (self.custom_action is None):
            raise ValueError("exactly one option_id or custom_action is required")
        if self.custom_action is not None:
            CustomAction(text=self.custom_action)
        return self


class SelectChoiceResponse(BaseModel):
    """Stable public result for an accepted request or its exact replay."""

    status: Literal["success", "duplicate"]
    choice_id: UUID
    choice_version: int
    story_status: StoryStatus


class CreateBranchRequest(BaseModel):
    """Optional metadata for a new fork branch."""

    name: str = Field(default="Branch", min_length=1, max_length=200)


class CreateBranchResponse(BaseModel):
    """Stable public result for a successfully created fork branch."""

    branch_id: UUID
    story_id: UUID
    fork_segment_id: UUID
    memory_snapshot_id: UUID


def create_choice_router(
    repository: StoryRepository | None,
    llm_client: LLMClient | None = None,
) -> APIRouter:
    """Build choice routes around explicitly injected persistence and model clients."""
    router = APIRouter(prefix="/api/choices", tags=["choices"])

    @router.post("/{choice_id}/select", response_model=SelectChoiceResponse)
    async def select_choice(
        choice_id: UUID,
        request: SelectChoiceRequest,
    ) -> SelectChoiceResponse:
        if repository is None:
            raise _choice_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "choice_service_unavailable",
                retryable=True,
            )
        existing = repository.get_choice_with_story(choice_id)
        if existing is None:
            raise _choice_error(status.HTTP_404_NOT_FOUND, "choice_not_found")
        choice, story = existing
        _log.warning(
            "select_choice: choice_id=%s choice.version=%s request.version=%s "
            "choice.status=%s story.status=%s story.current_branch_id=%s",
            choice_id, choice.version, request.choice_version,
            choice.status, story.status, story.current_branch_id,
        )
        if choice.version != request.choice_version:
            if (
                choice.status == "selected"
                and choice.version == request.choice_version + 1
                and choice.selected_option_id == request.option_id
                and choice.selected_custom_action == request.custom_action
            ):
                return _response(
                    ChoiceSubmissionResult(
                        status="duplicate", choice=choice, story=story
                    )
                )
            raise _choice_error(
                status.HTTP_409_CONFLICT, "choice_version_conflict"
            )
        if story.status is not StoryStatus.WAITING_CHOICE:
            _log.warning("invalid_choice_state: story.status=%s (expected WAITING_CHOICE)", story.status)
            raise _choice_error(status.HTTP_409_CONFLICT, "invalid_choice_state")

        custom_effects: dict[str, object] | None = None
        if request.custom_action is not None:
            if llm_client is None:
                raise _choice_error(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "choice_service_unavailable",
                    retryable=True,
                )
            try:
                custom_effects = await llm_client.generate_json(
                    prompt=CUSTOM_ACTION_EFFECTS_PROMPT_V1,
                    context={
                        "choice_id": str(choice.id),
                        "custom_action": request.custom_action,
                        "available_options": [option.text for option in choice.options],
                    },
                )
            except Exception as exc:
                raise _choice_error(
                    status.HTTP_502_BAD_GATEWAY,
                    "custom_action_parse_failed",
                    retryable=True,
                ) from exc

        try:
            result = repository.submit_choice(
                choice_id,
                request.choice_version,
                option_id=request.option_id,
                custom_action=request.custom_action,
                custom_effects=custom_effects,
            )
        except ChoiceNotFoundError as exc:
            raise _choice_error(status.HTTP_404_NOT_FOUND, "choice_not_found") from exc
        except ChoiceVersionConflictError as exc:
            raise _choice_error(
                status.HTTP_409_CONFLICT, "choice_version_conflict"
            ) from exc
        except InvalidChoiceStateError as exc:
            raise _choice_error(status.HTTP_409_CONFLICT, "invalid_choice_state") from exc
        except ChoiceOptionNotFoundError as exc:
            raise _choice_error(
                status.HTTP_409_CONFLICT, "choice_option_conflict"
            ) from exc
        except InvalidChoiceEffectsError as exc:
            if request.custom_action is not None:
                raise _choice_error(
                    status.HTTP_502_BAD_GATEWAY,
                    "custom_action_parse_failed",
                    retryable=True,
                ) from exc
            raise _choice_error(
                status.HTTP_409_CONFLICT, "choice_effects_invalid"
            ) from exc
        return _response(result)

    @router.post("/{choice_id}/branch", response_model=CreateBranchResponse)
    async def create_branch(
        choice_id: UUID,
        request: CreateBranchRequest,
    ) -> CreateBranchResponse:
        if repository is None:
            raise _choice_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "choice_service_unavailable",
                retryable=True,
            )
        try:
            new_branch, new_snapshot = repository.fork_at_choice(choice_id, request.name)
        except ChoiceNotFoundError as exc:
            raise _choice_error(status.HTTP_404_NOT_FOUND, "choice_not_found") from exc
        except ChoiceNotSelectedError as exc:
            raise _choice_error(status.HTTP_409_CONFLICT, "choice_not_selected") from exc
        assert new_branch.fork_segment_id is not None
        return CreateBranchResponse(
            branch_id=new_branch.id,
            story_id=new_branch.story_id,
            fork_segment_id=new_branch.fork_segment_id,
            memory_snapshot_id=new_snapshot.id,
        )

    return router


def _response(result: ChoiceSubmissionResult) -> SelectChoiceResponse:
    return SelectChoiceResponse(
        status=result.status,
        choice_id=result.choice.id,
        choice_version=result.choice.version,
        story_status=result.story.status,
    )


def _choice_error(
    status_code: int,
    code: str,
    *,
    retryable: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "retryable": retryable},
    )


__all__ = ["create_choice_router", "CreateBranchRequest", "CreateBranchResponse"]

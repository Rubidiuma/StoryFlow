from __future__ import annotations

"""Bounded AI assistance for one story configuration field at a time."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from storyflow.llm.base import LLMClient
from storyflow.prompts.field_improvement import FIELD_IMPROVEMENT_PROMPT
from storyflow.services.field_improvement import (
    FIELD_LABELS,
    FIELD_LIMITS,
    filter_context,
    validate_suggestion,
)


class ImproveFieldRequest(BaseModel):
    """Validated input for one field-improvement request."""

    field: str
    value: str = Field(max_length=2000)
    context: dict[str, str] = Field(default_factory=dict)

    @field_validator("field")
    @classmethod
    def supported_field(cls, value: str) -> str:
        if value not in FIELD_LIMITS:
            raise ValueError("unsupported story configuration field")
        return value

    @field_validator("context")
    @classmethod
    def supported_context(cls, value: dict[str, str]) -> dict[str, str]:
        for field, content in value.items():
            if field not in FIELD_LIMITS:
                raise ValueError("unsupported context field")
            if len(content) > FIELD_LIMITS[field]:
                raise ValueError("context field exceeds maximum length")
        return value

    @model_validator(mode="after")
    def target_length(self) -> ImproveFieldRequest:
        if len(self.value) > FIELD_LIMITS[self.field]:
            raise ValueError("target field exceeds maximum length")
        return self


class ImproveFieldResponse(BaseModel):
    field: str
    suggestion: str


def create_field_improvement_router(llm_client: LLMClient | None) -> APIRouter:
    """Build the single-field improvement endpoint around the configured model."""
    router = APIRouter(prefix="/api/story-config", tags=["story-config"])

    @router.post("/improve-field", response_model=ImproveFieldResponse)
    async def improve_field(request: ImproveFieldRequest) -> ImproveFieldResponse:
        if llm_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "FIELD_IMPROVEMENT_UNAVAILABLE", "retryable": True},
            )

        model_context: dict[str, object] = {
            "target_field": request.field,
            "field_label": FIELD_LABELS[request.field],
            "current_value": request.value.strip(),
            "other_settings": filter_context(request.context, target_field=request.field),
            "max_length": FIELD_LIMITS[request.field],
        }
        try:
            raw = await llm_client.generate_json(
                prompt=FIELD_IMPROVEMENT_PROMPT,
                context=model_context,
            )
            suggestion = validate_suggestion(request.field, raw.get("suggestion"))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "FIELD_IMPROVEMENT_FAILED", "retryable": True},
            ) from exc

        return ImproveFieldResponse(field=request.field, suggestion=suggestion)

    return router

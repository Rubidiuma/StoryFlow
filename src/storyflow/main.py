"""FastAPI application entry point."""

from fastapi import FastAPI

from storyflow.api.routes.generation import create_generation_router
from storyflow.api.routes.stories import create_story_router
from storyflow.db.repositories import StoryRepository
from storyflow.llm.base import LLMClient


def create_app(
    repository: StoryRepository | None = None,
    llm_client: LLMClient | None = None,
    *,
    emit_generation_heartbeat: bool = False,
) -> FastAPI:
    """Create the StoryFlow application."""
    app = FastAPI(title="StoryFlow", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report application readiness without exposing credentials."""
        return {
            "status": "ok",
            "application": "ready",
            "database": "unconfigured",
            "llm": "unconfigured",
        }

    app.include_router(create_story_router(repository, llm_client))
    app.include_router(
        create_generation_router(
            repository,
            llm_client,
            emit_heartbeat=emit_generation_heartbeat,
        )
    )
    return app


app = create_app()

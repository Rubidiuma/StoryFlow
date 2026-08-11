from __future__ import annotations

"""FastAPI application entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from storyflow.api.routes.choices import create_choice_router
from storyflow.api.routes.export import create_export_router
from storyflow.api.routes.generation import create_generation_router
from storyflow.api.routes.stories import create_story_router
from storyflow.api.routes.web import WEB_STATIC_DIRECTORY, create_web_router
from storyflow.db.repositories import StoryRepository
from storyflow.llm.base import LLMClient
from storyflow.security.credentials import CredentialProvider
from storyflow.security.rate_limit import RateLimiter
from storyflow.services.generation import recover_interrupted_generations


def create_app(
    repository: StoryRepository | None = None,
    llm_client: LLMClient | None = None,
    *,
    emit_generation_heartbeat: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Create the StoryFlow application."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if repository is not None:
            recover_interrupted_generations(repository)
        yield

    app = FastAPI(title="StoryFlow", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=WEB_STATIC_DIRECTORY), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report application readiness without exposing credentials."""
        return {
            "status": "ok",
            "application": "ready",
            "database": "configured" if repository is not None else "unconfigured",
            "llm": "configured" if llm_client is not None else "unconfigured",
        }

    app.include_router(create_web_router(repository))
    app.include_router(create_story_router(repository, llm_client))
    app.include_router(create_choice_router(repository, llm_client))
    app.include_router(create_export_router(repository))
    app.include_router(
        create_generation_router(
            repository,
            llm_client,
            emit_heartbeat=emit_generation_heartbeat,
            rate_limiter=rate_limiter,
        )
    )
    return app


def _build_repository() -> StoryRepository:
    """Open (and initialize if needed) the SQLite database from STORYFLOW_DB_PATH."""
    from pathlib import Path
    from storyflow.db.database import Database
    default_db = "/data/storyflow.sqlite3" if os.path.isdir("/data") else "storyflow.sqlite3"
    db_path = Path(os.getenv("STORYFLOW_DB_PATH", default_db))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(db_path)
    database.initialize()
    return StoryRepository(database)


def _build_llm_client() -> LLMClient | None:
    """Create the real LLM client from environment or secret file credentials."""
    from pathlib import Path
    secret_file_path = os.getenv("STORYFLOW_LLM_KEY_FILE")
    secret_file = Path(secret_file_path) if secret_file_path else None
    provider = CredentialProvider(secret_file=secret_file)
    api_key = provider.get_llm_key()
    if api_key is None:
        return None
    base_url = os.getenv("STORYFLOW_LLM_BASE_URL") or None
    from storyflow.llm.provider import ProviderLLMClient
    return ProviderLLMClient(api_key=api_key, base_url=base_url)


app = create_app(
    repository=_build_repository(),
    llm_client=_build_llm_client(),
)

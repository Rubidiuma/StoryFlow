"""FastAPI application entry point."""

from fastapi import FastAPI


def create_app() -> FastAPI:
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

    return app


app = create_app()

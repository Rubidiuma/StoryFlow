"""Non-sensitive runtime configuration for StoryFlow."""

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings that are safe to read from the environment."""

    environment: str
    host: str
    port: int


def load_settings() -> Settings:
    """Load application runtime settings without reading credentials."""
    return Settings(
        environment=getenv("STORYFLOW_ENVIRONMENT", "development"),
        host=getenv("STORYFLOW_HOST", "127.0.0.1"),
        port=int(getenv("STORYFLOW_PORT", "8000")),
    )

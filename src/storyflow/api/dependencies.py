from __future__ import annotations

"""FastAPI dependencies for session and credential injection."""

from fastapi import Request

from storyflow.security.sessions import get_session_id


def optional_session_id(request: Request) -> str | None:
    """FastAPI dependency: extract session ID without requiring its presence."""
    return get_session_id(request)

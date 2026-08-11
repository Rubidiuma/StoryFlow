from __future__ import annotations

"""Session ID extraction from request headers and cookies."""

from fastapi import Request


def get_session_id(request: Request) -> str | None:
    """Return the session ID from X-Session-ID header or session_id cookie."""
    return request.headers.get("X-Session-ID") or request.cookies.get("session_id") or None

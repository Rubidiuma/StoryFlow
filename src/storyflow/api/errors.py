"""Stable, non-sensitive API error payloads."""

from typing import Final

from fastapi import HTTPException

_GENERATION_RETRYABILITY: Final[dict[str, bool]] = {
    "director_failed": True,
    "director_invalid": False,
    "writer_failed": True,
    "commit_failed": True,
    "invalid_generation_state": False,
}


def generation_error_data(code: str | None) -> dict[str, object]:
    """Map an internal generation result to its public stable error shape."""
    stable_code = code if code in _GENERATION_RETRYABILITY else "generation_failed"
    return {
        "code": stable_code,
        "retryable": _GENERATION_RETRYABILITY.get(stable_code, False),
    }


def generation_http_error(
    status_code: int,
    code: str,
    *,
    retryable: bool = False,
) -> HTTPException:
    """Create a normal JSON HTTP error without an internal message."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "retryable": retryable},
    )


__all__ = ["generation_error_data", "generation_http_error"]

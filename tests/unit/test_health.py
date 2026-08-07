"""Health endpoint contract tests."""

import httpx
import pytest

from storyflow.main import create_app


@pytest.mark.asyncio
async def test_health_returns_non_sensitive_component_statuses() -> None:
    """The health check exposes readiness without exposing credentials."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": "ready",
        "database": "unconfigured",
        "llm": "unconfigured",
    }
    assert not ({"key", "secret", "token"} & set(response.json()))

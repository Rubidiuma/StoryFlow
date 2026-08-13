from __future__ import annotations

import httpx
import pytest

from storyflow.llm.fake import FakeLLMClient
from storyflow.main import create_app


def request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "field": "world_background",
        "value": "海上城市",
        "context": {
            "genre": "东方奇幻",
            "forbidden_elements": "禁止穿越和复活",
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_improve_field_returns_validated_chinese_suggestion() -> None:
    llm = FakeLLMClient(
        json_responses=[{"suggestion": "城市漂浮在永夜海面，潮汐会唤醒沉睡的古老灯塔。"}]
    )
    transport = httpx.ASGITransport(app=create_app(llm_client=llm))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/story-config/improve-field", json=request_payload()
        )

    assert response.status_code == 200
    assert response.json() == {
        "field": "world_background",
        "suggestion": "城市漂浮在永夜海面，潮汐会唤醒沉睡的古老灯塔。",
    }
    assert llm.calls[0]["context"] == {
        "target_field": "world_background",
        "field_label": "世界背景",
        "current_value": "海上城市",
        "other_settings": {
            "genre": "东方奇幻",
            "forbidden_elements": "禁止穿越和复活",
        },
        "max_length": 2000,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        request_payload(field="title"),
        request_payload(value="字" * 2001),
    ],
)
async def test_improve_field_rejects_unsupported_or_oversized_input(
    payload: dict[str, object],
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(llm_client=FakeLLMClient(json_responses=[]))
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/story-config/improve-field", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_improve_field_reports_missing_llm_without_calling_provider() -> None:
    transport = httpx.ASGITransport(app=create_app(llm_client=None))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/story-config/improve-field", json=request_payload()
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "FIELD_IMPROVEMENT_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_response",
    [RuntimeError("provider unavailable"), {"suggestion": "...!!!"}],
)
async def test_improve_field_maps_provider_and_invalid_output_to_bad_gateway(
    provider_response: object,
) -> None:
    llm = FakeLLMClient(json_responses=[provider_response])
    transport = httpx.ASGITransport(app=create_app(llm_client=llm))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/story-config/improve-field", json=request_payload()
        )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "FIELD_IMPROVEMENT_FAILED"

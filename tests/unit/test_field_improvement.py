from __future__ import annotations

import pytest

from storyflow.services.field_improvement import is_incomplete


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("。？！……", True),
        ("悬疑冒险篇", True),
        ("悬疑冒险故事", False),
        ("一名失忆侦探在雨夜追查连环失踪案。", False),
    ],
)
def test_is_incomplete_uses_meaningful_character_boundary(
    value: str, expected: bool
) -> None:
    assert is_incomplete(value) is expected

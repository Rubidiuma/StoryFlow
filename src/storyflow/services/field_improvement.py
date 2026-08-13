from __future__ import annotations

"""Validation policy for AI-assisted story configuration fields."""

import re
from collections.abc import Mapping


FIELD_LIMITS: dict[str, int] = {
    "genre": 200,
    "structure": 200,
    "world_background": 2000,
    "protagonist_desc": 2000,
    "important_supporting_characters": 1000,
    "style": 500,
    "required_elements": 1000,
    "forbidden_elements": 1000,
    "ending_tendency": 1000,
}

FIELD_LABELS: dict[str, str] = {
    "genre": "题材类型",
    "structure": "故事结构",
    "world_background": "世界背景",
    "protagonist_desc": "主角设定",
    "important_supporting_characters": "重要配角",
    "style": "叙事风格",
    "required_elements": "必须包含的元素",
    "forbidden_elements": "禁止出现的元素",
    "ending_tendency": "结局倾向",
}

_MEANINGFUL_CHARACTER = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
_CHINESE_CHARACTER = re.compile(r"[\u3400-\u9fff]")


def is_incomplete(value: str) -> bool:
    """Return whether *value* has fewer than six meaningful characters."""
    return len(_MEANINGFUL_CHARACTER.findall(value)) < 6


def filter_context(context: Mapping[str, str], *, target_field: str) -> dict[str, str]:
    """Keep only supported, non-target story fields for the model."""
    return {
        field: value.strip()
        for field, value in context.items()
        if field in FIELD_LIMITS and field != target_field and value.strip()
    }


def validate_suggestion(field: str, suggestion: object) -> str:
    """Normalize a provider suggestion and enforce the public response contract."""
    if not isinstance(suggestion, str):
        raise ValueError("suggestion must be text")
    normalized = suggestion.strip()
    if not normalized or not _CHINESE_CHARACTER.search(normalized):
        raise ValueError("suggestion must contain Chinese text")
    if len(normalized) > FIELD_LIMITS[field]:
        raise ValueError("suggestion exceeds field length")
    return normalized

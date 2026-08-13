from __future__ import annotations

"""User-visible history and summary data for the story reader."""

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Literal, Protocol
from uuid import UUID

from storyflow.domain.models import ChoicePoint, MemorySnapshot, StorySegment


class _ChoiceReader(Protocol):
    def get_choice_point_for_segment(self, segment_id: UUID) -> ChoicePoint | None: ...


@dataclass(frozen=True, slots=True)
class HistoryChoice:
    choice_id: UUID
    segment_id: UUID
    selected_text: str


def build_history_choices(
    repository: _ChoiceReader,
    segments: Sequence[StorySegment],
) -> dict[UUID, HistoryChoice]:
    """Return public selected-action text keyed by its scene."""
    history: dict[UUID, HistoryChoice] = {}
    for segment in sorted(segments, key=lambda item: item.sequence):
        choice = repository.get_choice_point_for_segment(segment.id)
        if choice is None or choice.status != "selected":
            continue
        selected_text = _selected_text(choice)
        if selected_text:
            history[segment.id] = HistoryChoice(
                choice_id=choice.id,
                segment_id=segment.id,
                selected_text=selected_text,
            )
    return history


def build_visible_summary(
    snapshot: MemorySnapshot | None,
    segments: Sequence[StorySegment],
) -> tuple[str, Literal["rolling", "stage", "empty"]]:
    """Choose the persisted rollup or an ordered public scene-summary fallback."""
    if (
        snapshot is not None
        and snapshot.rolling_summary.strip()
        and re.search(r"[\u3400-\u9fff]", snapshot.rolling_summary)
    ):
        return snapshot.rolling_summary.strip(), "rolling"
    summaries = [
        segment.summary.strip()
        for segment in sorted(segments, key=lambda item: item.sequence)
        if segment.summary.strip() and re.search(r"[\u3400-\u9fff]", segment.summary)
    ]
    if summaries:
        return "\n\n".join(summaries), "stage"
    if segments:
        latest = max(segment.sequence for segment in segments)
        return f"故事已推进至第 {latest} 个场景，后续将继续更新中文剧情摘要。", "stage"
    return "", "empty"


def _selected_text(choice: ChoicePoint) -> str:
    if choice.selected_option_id is not None:
        option = next(
            (item for item in choice.options if item.id == choice.selected_option_id),
            None,
        )
        return option.text.strip() if option is not None else ""
    return (choice.selected_custom_action or "").strip()


__all__ = ["HistoryChoice", "build_history_choices", "build_visible_summary"]

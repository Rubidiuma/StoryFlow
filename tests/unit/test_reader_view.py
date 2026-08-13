from __future__ import annotations

from uuid import uuid4

from storyflow.domain.enums import ChoiceType
from storyflow.domain.models import ChoiceOption, ChoicePoint, MemorySnapshot, StorySegment
from storyflow.services.reader_view import build_history_choices, build_visible_summary


def _segment(sequence: int, summary: str) -> StorySegment:
    return StorySegment(
        story_id=uuid4(),
        branch_id=uuid4(),
        sequence=sequence,
        content=f"正文 {sequence}",
        summary=summary,
        generation_key=f"reader-view-{sequence}-{uuid4()}",
    )


class _ChoiceRepository:
    def __init__(self, choices: dict[object, ChoicePoint]) -> None:
        self.choices = choices

    def get_choice_point_for_segment(self, segment_id: object) -> ChoicePoint | None:
        return self.choices.get(segment_id)


def _selected_choice(*, custom_action: str | None = None) -> ChoicePoint:
    options = [
        ChoiceOption(text="进入主控舱", effects={"route_change": "control"}),
        ChoiceOption(text="返回潜艇", effects={"route_change": "submarine"}),
        ChoiceOption(text="呼叫队友", effects={"route_change": "radio"}),
    ]
    return ChoicePoint(
        type=ChoiceType.DECISION,
        reason="基地开始坍塌",
        options=options,
        status="selected",
        selected_option_id=None if custom_action else options[0].id,
        selected_custom_action=custom_action,
        selected_effects={"information_state": "不可展示的隐藏影响"},
        version=2,
    )


def test_history_choices_expose_selected_text_without_hidden_effects() -> None:
    preset_segment = _segment(1, "进入基地")
    custom_segment = _segment(2, "抵达舱门")
    repository = _ChoiceRepository(
        {
            preset_segment.id: _selected_choice(),
            custom_segment.id: _selected_choice(custom_action="切断备用电源"),
        }
    )

    history = build_history_choices(repository, [custom_segment, preset_segment])

    assert history[preset_segment.id].selected_text == "进入主控舱"
    assert history[custom_segment.id].selected_text == "切断备用电源"
    assert "不可展示" not in repr(history)


def test_visible_summary_prefers_persisted_rolling_summary() -> None:
    segment = _segment(1, "旧短摘要")
    snapshot = MemorySnapshot(
        story_id=segment.story_id,
        branch_id=segment.branch_id,
        rolling_summary="五幕以来，李云已进入主控舱。",
    )

    text, source = build_visible_summary(snapshot, [segment])

    assert (text, source) == ("五幕以来，李云已进入主控舱。", "rolling")


def test_visible_summary_uses_ordered_nonblank_scene_summaries_before_first_rollup() -> None:
    first = _segment(1, "进入基地")
    blank = _segment(2, "   ")
    third = _segment(3, "发现密门")

    text, source = build_visible_summary(None, [third, blank, first])

    assert text == "进入基地\n\n发现密门"
    assert source == "stage"


def test_visible_summary_reports_empty_story() -> None:
    assert build_visible_summary(None, []) == ("", "empty")

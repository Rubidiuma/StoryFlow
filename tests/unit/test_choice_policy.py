"""Unit tests for the pure StoryFlow choice-point policy."""

from typing import cast

import pytest

from storyflow.domain.enums import ChoiceFrequency, ChoiceType
from storyflow.domain.models import ChoiceOption, ChoicePoint
from storyflow.services.choice_policy import (
    ChoiceDecision,
    ChoicePolicyResult,
    evaluate_choice_policy,
)


def valid_suggestion() -> ChoicePoint:
    """Build a model-originated choice suggestion that satisfies the policy contract."""
    return ChoicePoint(
        type=ChoiceType.DECISION,
        reason="The bridge is collapsing behind the hero.",
        status="pending",
        options=[
            ChoiceOption(text="Cross the bridge", effects={"route": "keep"}, position=0),
            ChoiceOption(text="Climb down", effects={"route": "river"}, position=1),
            ChoiceOption(text="Turn back", effects={"route": "village"}, position=2),
        ],
    )


def malformed_suggestion(*, reason: str = "A conflict", options: list[ChoiceOption]) -> ChoicePoint:
    """Construct model-shaped invalid input as an untrusted model response could provide it."""
    return ChoicePoint.model_construct(type=ChoiceType.DECISION, reason=reason, options=options)


@pytest.mark.parametrize(
    ("frequency", "distance", "expected"),
    [
        (ChoiceFrequency.FEW, 3, "continue"),
        (ChoiceFrequency.FEW, 4, "accept"),
        (ChoiceFrequency.FEW, 5, "force"),
        (ChoiceFrequency.MEDIUM, 1, "continue"),
        (ChoiceFrequency.MEDIUM, 2, "accept"),
        (ChoiceFrequency.MEDIUM, 3, "force"),
        (ChoiceFrequency.MANY, 0, "continue"),
        (ChoiceFrequency.MANY, 1, "accept"),
        (ChoiceFrequency.MANY, 2, "force"),
    ],
)
def test_frequency_boundaries_return_hand_checked_decisions(
    frequency: ChoiceFrequency, distance: int, expected: ChoiceDecision
):
    """An incorrect minimum or maximum interval changes the returned policy decision."""
    result = evaluate_choice_policy(frequency, distance, valid_suggestion())

    assert result == ChoicePolicyResult(decision=expected)


@pytest.mark.parametrize(
    ("frequency", "distance"),
    [
        (ChoiceFrequency.FEW, 0),
        (ChoiceFrequency.MEDIUM, 1),
        (ChoiceFrequency.MANY, 0),
    ],
)
def test_pre_minimum_valid_suggestion_is_rejected(
    frequency: ChoiceFrequency, distance: int
):
    """A premature suggestion must not become a reader-facing choice."""
    assert evaluate_choice_policy(frequency, distance, valid_suggestion()).decision == "continue"


@pytest.mark.parametrize(
    ("frequency", "distance"),
    [
        (ChoiceFrequency.FEW, 4),
        (ChoiceFrequency.MEDIUM, 2),
        (ChoiceFrequency.MANY, 1),
    ],
)
def test_window_accepts_a_valid_suggestion_and_continues_without_one(
    frequency: ChoiceFrequency, distance: int
):
    """Within the interval, only an actual valid suggestion creates a choice."""
    assert evaluate_choice_policy(frequency, distance, valid_suggestion()).decision == "accept"
    assert evaluate_choice_policy(frequency, distance, None).decision == "continue"


@pytest.mark.parametrize(
    ("frequency", "distance"),
    [
        (ChoiceFrequency.FEW, 5),
        (ChoiceFrequency.FEW, 8),
        (ChoiceFrequency.MEDIUM, 3),
        (ChoiceFrequency.MEDIUM, 6),
        (ChoiceFrequency.MANY, 2),
        (ChoiceFrequency.MANY, 4),
    ],
)
def test_maximum_and_later_distances_force_or_safely_pause(
    frequency: ChoiceFrequency, distance: int
):
    """A missed required choice is either forced from valid input or safely paused."""
    assert evaluate_choice_policy(frequency, distance, valid_suggestion()).decision == "force"
    assert evaluate_choice_policy(frequency, distance, None).decision == "pause"


@pytest.mark.parametrize(
    "suggestion",
    [
        malformed_suggestion(
            options=[
                ChoiceOption(text="One", effects={"route": "a"}, position=0),
                ChoiceOption(text=" one ", effects={"route": "b"}, position=1),
                ChoiceOption(text="Three", effects={"route": "c"}, position=2),
            ]
        ),
        malformed_suggestion(
            reason="   ",
            options=[
                ChoiceOption(text="One", effects={"route": "a"}, position=0),
                ChoiceOption(text="Two", effects={"route": "b"}, position=1),
                ChoiceOption(text="Three", effects={"route": "c"}, position=2),
            ],
        ),
        malformed_suggestion(
            options=[
                ChoiceOption(text="One", effects={"route": "a"}, position=0),
                ChoiceOption(text="Two", effects={"route": "b"}, position=1),
            ]
        ),
        malformed_suggestion(
            options=[
                ChoiceOption.model_construct(text="One", effects={}, position=0),
                ChoiceOption(text="Two", effects={"route": "b"}, position=1),
                ChoiceOption(text="Three", effects={"route": "c"}, position=2),
            ]
        ),
    ],
)
def test_invalid_suggestions_continue_before_maximum_and_pause_at_maximum(
    suggestion: ChoicePoint,
):
    """Malformed model output is never accepted or forced into a reader decision."""
    before_maximum = evaluate_choice_policy(ChoiceFrequency.MEDIUM, 2, suggestion)
    at_maximum = evaluate_choice_policy(ChoiceFrequency.MEDIUM, 3, suggestion)

    assert before_maximum.decision == "continue"
    assert at_maximum.decision == "pause"


def test_policy_does_not_mutate_a_valid_suggestion():
    """Checking a suggestion must leave the model-owned domain object unchanged."""
    suggestion = valid_suggestion()
    before = suggestion.model_dump(mode="json")

    evaluate_choice_policy(ChoiceFrequency.MEDIUM, 2, suggestion)

    assert suggestion.model_dump(mode="json") == before


@pytest.mark.parametrize(
    ("frequency", "distance", "error_type"),
    [
        (ChoiceFrequency.MEDIUM, -1, ValueError),
        ("中", 2, TypeError),
        (ChoiceFrequency.MEDIUM, 2.5, TypeError),
        (ChoiceFrequency.MEDIUM, True, TypeError),
    ],
)
def test_policy_rejects_malformed_frequency_or_distance(
    frequency: object, distance: object, error_type: type[Exception]
):
    """Unrepresentable intervals and non-enum frequencies cannot select policy behavior."""
    with pytest.raises(error_type):
        evaluate_choice_policy(
            cast(ChoiceFrequency, frequency), cast(int, distance), valid_suggestion()
        )

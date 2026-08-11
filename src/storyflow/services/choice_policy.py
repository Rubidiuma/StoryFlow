"""Pure policy for deciding whether a model choice suggestion may be shown."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from storyflow.domain.enums import ChoiceFrequency
from storyflow.domain.models import ChoiceOption, ChoicePoint

ChoiceDecision = Literal["continue", "accept", "force", "pause"]


@dataclass(frozen=True, slots=True)
class ChoicePolicyResult:
    """The deterministic result of checking one optional choice suggestion."""

    decision: ChoiceDecision


def evaluate_choice_policy(
    frequency: ChoiceFrequency,
    scenes_since_last_choice: int,
    suggestion: ChoicePoint | None,
) -> ChoicePolicyResult:
    """Return the safe action for a choice suggestion at this scene distance."""
    minimum, maximum = _interval_for(frequency)
    _validate_distance(scenes_since_last_choice)

    if scenes_since_last_choice < minimum:
        return ChoicePolicyResult(decision="continue")

    valid_suggestion = _is_valid_suggestion(suggestion)
    if scenes_since_last_choice < maximum:
        return ChoicePolicyResult(decision="accept" if valid_suggestion else "continue")

    return ChoicePolicyResult(decision="force" if valid_suggestion else "pause")


def _interval_for(frequency: ChoiceFrequency) -> tuple[int, int]:
    """Return the inclusive scene-distance bounds for one configured frequency."""
    if not isinstance(frequency, ChoiceFrequency):
        raise TypeError("choice frequency must be a ChoiceFrequency")
    if frequency is ChoiceFrequency.FEW:
        return 4, 5
    if frequency is ChoiceFrequency.MEDIUM:
        return 2, 3
    if frequency is ChoiceFrequency.MANY:
        return 1, 2
    raise ValueError("choice frequency is not supported")


def _validate_distance(scenes_since_last_choice: int) -> None:
    """Reject values that cannot represent a completed-scene distance."""
    if isinstance(scenes_since_last_choice, bool) or not isinstance(scenes_since_last_choice, int):
        raise TypeError("scenes since last choice must be an integer")
    if scenes_since_last_choice < 0:
        raise ValueError("scenes since last choice must not be negative")


def _is_valid_suggestion(suggestion: ChoicePoint | None) -> bool:
    """Defensively validate an untrusted model suggestion without changing it."""
    if not isinstance(suggestion, ChoicePoint):
        return False
    if not isinstance(suggestion.reason, str) or not suggestion.reason.strip():
        return False
    if not isinstance(suggestion.options, list) or len(suggestion.options) != 3:
        return False

    normalized_texts: list[str] = []
    for option in suggestion.options:
        if not isinstance(option, ChoiceOption):
            return False
        if not isinstance(option.text, str) or not option.text.strip():
            return False
        if not isinstance(option.effects, Mapping) or not option.effects:
            return False
        normalized_texts.append(option.text.strip().casefold())
    return len(normalized_texts) == len(set(normalized_texts))

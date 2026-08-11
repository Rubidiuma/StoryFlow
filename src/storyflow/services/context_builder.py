"""Deterministic selection of structured story context within a token budget."""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from math import ceil
from typing import Literal

ForeshadowingStatus = Literal["planted", "active", "resolved", "abandoned"]


@dataclass(frozen=True, slots=True)
class SceneMemory:
    """One completed scene and its compact summary."""

    sequence: int
    content: str
    summary: str = ""


@dataclass(frozen=True, slots=True)
class ChoiceMemory:
    """A committed reader choice and its hidden effects."""

    text: str
    effects: dict[str, object]
    result_summary: str = ""


@dataclass(frozen=True, slots=True)
class ForeshadowingMemory:
    """One tracked clue and its lifecycle state."""

    id: str
    description: str
    status: ForeshadowingStatus


@dataclass(frozen=True, slots=True)
class LayeredMemory:
    """Caller-owned memory candidates for one context build."""

    fixed_memory: dict[str, object]
    current_arc: dict[str, object]
    characters: list[dict[str, object]]
    foreshadowing: list[ForeshadowingMemory]
    choices: list[ChoiceMemory]
    rolling_summary: str
    scenes: list[SceneMemory]


@dataclass(frozen=True, slots=True)
class BuiltContext:
    """Selected JSON-ready layers and their deterministic budget accounting."""

    layers: dict[str, object]
    estimated_tokens: int
    budget_tokens: int


class ContextBudgetError(ValueError):
    """Mandatory structured context cannot fit the configured budget."""


def estimate_tokens(value: object) -> int:
    """Estimate tokens from canonical JSON or raw text at four characters each."""
    if value is None or value == "" or value == [] or value == {}:
        return 0
    if isinstance(value, str):
        serialized = value
    else:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return max(1, ceil(len(serialized) / 4))


class ContextBuilder:
    """Build the ordered context layers for a configured token budget."""

    def __init__(self, budget_tokens: int):
        self.budget_tokens = budget_tokens

    def build(self, memory: LayeredMemory) -> BuiltContext:
        """Select active memories and split recent scenes from older summaries."""
        ordered_scenes = sorted(memory.scenes, key=lambda scene: scene.sequence)
        recent_scenes = ordered_scenes[-2:]
        older_scenes = reversed(ordered_scenes[:-2])
        older_scene_summaries = [
            {"sequence": scene.sequence, "summary": scene.summary}
            for scene in older_scenes
        ]
        characters = deepcopy(memory.characters)
        layers: dict[str, object] = {
            "fixed_memory": deepcopy(memory.fixed_memory),
            "current_arc": deepcopy(memory.current_arc),
            "characters": characters,
            "foreshadowing": [
                asdict(item)
                for item in memory.foreshadowing
                if item.status in ("planted", "active")
            ],
            "choices": [asdict(item) for item in memory.choices],
            "rolling_summary": memory.rolling_summary,
            "recent_scenes": [asdict(scene) for scene in recent_scenes],
            "older_scene_summaries": older_scene_summaries,
        }
        estimated_tokens = estimate_tokens(layers)
        while estimated_tokens > self.budget_tokens and older_scene_summaries:
            older_scene_summaries.pop()
            estimated_tokens = estimate_tokens(layers)
        while estimated_tokens > self.budget_tokens:
            unrelated_index = next(
                (
                    index
                    for index, character in enumerate(characters)
                    if character.get("related") is False
                ),
                None,
            )
            if unrelated_index is None:
                break
            characters.pop(unrelated_index)
            estimated_tokens = estimate_tokens(layers)
        rolling_words = memory.rolling_summary.split()
        while estimated_tokens > self.budget_tokens and rolling_words:
            rolling_words.pop(0)
            layers["rolling_summary"] = " ".join(rolling_words)
            estimated_tokens = estimate_tokens(layers)
        if estimated_tokens > self.budget_tokens:
            raise ContextBudgetError(
                "mandatory context requires "
                f"{estimated_tokens} estimated tokens but budget is {self.budget_tokens}"
            )
        return BuiltContext(
            layers=layers,
            estimated_tokens=estimated_tokens,
            budget_tokens=self.budget_tokens,
        )

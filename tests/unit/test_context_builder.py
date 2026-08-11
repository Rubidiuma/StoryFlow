"""Unit tests for deterministic, budgeted story context construction."""

from copy import deepcopy

import pytest

from storyflow.services.context_builder import (
    ChoiceMemory,
    ContextBudgetError,
    ContextBuilder,
    ForeshadowingMemory,
    LayeredMemory,
    SceneMemory,
    estimate_tokens,
)


def test_token_estimation_uses_a_deterministic_character_formula():
    """Changing serialization order or rounding would change the public estimate."""
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens([]) == 0
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens({"a": ""}) == 2
    assert estimate_tokens({"b": "two", "a": "one"}) == estimate_tokens(
        {"a": "one", "b": "two"}
    )


def test_layers_keep_recent_full_scenes_and_only_summarize_older_scenes():
    """Selecting the wrong scene boundary would leak old prose or lose recent prose."""
    memory = LayeredMemory(
        fixed_memory={"world": "Moon cities"},
        current_arc={"goal": "Find the observatory"},
        characters=[{"name": "Mira"}],
        foreshadowing=[
            ForeshadowingMemory(
                id="f-active", description="A cracked lens", status="active"
            ),
            ForeshadowingMemory(
                id="f-resolved", description="The false map", status="resolved"
            ),
            ForeshadowingMemory(
                id="f-planted", description="A silent bell", status="planted"
            ),
            ForeshadowingMemory(
                id="f-abandoned", description="A red herring", status="abandoned"
            ),
        ],
        choices=[],
        rolling_summary="Mira crossed the salt plain.",
        scenes=[
            SceneMemory(sequence=3, content="third full", summary="third summary"),
            SceneMemory(sequence=1, content="first full", summary="first summary"),
            SceneMemory(sequence=4, content="fourth full", summary="fourth summary"),
            SceneMemory(sequence=2, content="second full", summary="second summary"),
        ],
    )

    result = ContextBuilder(budget_tokens=1_000).build(memory)

    assert list(result.layers) == [
        "fixed_memory",
        "current_arc",
        "characters",
        "foreshadowing",
        "choices",
        "rolling_summary",
        "recent_scenes",
        "older_scene_summaries",
    ]
    assert result.layers["recent_scenes"] == [
        {"sequence": 3, "content": "third full", "summary": "third summary"},
        {"sequence": 4, "content": "fourth full", "summary": "fourth summary"},
    ]
    assert result.layers["older_scene_summaries"] == [
        {"sequence": 2, "summary": "second summary"},
        {"sequence": 1, "summary": "first summary"},
    ]
    assert result.layers["foreshadowing"] == [
        {"id": "f-active", "description": "A cracked lens", "status": "active"},
        {"id": "f-planted", "description": "A silent bell", "status": "planted"},
    ]
    assert 0 < result.estimated_tokens <= result.budget_tokens == 1_000


def test_thirty_scenes_are_trimmed_below_budget_without_losing_mandatory_layers():
    """Unbounded old summaries must not exceed the configured generation budget."""
    memory = LayeredMemory(
        fixed_memory={"world": "No one can breathe beyond the glass"},
        current_arc={"goal": "Repair the eastern seal"},
        characters=[{"name": "Mira", "role": "engineer"}],
        foreshadowing=[
            ForeshadowingMemory(
                id="f1", description="The seal hums at midnight", status="active"
            ),
            ForeshadowingMemory(
                id="f2", description="The spare key was used", status="resolved"
            ),
        ],
        choices=[
            ChoiceMemory(
                text="Trust the archivist",
                effects={"relationship": "archivist+1"},
                result_summary="Mira shared the map.",
            )
        ],
        rolling_summary="The expedition crossed every western district before the seal failed.",
        scenes=[
            SceneMemory(
                sequence=sequence,
                content=f"scene {sequence} " + "x" * 80,
                summary=f"summary {sequence}",
            )
            for sequence in range(1, 31)
        ],
    )
    before = deepcopy(memory)

    result = ContextBuilder(budget_tokens=250).build(memory)

    assert result.estimated_tokens <= 250
    assert result.budget_tokens == 250
    assert result.layers["fixed_memory"] == {
        "world": "No one can breathe beyond the glass"
    }
    assert result.layers["current_arc"] == {"goal": "Repair the eastern seal"}
    assert result.layers["choices"] == [
        {
            "text": "Trust the archivist",
            "effects": {"relationship": "archivist+1"},
            "result_summary": "Mira shared the map.",
        }
    ]
    assert result.layers["foreshadowing"] == [
        {
            "id": "f1",
            "description": "The seal hums at midnight",
            "status": "active",
        }
    ]
    assert result.layers["recent_scenes"] == [
        {"sequence": 29, "content": "scene 29 " + "x" * 80, "summary": "summary 29"},
        {"sequence": 30, "content": "scene 30 " + "x" * 80, "summary": "summary 30"},
    ]
    assert memory == before


def test_budget_pressure_trims_old_summaries_then_unrelated_characters_then_whole_words():
    """Changing priority or slicing summary text would discard higher-value context first."""
    memory = LayeredMemory(
        fixed_memory={"world": "x" * 20},
        current_arc={"goal": "y" * 20},
        characters=[
            {"name": "old", "detail": "o" * 80, "related": False},
            {"name": "new", "detail": "n" * 80},
        ],
        foreshadowing=[],
        choices=[],
        rolling_summary="alpha bravo charlie delta echo foxtrot golf hotel india juliet",
        scenes=[
            SceneMemory(sequence=1, content="first", summary="w" * 80),
            SceneMemory(sequence=2, content="second", summary="z" * 80),
            SceneMemory(sequence=3, content="third", summary="s3"),
            SceneMemory(sequence=4, content="fourth", summary="s4"),
        ],
    )

    summaries_trimmed = ContextBuilder(budget_tokens=150).build(memory)
    unrelated_character_trimmed = ContextBuilder(budget_tokens=119).build(memory)
    summary_words_trimmed = ContextBuilder(budget_tokens=116).build(memory)

    assert summaries_trimmed.layers["older_scene_summaries"] == []
    assert summaries_trimmed.layers["characters"] == [
        {"name": "old", "detail": "o" * 80, "related": False},
        {"name": "new", "detail": "n" * 80},
    ]
    assert summaries_trimmed.layers["rolling_summary"] == (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    )
    assert unrelated_character_trimmed.layers["older_scene_summaries"] == []
    assert unrelated_character_trimmed.layers["characters"] == [
        {"name": "new", "detail": "n" * 80}
    ]
    assert unrelated_character_trimmed.layers["rolling_summary"] == (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    )
    assert summary_words_trimmed.layers["characters"] == [
        {"name": "new", "detail": "n" * 80}
    ]
    assert summary_words_trimmed.layers["rolling_summary"] == (
        "charlie delta echo foxtrot golf hotel india juliet"
    )
    assert summary_words_trimmed.estimated_tokens == 116
    with pytest.raises(ContextBudgetError, match="mandatory context"):
        ContextBuilder(budget_tokens=102).build(memory)


def test_budget_smaller_than_untrimmable_layers_raises_an_explicit_error():
    """Returning an oversized mandatory context would make budget accounting dishonest."""
    memory = LayeredMemory(
        fixed_memory={"world": "The city floats above an endless storm."},
        current_arc={"goal": "Reach the final anchor."},
        characters=[{"name": "old observer"}],
        foreshadowing=[
            ForeshadowingMemory(
                id="anchor", description="The anchor is already cracked.", status="planted"
            )
        ],
        choices=[ChoiceMemory(text="Climb", effects={"route": "spire"})],
        rolling_summary="Long ago the crew crossed the lower rings.",
        scenes=[
            SceneMemory(sequence=1, content="The crew reaches the spire.", summary="At spire")
        ],
    )

    with pytest.raises(ContextBudgetError, match="mandatory context"):
        ContextBuilder(budget_tokens=1).build(memory)

"""Unit tests for domain models and validation."""
import pytest
from pydantic import ValidationError

from storyflow.domain.models import (
    ChoiceOption,
    ChoicePoint,
    StoryConfig,
)


class TestStoryConfig:
    """Test story configuration validation."""

    def test_valid_story_config(self):
        """A valid story config should pass validation."""
        config = StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="A fantasy kingdom",
            protagonist_desc="A brave hero",
            style="epic",
            choice_frequency="中",
        )
        assert config.genre == "fantasy"

    def test_story_config_total_length_limit(self):
        """Total input length should not exceed 6000 characters per SPEC §5.1."""
        long_text = "x" * 2000
        with pytest.raises(ValidationError):
            StoryConfig(
                genre=long_text,
                structure=long_text,
                world_background=long_text,
                protagonist_desc=long_text,
                style=long_text,
                choice_frequency="medium",
            )

    def test_choice_frequency_enum(self):
        """choice_frequency should only accept: 少, 中, 多."""
        valid_frequencies = ["少", "中", "多"]
        for freq in valid_frequencies:
            config = StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="World",
                protagonist_desc="Hero",
                style="epic",
                choice_frequency=freq,
            )
            # Enum values are stored as their string representation
            assert config.choice_frequency.value == freq

        with pytest.raises(ValidationError):
            StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="World",
                protagonist_desc="Hero",
                style="epic",
                choice_frequency="invalid",
            )


class TestChoiceOption:
    """Test choice option validation."""

    def test_valid_choice_option(self):
        """Valid choice option should pass validation."""
        option = ChoiceOption(
            text="Go left",
            effects={
                "route_change": "enter_cave",
                "character_state": {"name": "hero", "location": "cave"},
            },
        )
        assert option.text == "Go left"
        assert option.effects is not None

    def test_choice_option_text_required(self):
        """Choice option text is required."""
        with pytest.raises(ValidationError):
            ChoiceOption(text="", effects={"route_change": "left"})

    def test_choice_option_effects_required(self):
        """Choice option effects must be non-empty."""
        with pytest.raises(ValidationError):
            ChoiceOption(text="Go left", effects={})

    def test_choice_option_effects_structure(self):
        """Choice option effects should be a dict with meaningful keys."""
        option = ChoiceOption(
            text="Go left",
            effects={"route_change": "cave", "information_state": "learned_secret"},
        )
        assert "route_change" in option.effects or "information_state" in option.effects


class TestChoicePoint:
    """Test choice point validation."""

    def test_valid_choice_point_with_three_options(self):
        """Choice point must have exactly 3 unique options per SPEC §5.3."""
        options = [
            ChoiceOption(text="Option A", effects={"route": "a"}),
            ChoiceOption(text="Option B", effects={"route": "b"}),
            ChoiceOption(text="Option C", effects={"route": "c"}),
        ]
        choice_point = ChoicePoint(
            type="decision",
            reason="character_conflict",
            options=options,
        )
        assert len(choice_point.options) == 3

    def test_choice_point_must_have_three_options(self):
        """Choice point must have exactly 3 options."""
        with pytest.raises(ValidationError):
            options = [
                ChoiceOption(text="Option A", effects={"route": "a"}),
                ChoiceOption(text="Option B", effects={"route": "b"}),
            ]
            ChoicePoint(
                type="decision",
                reason="conflict",
                options=options,
            )

    def test_choice_point_options_must_be_unique(self):
        """Choice point options must have unique text."""
        with pytest.raises(ValidationError):
            options = [
                ChoiceOption(text="Same text", effects={"route": "a"}),
                ChoiceOption(text="Same text", effects={"route": "b"}),
                ChoiceOption(text="Other", effects={"route": "c"}),
            ]
            ChoicePoint(
                type="decision",
                reason="conflict",
                options=options,
            )

    def test_choice_point_reason_required(self):
        """Choice point reason should be non-empty."""
        with pytest.raises(ValidationError):
            options = [
                ChoiceOption(text="Option A", effects={"route": "a"}),
                ChoiceOption(text="Option B", effects={"route": "b"}),
                ChoiceOption(text="Option C", effects={"route": "c"}),
            ]
            ChoicePoint(
                type="decision",
                reason="",
                options=options,
            )


class TestCustomAction:
    """Test custom action validation per SPEC §5.4."""

    def test_valid_custom_action_length(self):
        """Custom action must be 1-300 characters per SPEC §5.4."""
        from storyflow.domain.models import CustomAction

        action = CustomAction(text="I try to open the door")
        assert len(action.text) >= 1 and len(action.text) <= 300

    def test_custom_action_too_short(self):
        """Custom action cannot be empty."""
        from storyflow.domain.models import CustomAction

        with pytest.raises(ValidationError):
            CustomAction(text="")

    def test_custom_action_too_long(self):
        """Custom action cannot exceed 300 characters."""
        from storyflow.domain.models import CustomAction

        long_text = "x" * 301
        with pytest.raises(ValidationError):
            CustomAction(text=long_text)

    def test_custom_action_boundary_300_chars(self):
        """Custom action with exactly 300 characters should be valid."""
        from storyflow.domain.models import CustomAction

        text_300 = "x" * 300
        action = CustomAction(text=text_300)
        assert len(action.text) == 300

    def test_custom_action_single_char(self):
        """Custom action with single character should be valid."""
        from storyflow.domain.models import CustomAction

        action = CustomAction(text="I")
        assert len(action.text) == 1

"""Unit tests for domain models and validation."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from storyflow import domain
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
        """Total input above 6000 characters is rejected when each field is valid alone."""
        with pytest.raises(ValidationError):
            StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="w" * 2000,
                protagonist_desc="p" * 2000,
                style="s" * 500,
                required_elements="r" * 1000,
                forbidden_elements="f" * 484,
                ending_tendency="e",
                choice_frequency="中",
            )

    def test_story_config_allows_exactly_6000_characters_across_user_text_fields(self):
        """The documented cumulative limit includes its 6000-character boundary."""
        config = StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="w" * 2000,
            protagonist_desc="p" * 2000,
            style="s" * 500,
            required_elements="r" * 1000,
            forbidden_elements="f" * 484,
            choice_frequency="中",
        )

        assert config.forbidden_elements == "f" * 484

    def test_story_config_represents_important_supporting_characters(self):
        """The configuration retains the optional supporting-character description."""
        config = StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="A fantasy kingdom",
            protagonist_desc="A brave hero",
            important_supporting_characters="An archivist who remembers every broken oath.",
            style="epic",
            choice_frequency="中",
        )

        assert config.important_supporting_characters == (
            "An archivist who remembers every broken oath."
        )

    def test_important_supporting_characters_has_an_individual_1000_character_limit(self):
        """The supporting-character description cannot exceed its own field budget."""
        with pytest.raises(ValidationError):
            StoryConfig(
                genre="fantasy",
                structure="three_act",
                world_background="A fantasy kingdom",
                protagonist_desc="A brave hero",
                important_supporting_characters="c" * 1001,
                style="epic",
                choice_frequency="中",
            )

    def test_story_config_cumulative_boundary_includes_supporting_characters(self):
        """Supporting-character text consumes the documented cumulative text budget."""
        values = {
            "genre": "fantasy",
            "structure": "three_act",
            "world_background": "w" * 2000,
            "protagonist_desc": "p" * 2000,
            "important_supporting_characters": "c" * 1000,
            "style": "s" * 500,
            "required_elements": "r" * 484,
            "choice_frequency": "中",
        }

        config = StoryConfig(**values)
        assert config.important_supporting_characters == "c" * 1000
        with pytest.raises(ValidationError, match="6,000"):  # Now uses Chinese format
            StoryConfig(**values, ending_tendency="e")

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


class TestStory:
    """Test aggregate-level story validation."""

    def test_story_rejects_choice_frequency_that_differs_from_canonical_config(self):
        """The compatibility field cannot diverge from the canonical configuration value."""
        config = StoryConfig(
            genre="fantasy",
            structure="three_act",
            world_background="A fantasy kingdom",
            protagonist_desc="A brave hero",
            style="epic",
            choice_frequency="中",
        )

        with pytest.raises(ValidationError, match="config.choice_frequency"):
            domain.Story(
                session_id="session-1",
                choice_frequency="少",
                config=config,
            )


class TestScenePlan:
    """Test the structured scene plan contract from SPEC §5.2."""

    def test_public_scene_plan_defaults_to_a_complete_scene_without_a_choice(self):
        """A plan exposes the required structure and its documented defaults."""
        plan = domain.ScenePlan(
            goal="Recover the lost map",
            conflict="The guard refuses entry",
            beats=["Approach the gate", "Offer a bargain"],
        )

        assert plan.goal == "Recover the lost map"
        assert plan.conflict == "The guard refuses entry"
        assert plan.beats == ["Approach the gate", "Offer a bargain"]
        assert plan.choice_suggestion is None
        assert plan.scene_complete is True

    @pytest.mark.parametrize(
        ("goal", "conflict", "beats"),
        [
            ("   ", "The guard refuses entry", ["Approach the gate"]),
            ("Recover the map", "   ", ["Approach the gate"]),
            ("Recover the map", "The guard refuses entry", []),
            ("Recover the map", "The guard refuses entry", ["   "]),
        ],
    )
    def test_scene_plan_rejects_blank_required_text_and_empty_beats(
        self, goal, conflict, beats
    ):
        """Scene planning cannot proceed with absent structure or whitespace-only content."""
        with pytest.raises(ValidationError):
            domain.ScenePlan(goal=goal, conflict=conflict, beats=beats)


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

    def test_choice_option_text_cannot_be_only_whitespace(self):
        """A visibly empty option cannot be presented to the reader."""
        with pytest.raises(ValidationError):
            ChoiceOption(text="   ", effects={"route_change": "left"})

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


class TestSpecRelationships:
    """Test relationship fields explicitly listed in SPEC §8."""

    def test_relationship_fields_support_unbound_llm_choice_options(self):
        """Nested choices may be unbound until their scene is persisted."""
        story_id = uuid4()
        branch_id = uuid4()
        option = domain.ChoiceOption(text="Enter the gate", effects={"route": "gate"})
        choice_point = domain.ChoicePoint(
            type="decision",
            reason="The guard demands a response",
            options=[
                option,
                domain.ChoiceOption(text="Negotiate", effects={"route": "deal"}),
                domain.ChoiceOption(text="Leave", effects={"route": "road"}),
            ],
        )
        character = domain.CharacterState(
            story_id=story_id,
            branch_id=branch_id,
            name="Ari",
            role="protagonist",
        )

        assert character.branch_id == branch_id
        assert choice_point.segment_id is None
        assert option.id is not None
        assert option.choice_point_id is None


class TestStorySegment:
    """Test segment lineage validation."""

    def test_story_segment_cannot_name_itself_as_parent(self):
        """A segment's immediate parent cannot be its own identifier."""
        segment_id = uuid4()

        with pytest.raises(ValidationError, match="own parent"):
            domain.StorySegment(
                id=segment_id,
                story_id=uuid4(),
                branch_id=uuid4(),
                parent_segment_id=segment_id,
                sequence=1,
                content="A path folds back onto itself.",
                generation_key="self-parent",
            )


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

    def test_choice_point_normalizes_option_text_before_checking_uniqueness(self):
        """Cosmetic case and surrounding whitespace cannot create duplicate choices."""
        with pytest.raises(ValidationError):
            ChoicePoint(
                type="decision",
                reason="conflict",
                options=[
                    ChoiceOption(text="Take the bridge", effects={"route": "bridge"}),
                    ChoiceOption(text="  take THE bridge  ", effects={"route": "bridge"}),
                    ChoiceOption(text="Search the river", effects={"route": "river"}),
                ],
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

    def test_choice_point_reason_cannot_be_only_whitespace(self):
        """A choice point must describe a real narrative reason."""
        with pytest.raises(ValidationError):
            ChoicePoint(
                type="decision",
                reason="   ",
                options=[
                    ChoiceOption(text="Option A", effects={"route": "a"}),
                    ChoiceOption(text="Option B", effects={"route": "b"}),
                    ChoiceOption(text="Option C", effects={"route": "c"}),
                ],
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

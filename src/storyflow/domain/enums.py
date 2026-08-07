"""Domain enumerations for StoryFlow."""
from enum import Enum


class StoryStatus(str, Enum):
    """Story execution status per SPEC §6.

    - DRAFT: Story bible not yet confirmed
    - IDLE: Ready to start or continue generation
    - PLANNING: Generating scene plan
    - STREAMING: Streaming story text
    - COMMITTING: Committing scene and memory changes
    - WAITING_CHOICE: Waiting for user choice, generation disabled
    - PAUSED: User paused or safety limit reached
    - ERROR: Unrecoverable error, awaiting retry
    """

    DRAFT = "DRAFT"
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    STREAMING = "STREAMING"
    COMMITTING = "COMMITTING"
    WAITING_CHOICE = "WAITING_CHOICE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class ChoiceFrequency(str, Enum):
    """User choice frequency per SPEC §5.2.

    - 少 (Few): Usually every 4-5 scenes
    - 中 (Medium): Usually every 2-3 scenes
    - 多 (Many): Usually every 1-2 scenes
    """

    FEW = "少"
    MEDIUM = "中"
    MANY = "多"


class Genre(str, Enum):
    """Story genre per SPEC §5.1."""

    FANTASY = "fantasy"
    SCIFI = "scifi"
    MYSTERY = "mystery"
    EMOTION = "emotion"
    OPEN = "open"


class StoryStructure(str, Enum):
    """Story structure template per SPEC §5.1."""

    THREE_ACT = "three_act"
    HERO_JOURNEY = "hero_journey"
    MYSTERY_INVESTIGATION = "mystery_investigation"
    EMOTIONAL_GROWTH = "emotional_growth"
    OPEN_SERIES = "open_series"


class ChoiceType(str, Enum):
    """Choice point type."""

    DECISION = "decision"
    ACTION = "action"
    DIALOGUE = "dialogue"

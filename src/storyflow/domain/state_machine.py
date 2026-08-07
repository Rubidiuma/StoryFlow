"""Story state machine implementation per SPEC §6."""
from typing import ClassVar

from storyflow.domain.enums import StoryStatus


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""



class StoryStateMachine:
    """Manages valid story state transitions per SPEC §6.

    Constraints:
    - WAITING_CHOICE cannot directly transition to PLANNING
    - DRAFT cannot directly transition to PLANNING (must go through IDLE)
    - All transitions are logged for debugging (implemented in service layer)
    """

    # Define valid transitions as a mapping: from_state -> set of allowed_to_states
    VALID_TRANSITIONS: ClassVar[dict[StoryStatus, set[StoryStatus]]] = {
        StoryStatus.DRAFT: {StoryStatus.IDLE},
        StoryStatus.IDLE: {StoryStatus.PLANNING, StoryStatus.PAUSED, StoryStatus.ERROR},
        StoryStatus.PLANNING: {
            StoryStatus.STREAMING,
            StoryStatus.ERROR,
            StoryStatus.PAUSED,
        },
        StoryStatus.STREAMING: {
            StoryStatus.COMMITTING,
            StoryStatus.ERROR,
            StoryStatus.PAUSED,
        },
        StoryStatus.COMMITTING: {
            StoryStatus.IDLE,
            StoryStatus.WAITING_CHOICE,
            StoryStatus.ERROR,
            StoryStatus.PAUSED,
        },
        StoryStatus.WAITING_CHOICE: {
            StoryStatus.IDLE,
            StoryStatus.PAUSED,
            StoryStatus.ERROR,
        },
        StoryStatus.PAUSED: {
            StoryStatus.IDLE,
            StoryStatus.ERROR,
        },
        StoryStatus.ERROR: {
            StoryStatus.IDLE,
            StoryStatus.PAUSED,
        },
    }

    def __init__(self, initial_state: StoryStatus = StoryStatus.DRAFT):
        """Initialize state machine with initial state."""
        self.current_state = initial_state

    def transition(self, target_state: StoryStatus) -> None:
        """Transition to target state if valid.

        Args:
            target_state: The desired target state.

        Raises:
            InvalidTransitionError: If transition is not allowed.
        """
        if target_state not in self.VALID_TRANSITIONS.get(
            self.current_state, set()
        ):
            raise InvalidTransitionError(
                f"Cannot transition from {self.current_state} to {target_state}"
            )

        self.current_state = target_state

    def can_transition_to(self, target_state: StoryStatus) -> bool:
        """Check if transition is allowed without performing it.

        Args:
            target_state: The desired target state.

        Returns:
            True if transition is valid, False otherwise.
        """
        return target_state in self.VALID_TRANSITIONS.get(self.current_state, set())

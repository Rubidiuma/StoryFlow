"""Story state machine implementation per SPEC §6."""
from collections.abc import Mapping
from types import MappingProxyType
from typing import ClassVar

from storyflow.domain.enums import StoryStatus


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


_VALID_TRANSITIONS: Mapping[StoryStatus, frozenset[StoryStatus]] = MappingProxyType(
    {
        StoryStatus.DRAFT: frozenset({StoryStatus.IDLE}),
        StoryStatus.IDLE: frozenset(
            {StoryStatus.PLANNING, StoryStatus.PAUSED, StoryStatus.ERROR}
        ),
        StoryStatus.PLANNING: frozenset(
            {StoryStatus.STREAMING, StoryStatus.ERROR, StoryStatus.PAUSED}
        ),
        StoryStatus.STREAMING: frozenset(
            {StoryStatus.COMMITTING, StoryStatus.ERROR, StoryStatus.PAUSED}
        ),
        StoryStatus.COMMITTING: frozenset(
            {
                StoryStatus.IDLE,
                StoryStatus.WAITING_CHOICE,
                StoryStatus.ERROR,
                StoryStatus.PAUSED,
            }
        ),
        StoryStatus.WAITING_CHOICE: frozenset(
            {StoryStatus.IDLE, StoryStatus.PAUSED, StoryStatus.ERROR}
        ),
        StoryStatus.PAUSED: frozenset({StoryStatus.IDLE, StoryStatus.ERROR}),
        StoryStatus.ERROR: frozenset({StoryStatus.IDLE, StoryStatus.PAUSED}),
    }
)


def transition(current: StoryStatus, target: StoryStatus) -> StoryStatus:
    """Return a legal target status without changing external state."""
    if target not in _VALID_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"Cannot transition from {current} to {target}")
    return target


class StoryStateMachine:
    """Manages valid story state transitions per SPEC §6.

    Constraints:
    - WAITING_CHOICE cannot directly transition to PLANNING
    - DRAFT cannot directly transition to PLANNING (must go through IDLE)
    - All transitions are logged for debugging (implemented in service layer)
    """

    VALID_TRANSITIONS: ClassVar[Mapping[StoryStatus, frozenset[StoryStatus]]] = _VALID_TRANSITIONS

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
        self.current_state = transition(self.current_state, target_state)

    def can_transition_to(self, target_state: StoryStatus) -> bool:
        """Check if transition is allowed without performing it.

        Args:
            target_state: The desired target state.

        Returns:
            True if transition is valid, False otherwise.
        """
        try:
            transition(self.current_state, target_state)
        except InvalidTransitionError:
            return False
        return True

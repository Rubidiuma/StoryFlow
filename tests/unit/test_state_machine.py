"""Unit tests for story state machine transitions."""
import pytest

from storyflow import domain
from storyflow.domain.enums import StoryStatus
from storyflow.domain.state_machine import InvalidTransitionError, StoryStateMachine


class TestStateTransitions:
    """Test valid and invalid state transitions."""

    def test_public_transition_returns_target_without_mutating_a_state_machine(self):
        """The pure transition function returns a legal target without external mutation."""
        machine = StoryStateMachine(initial_state=StoryStatus.DRAFT)

        result = domain.transition(StoryStatus.DRAFT, StoryStatus.IDLE)

        assert result == StoryStatus.IDLE
        assert machine.current_state == StoryStatus.DRAFT

    def test_public_transition_rejects_illegal_targets(self):
        """The pure transition function enforces the same legal transition table."""
        with pytest.raises(domain.InvalidTransitionError):
            domain.transition(StoryStatus.DRAFT, StoryStatus.PLANNING)

    def test_draft_to_planning_rejected(self):
        """DRAFT -> PLANNING should be rejected; must confirm to IDLE first."""
        machine = StoryStateMachine(initial_state=StoryStatus.DRAFT)

        with pytest.raises(InvalidTransitionError):
            machine.transition(StoryStatus.PLANNING)

    def test_draft_to_idle_via_confirmation(self):
        """DRAFT -> IDLE should be allowed (confirmation of story bible)."""
        machine = StoryStateMachine(initial_state=StoryStatus.DRAFT)

        machine.transition(StoryStatus.IDLE)
        assert machine.current_state == StoryStatus.IDLE

    def test_idle_to_planning_allowed(self):
        """IDLE -> PLANNING should be allowed."""
        machine = StoryStateMachine(initial_state=StoryStatus.IDLE)

        machine.transition(StoryStatus.PLANNING)
        assert machine.current_state == StoryStatus.PLANNING

    def test_planning_to_streaming_allowed(self):
        """PLANNING -> STREAMING should be allowed."""
        machine = StoryStateMachine(initial_state=StoryStatus.PLANNING)

        machine.transition(StoryStatus.STREAMING)
        assert machine.current_state == StoryStatus.STREAMING

    def test_streaming_to_committing_allowed(self):
        """STREAMING -> COMMITTING should be allowed."""
        machine = StoryStateMachine(initial_state=StoryStatus.STREAMING)

        machine.transition(StoryStatus.COMMITTING)
        assert machine.current_state == StoryStatus.COMMITTING

    def test_committing_to_idle_allowed(self):
        """COMMITTING -> IDLE should be allowed (no choices)."""
        machine = StoryStateMachine(initial_state=StoryStatus.COMMITTING)

        machine.transition(StoryStatus.IDLE)
        assert machine.current_state == StoryStatus.IDLE

    def test_committing_to_waiting_choice_allowed(self):
        """COMMITTING -> WAITING_CHOICE should be allowed (with choices)."""
        machine = StoryStateMachine(initial_state=StoryStatus.COMMITTING)

        machine.transition(StoryStatus.WAITING_CHOICE)
        assert machine.current_state == StoryStatus.WAITING_CHOICE

    def test_waiting_choice_to_planning_rejected(self):
        """WAITING_CHOICE -> PLANNING should be rejected."""
        machine = StoryStateMachine(initial_state=StoryStatus.WAITING_CHOICE)

        with pytest.raises(InvalidTransitionError):
            machine.transition(StoryStatus.PLANNING)

    def test_waiting_choice_to_idle_allowed(self):
        """WAITING_CHOICE -> IDLE should be allowed (after choice submission)."""
        machine = StoryStateMachine(initial_state=StoryStatus.WAITING_CHOICE)

        machine.transition(StoryStatus.IDLE)
        assert machine.current_state == StoryStatus.IDLE

    def test_paused_to_idle_allowed(self):
        """PAUSED -> IDLE should be allowed (resume reading)."""
        machine = StoryStateMachine(initial_state=StoryStatus.PAUSED)

        machine.transition(StoryStatus.IDLE)
        assert machine.current_state == StoryStatus.IDLE

    def test_any_state_to_paused_allowed(self):
        """Any state should be able to transition to PAUSED."""
        for state in [StoryStatus.IDLE, StoryStatus.PLANNING, StoryStatus.STREAMING]:
            machine = StoryStateMachine(initial_state=state)
            machine.transition(StoryStatus.PAUSED)
            assert machine.current_state == StoryStatus.PAUSED

    def test_any_state_to_error_allowed(self):
        """Any state should be able to transition to ERROR."""
        for state in [StoryStatus.IDLE, StoryStatus.PLANNING, StoryStatus.STREAMING]:
            machine = StoryStateMachine(initial_state=state)
            machine.transition(StoryStatus.ERROR)
            assert machine.current_state == StoryStatus.ERROR

    def test_invalid_transition_error_message(self):
        """InvalidTransitionError should provide clear context."""
        machine = StoryStateMachine(initial_state=StoryStatus.DRAFT)

        with pytest.raises(InvalidTransitionError) as exc_info:
            machine.transition(StoryStatus.PLANNING)

        assert "DRAFT" in str(exc_info.value)
        assert "PLANNING" in str(exc_info.value)

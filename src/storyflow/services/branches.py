from __future__ import annotations

"""Branch creation and fork management service."""

from uuid import UUID

from storyflow.db.repositories import ChoiceNotFoundError, ChoiceNotSelectedError, StoryRepository
from storyflow.domain.models import Branch, MemorySnapshot

__all__ = ["BranchService"]


class BranchService:
    """Orchestrate branch fork operations over the story repository."""

    def __init__(self, repository: StoryRepository) -> None:
        self.repository = repository

    def create_fork(
        self,
        choice_id: UUID,
        branch_name: str = "Branch",
    ) -> tuple[Branch, MemorySnapshot]:
        """Create a fork branch at a selected choice point.

        Raises ChoiceNotFoundError if the choice does not exist.
        Raises ChoiceNotSelectedError if the choice has not been made yet.
        """
        return self.repository.fork_at_choice(choice_id, branch_name)

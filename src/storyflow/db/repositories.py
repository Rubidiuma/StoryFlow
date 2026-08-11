from __future__ import annotations

"""Persistence operations for StoryFlow's Pydantic domain models."""
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from storyflow.db.database import Database
from storyflow.domain.enums import StoryStatus
from storyflow.domain.models import (
    Branch,
    CharacterState,
    ChoicePoint,
    GenerationEvent,
    MemorySnapshot,
    Story,
    StoryArc,
    StoryBible,
    StorySegment,
)
from storyflow.domain.state_machine import InvalidTransitionError, transition
from storyflow.services.memory import MemoryService


class StoryNotFoundError(LookupError):
    """The requested story does not exist."""


class IncompleteBibleBundleError(ValueError):
    """A story is missing at least one record required for confirmation."""


class IllegalStoryStateError(ValueError):
    """The current story state cannot be confirmed."""


class ChoiceNotFoundError(LookupError):
    """The requested choice point does not exist."""


class InvalidChoiceStateError(ValueError):
    """A choice cannot be submitted from the current story or branch state."""


class ChoiceVersionConflictError(ValueError):
    """A choice submission names an obsolete or future version."""


class ChoiceOptionNotFoundError(ValueError):
    """A preset submission names no option from this choice point."""


class InvalidChoiceEffectsError(ValueError):
    """Normalized choice effects cannot be applied to current memory."""


class ChoiceNotSelectedError(ValueError):
    """A fork cannot be created from a choice that has not been selected."""


@dataclass(frozen=True, slots=True)
class ChoiceSubmissionResult:
    """Persisted outcome of one accepted or exactly replayed submission."""

    status: Literal["success", "duplicate"]
    choice: ChoicePoint
    story: Story


def _json(model: BaseModel) -> str:
    """Serialize a Pydantic model using its JSON-native representation."""
    return model.model_dump_json()


class StoryRepository:
    """Read and write the relational records that compose a story."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_story(self, story: Story) -> Story:
        if story.current_branch_id is not None:
            raise ValueError(
                "a story must be created without a current branch; use set_current_branch"
            )
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO stories (id, session_id, current_branch_id, payload) VALUES (?, ?, ?, ?)",
                (str(story.id), story.session_id, _optional_id(story.current_branch_id), _json(story)),
            )
        return story

    def get_story(self, story_id: UUID) -> Story | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM stories WHERE id = ?", (str(story_id),)
            ).fetchone()
        return Story.model_validate_json(row["payload"]) if row else None

    def list_stories(self) -> list[Story]:
        """Return the bookshelf ordered from most recently updated to oldest."""
        with self.database.read() as connection:
            rows = connection.execute("SELECT payload FROM stories").fetchall()
        stories = [Story.model_validate_json(row["payload"]) for row in rows]
        return sorted(stories, key=lambda story: story.updated_at, reverse=True)

    def recover_interrupted_generations(self) -> list[Story]:
        """Atomically mark persisted in-flight stories as interrupted once."""
        active_statuses = {
            StoryStatus.PLANNING,
            StoryStatus.STREAMING,
            StoryStatus.COMMITTING,
        }
        recovered: list[Story] = []
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT current_branch_id, payload FROM stories ORDER BY rowid"
            ).fetchall()
            for row in rows:
                story = Story.model_validate_json(row["payload"])
                if story.status not in active_statuses:
                    continue
                current_branch_id = row["current_branch_id"]
                event_branch_id: UUID | None = None
                if (
                    current_branch_id is not None
                    and story.current_branch_id is not None
                    and current_branch_id == str(story.current_branch_id)
                ):
                    branch_exists = connection.execute(
                        "SELECT 1 FROM branches WHERE id = ? AND story_id = ?",
                        (current_branch_id, str(story.id)),
                    ).fetchone()
                    if branch_exists is not None:
                        event_branch_id = story.current_branch_id
                original_status = story.status
                recovered_story = story.model_copy(
                    update={
                        "status": transition(original_status, StoryStatus.ERROR),
                        "version": story.version + 1,
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                )
                event = GenerationEvent(
                    story_id=story.id,
                    branch_id=event_branch_id,
                    event_type="error",
                    request_id=f"startup-recovery:{story.id}:{story.version}",
                    duration_ms=0,
                    input_token_estimate=0,
                    output_size=0,
                    error_code="generation_interrupted",
                    state_sequence=[original_status, StoryStatus.ERROR],
                )
                connection.execute(
                    "UPDATE stories SET payload = ? WHERE id = ?",
                    (_json(recovered_story), str(story.id)),
                )
                connection.execute(
                    """
                    INSERT INTO generation_events (id, story_id, branch_id, request_id, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.id),
                        str(event.story_id),
                        _optional_id(event.branch_id),
                        event.request_id,
                        _json(event),
                    ),
                )
                recovered.append(recovered_story)
        return recovered

    def set_current_branch(self, story_id: UUID, branch_id: UUID) -> Story:
        """Atomically select a branch that belongs to the story in both storage forms."""
        with self.database.transaction() as connection:
            story_row = connection.execute(
                "SELECT payload FROM stories WHERE id = ?", (str(story_id),)
            ).fetchone()
            if story_row is None:
                raise ValueError("story does not exist")
            branch_row = connection.execute(
                "SELECT story_id FROM branches WHERE id = ?", (str(branch_id),)
            ).fetchone()
            if branch_row is None:
                raise ValueError("current branch does not exist")
            if branch_row["story_id"] != str(story_id):
                raise ValueError("current branch must belong to the same story")
            story = Story.model_validate_json(story_row["payload"]).model_copy(
                update={"current_branch_id": branch_id}
            )
            connection.execute(
                "UPDATE stories SET current_branch_id = ?, payload = ? WHERE id = ?",
                (str(branch_id), _json(story), str(story_id)),
            )
        return story

    def save_bible(self, bible: StoryBible) -> StoryBible:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO story_bibles (story_id, payload) VALUES (?, ?)
                ON CONFLICT(story_id) DO UPDATE SET payload = excluded.payload
                """,
                (str(bible.story_id), _json(bible)),
            )
        return bible

    def get_bible(self, story_id: UUID) -> StoryBible | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM story_bibles WHERE story_id = ?", (str(story_id),)
            ).fetchone()
        return StoryBible.model_validate_json(row["payload"]) if row else None

    def replace_generated_bible_bundle(
        self,
        story: Story,
        bible: StoryBible,
        branch: Branch,
        characters: list[CharacterState],
        first_arc: StoryArc,
    ) -> Story:
        """Persist the records that compose one generated bundle."""
        if bible.story_id != story.id or branch.story_id != story.id:
            raise ValueError("Bible and branch must belong to the story")
        if branch.parent_branch_id is not None:
            raise ValueError("Initial Bible branch must be a root branch")
        if not characters:
            raise ValueError("Generated Bible bundle requires characters")
        if any(
            character.story_id != story.id or character.branch_id != branch.id
            for character in characters
        ):
            raise ValueError("Characters must belong to the generated story branch")
        if first_arc.story_id != story.id or first_arc.branch_id != branch.id:
            raise ValueError("First arc must belong to the generated story branch")

        with self.database.transaction() as connection:
            story_row = connection.execute(
                "SELECT payload FROM stories WHERE id = ?", (str(story.id),)
            ).fetchone()
            if story_row is None:
                raise ValueError("story does not exist")
            persisted_story = Story.model_validate_json(story_row["payload"])
            if (
                persisted_story.status != StoryStatus.DRAFT
                or persisted_story.version != story.version
            ):
                raise IllegalStoryStateError(
                    "story cannot generate a Bible from its current state or version"
                )
            unbound_story = persisted_story.model_copy(update={"current_branch_id": None})
            connection.execute(
                "UPDATE stories SET current_branch_id = NULL, payload = ? WHERE id = ?",
                (_json(unbound_story), str(story.id)),
            )
            connection.execute(
                "DELETE FROM character_states WHERE story_id = ?", (str(story.id),)
            )
            connection.execute("DELETE FROM story_arcs WHERE story_id = ?", (str(story.id),))
            connection.execute("DELETE FROM story_bibles WHERE story_id = ?", (str(story.id),))
            connection.execute("DELETE FROM branches WHERE story_id = ?", (str(story.id),))
            connection.execute(
                """
                INSERT INTO branches (
                    id, story_id, parent_branch_id, fork_choice_id, fork_segment_id,
                    head_segment_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(branch.id),
                    str(branch.story_id),
                    _optional_id(branch.parent_branch_id),
                    _optional_id(branch.fork_choice_id),
                    _optional_id(branch.fork_segment_id),
                    _optional_id(branch.head_segment_id),
                    _json(branch),
                ),
            )
            connection.execute(
                "INSERT INTO story_bibles (story_id, payload) VALUES (?, ?)",
                (str(bible.story_id), _json(bible)),
            )
            for character in characters:
                connection.execute(
                    """
                    INSERT INTO character_states (id, story_id, branch_id, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(character.id),
                        str(character.story_id),
                        str(character.branch_id),
                        _json(character),
                    ),
                )
            connection.execute(
                """
                INSERT INTO story_arcs (id, story_id, branch_id, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(first_arc.id),
                    str(first_arc.story_id),
                    str(first_arc.branch_id),
                    _json(first_arc),
                ),
            )
            updated_story = persisted_story.model_copy(update={"current_branch_id": branch.id})
            connection.execute(
                "UPDATE stories SET current_branch_id = ?, payload = ? WHERE id = ?",
                (str(branch.id), _json(updated_story), str(story.id)),
            )
        return updated_story

    def list_character_states(self, story_id: UUID) -> list[CharacterState]:
        """Return generated character state in persistence order for one story."""
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT payload FROM character_states WHERE story_id = ? ORDER BY rowid",
                (str(story_id),),
            ).fetchall()
        return [CharacterState.model_validate_json(row["payload"]) for row in rows]

    def list_story_arcs(self, story_id: UUID) -> list[StoryArc]:
        """Return generated arcs in persistence order for one story."""
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT payload FROM story_arcs WHERE story_id = ? ORDER BY rowid",
                (str(story_id),),
            ).fetchall()
        return [StoryArc.model_validate_json(row["payload"]) for row in rows]

    def confirm_bible(self, story_id: UUID) -> Story:
        """Atomically verify the generated bundle and transition its draft to IDLE."""
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT current_branch_id, payload FROM stories WHERE id = ?",
                (str(story_id),),
            ).fetchone()
            if row is None:
                raise StoryNotFoundError("story does not exist")
            story = Story.model_validate_json(row["payload"])
            if story.status not in (StoryStatus.DRAFT, StoryStatus.IDLE):
                raise IllegalStoryStateError("story cannot be confirmed from its current state")
            branch_id = row["current_branch_id"]
            complete = (
                branch_id is not None
                and _optional_id(story.current_branch_id) == branch_id
                and all(
                    (
                        connection.execute(
                            "SELECT 1 FROM story_bibles WHERE story_id = ?",
                            (str(story_id),),
                        ).fetchone(),
                        connection.execute(
                            "SELECT 1 FROM branches WHERE id = ? AND story_id = ?",
                            (branch_id, str(story_id)),
                        ).fetchone(),
                        connection.execute(
                            """
                            SELECT 1 FROM character_states
                            WHERE story_id = ? AND branch_id = ? LIMIT 1
                            """,
                            (str(story_id), branch_id),
                        ).fetchone(),
                        connection.execute(
                            """
                            SELECT 1 FROM story_arcs
                            WHERE story_id = ? AND branch_id = ? LIMIT 1
                            """,
                            (str(story_id), branch_id),
                        ).fetchone(),
                    )
                )
            )
            if not complete:
                raise IncompleteBibleBundleError("complete Bible bundle required")
            if story.status == StoryStatus.IDLE:
                return story
            try:
                target = transition(story.status, StoryStatus.IDLE)
            except InvalidTransitionError as exc:
                raise IllegalStoryStateError(str(exc)) from exc
            updated = story.model_copy(
                update={
                    "status": target,
                    "version": story.version + 1,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
            )
            connection.execute(
                "UPDATE stories SET payload = ? WHERE id = ?",
                (_json(updated), str(story_id)),
            )
        return updated

    def create_branch(self, branch: Branch) -> Branch:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO branches (
                    id, story_id, parent_branch_id, fork_choice_id, fork_segment_id, head_segment_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(branch.id),
                    str(branch.story_id),
                    _optional_id(branch.parent_branch_id),
                    _optional_id(branch.fork_choice_id),
                    _optional_id(branch.fork_segment_id),
                    _optional_id(branch.head_segment_id),
                    _json(branch),
                ),
            )
        return branch

    def get_branch(self, branch_id: UUID) -> Branch | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM branches WHERE id = ?", (str(branch_id),)
            ).fetchone()
        return Branch.model_validate_json(row["payload"]) if row else None

    def commit_segment_bundle(
        self,
        segment: StorySegment,
        choice_point: ChoicePoint | None = None,
        event: GenerationEvent | None = None,
    ) -> StorySegment:
        """Atomically persist a generated segment and its optional associated records."""
        with self.database.transaction() as connection:
            branch_row = connection.execute(
                "SELECT story_id, head_segment_id, payload FROM branches WHERE id = ?",
                (str(segment.branch_id),),
            ).fetchone()
            if branch_row is None:
                raise sqlite3.IntegrityError("segment branch does not exist")
            if branch_row["story_id"] != str(segment.story_id):
                raise ValueError("segment branch must belong to the segment story")
            return self._insert_segment_bundle(
                connection,
                segment,
                branch_row,
                choice_point,
                event,
            )

    def commit_generation_bundle(
        self,
        initial_story: Story,
        state_sequence: list[StoryStatus],
        segment: StorySegment,
        choice_point: ChoicePoint | None,
        event: GenerationEvent,
    ) -> tuple[Story, StorySegment]:
        """Atomically persist every state write and one completed generation bundle."""
        if not state_sequence or state_sequence[0] != initial_story.status:
            raise ValueError("generation state sequence must begin at the persisted status")
        if event.state_sequence != state_sequence:
            raise ValueError("generation event must record the exact state sequence")
        current = state_sequence[0]
        for target in state_sequence[1:]:
            current = transition(current, target)
        with self.database.transaction() as connection:
            story_row = connection.execute(
                "SELECT current_branch_id, payload FROM stories WHERE id = ?",
                (str(initial_story.id),),
            ).fetchone()
            if story_row is None:
                raise StoryNotFoundError("story does not exist")
            persisted_story = Story.model_validate_json(story_row["payload"])
            if (
                persisted_story.status != initial_story.status
                or persisted_story.version != initial_story.version
                or persisted_story.current_branch_id != segment.branch_id
                or story_row["current_branch_id"] != str(segment.branch_id)
            ):
                raise IllegalStoryStateError("story changed before generation commit")

            branch_row = connection.execute(
                "SELECT story_id, head_segment_id, payload FROM branches WHERE id = ?",
                (str(segment.branch_id),),
            ).fetchone()
            if branch_row is None:
                raise sqlite3.IntegrityError("segment branch does not exist")
            if branch_row["story_id"] != str(segment.story_id):
                raise ValueError("segment branch must belong to the segment story")
            if branch_row["head_segment_id"] != _optional_id(segment.parent_segment_id):
                raise IllegalStoryStateError("branch head changed before generation commit")

            updated_story = persisted_story
            for target in state_sequence[1:]:
                updated_story = updated_story.model_copy(
                    update={
                        "status": target,
                        "version": updated_story.version + 1,
                        "updated_at": datetime.now(UTC).replace(tzinfo=None),
                    }
                )
                connection.execute(
                    "UPDATE stories SET payload = ? WHERE id = ?",
                    (_json(updated_story), str(updated_story.id)),
                )

            committed = self._insert_segment_bundle(
                connection,
                segment,
                branch_row,
                choice_point,
                event,
            )
        return updated_story, committed

    def get_segment_by_generation_key(self, generation_key: str) -> StorySegment | None:
        """Return the formal scene committed for one idempotency key, if any."""
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM story_segments WHERE generation_key = ?",
                (generation_key,),
            ).fetchone()
        return StorySegment.model_validate_json(row["payload"]) if row else None

    def get_choice_point_for_segment(self, segment_id: UUID) -> ChoicePoint | None:
        """Return the optional choice committed with a formal scene."""
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM choice_points WHERE segment_id = ?",
                (str(segment_id),),
            ).fetchone()
        return ChoicePoint.model_validate_json(row["payload"]) if row else None

    def get_choice_with_story(self, choice_id: UUID) -> tuple[ChoicePoint, Story] | None:
        """Return a choice and its owning story for pre-provider validation."""
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT choice_points.payload AS choice_payload,
                       stories.payload AS story_payload
                FROM choice_points
                JOIN stories ON stories.id = choice_points.story_id
                WHERE choice_points.id = ?
                """,
                (str(choice_id),),
            ).fetchone()
        if row is None:
            return None
        return (
            ChoicePoint.model_validate_json(row["choice_payload"]),
            Story.model_validate_json(row["story_payload"]),
        )

    def submit_choice(
        self,
        choice_id: UUID,
        choice_version: int,
        *,
        option_id: UUID | None = None,
        custom_action: str | None = None,
        custom_effects: Mapping[str, object] | None = None,
    ) -> ChoiceSubmissionResult:
        """Atomically select a choice, append its memory snapshot, and resume the story."""
        if (option_id is None) == (custom_action is None):
            raise ValueError("exactly one preset option or custom action is required")
        if custom_action is not None and custom_effects is None:
            raise ValueError("custom effects are required for a custom action")

        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT choice_points.payload AS choice_payload,
                       choice_points.segment_id,
                       choice_points.story_id,
                       story_segments.branch_id,
                       stories.current_branch_id,
                       stories.payload AS story_payload
                FROM choice_points
                JOIN story_segments ON story_segments.id = choice_points.segment_id
                JOIN stories ON stories.id = choice_points.story_id
                WHERE choice_points.id = ?
                """,
                (str(choice_id),),
            ).fetchone()
            if row is None:
                raise ChoiceNotFoundError("choice does not exist")
            choice = ChoicePoint.model_validate_json(row["choice_payload"])
            story = Story.model_validate_json(row["story_payload"])

            if choice.version != choice_version:
                if _is_exact_choice_replay(
                    choice,
                    choice_version,
                    option_id=option_id,
                    custom_action=custom_action,
                ):
                    return ChoiceSubmissionResult(status="duplicate", choice=choice, story=story)
                raise ChoiceVersionConflictError("choice version changed")
            branch_row = connection.execute(
                "SELECT head_segment_id FROM branches WHERE id = ? AND story_id = ?",
                (row["branch_id"], row["story_id"]),
            ).fetchone()
            if (
                story.status is not StoryStatus.WAITING_CHOICE
                or story.current_branch_id is None
                or str(story.current_branch_id) != row["branch_id"]
                or row["current_branch_id"] != row["branch_id"]
                or branch_row is None
                or branch_row["head_segment_id"] != row["segment_id"]
            ):
                raise InvalidChoiceStateError("story is not waiting on this current choice")

            if option_id is not None:
                option = next(
                    (candidate for candidate in choice.options if candidate.id == option_id),
                    None,
                )
                if option is None:
                    raise ChoiceOptionNotFoundError("option does not belong to choice")
                selected_effects: Mapping[str, object] = option.effects
            else:
                assert custom_effects is not None
                selected_effects = custom_effects

            snapshot_row = connection.execute(
                """
                SELECT payload FROM memory_snapshots
                WHERE branch_id = ? ORDER BY rowid DESC LIMIT 1
                """,
                (row["branch_id"],),
            ).fetchone()
            if snapshot_row is None:
                character_rows = connection.execute(
                    """
                    SELECT payload FROM character_states
                    WHERE story_id = ? AND branch_id = ? ORDER BY rowid
                    """,
                    (row["story_id"], row["branch_id"]),
                ).fetchall()
                base_snapshot = MemorySnapshot(
                    story_id=story.id,
                    branch_id=UUID(row["branch_id"]),
                    segment_id=UUID(row["segment_id"]),
                    characters=[
                        CharacterState.model_validate_json(item["payload"])
                        for item in character_rows
                    ],
                    context_version=0,
                )
            else:
                base_snapshot = MemorySnapshot.model_validate_json(snapshot_row["payload"])
            try:
                updated_memory = MemoryService.apply_choice_effects(
                    base_snapshot, selected_effects
                ).model_copy(
                    update={
                        "id": uuid4(),
                        "segment_id": UUID(row["segment_id"]),
                    },
                    deep=True,
                )
            except ValueError as exc:
                raise InvalidChoiceEffectsError("choice effects are invalid") from exc

            updated_choice = choice.model_copy(
                update={
                    "status": "selected",
                    "selected_option_id": option_id,
                    "selected_custom_action": custom_action,
                    "selected_effects": dict(selected_effects),
                    "version": choice.version + 1,
                },
                deep=True,
            )
            updated_story = story.model_copy(
                update={
                    "status": transition(story.status, StoryStatus.IDLE),
                    "version": story.version + 1,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }
            )
            choice_update = connection.execute(
                """
                UPDATE choice_points SET selected_option_id = ?, payload = ?
                WHERE id = ?
                """,
                (_optional_id(option_id), _json(updated_choice), str(choice.id)),
            )
            story_update = connection.execute(
                "UPDATE stories SET payload = ? WHERE id = ?",
                (_json(updated_story), str(story.id)),
            )
            if choice_update.rowcount != 1 or story_update.rowcount != 1:
                raise RuntimeError("choice aggregate disappeared during submission")
            connection.execute(
                """
                INSERT INTO memory_snapshots (id, story_id, branch_id, segment_id, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(updated_memory.id),
                    str(updated_memory.story_id),
                    str(updated_memory.branch_id),
                    _optional_id(updated_memory.segment_id),
                    _json(updated_memory),
                ),
            )
        return ChoiceSubmissionResult(
            status="success", choice=updated_choice, story=updated_story
        )

    def _insert_segment_bundle(
        self,
        connection: sqlite3.Connection,
        segment: StorySegment,
        branch_row: sqlite3.Row,
        choice_point: ChoicePoint | None,
        event: GenerationEvent | None,
    ) -> StorySegment:
        """Insert one scene bundle using an existing transaction and branch row."""
        if event is not None and (
            event.story_id != segment.story_id or event.branch_id != segment.branch_id
        ):
            raise ValueError("event story and branch must match the segment")
        existing = connection.execute(
            "SELECT payload FROM story_segments WHERE generation_key = ?",
            (segment.generation_key,),
        ).fetchone()
        if existing:
            return StorySegment.model_validate_json(existing["payload"])
        connection.execute(
            """
            INSERT INTO story_segments (
                id, story_id, branch_id, parent_segment_id, sequence, generation_key, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(segment.id),
                str(segment.story_id),
                str(segment.branch_id),
                _optional_id(segment.parent_segment_id),
                segment.sequence,
                segment.generation_key,
                _json(segment),
            ),
        )
        if choice_point is not None:
            self._insert_choice_point(connection, segment, choice_point)
        if event is not None:
            connection.execute(
                """
                INSERT INTO generation_events (id, story_id, branch_id, request_id, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(event.id),
                    str(event.story_id),
                    str(event.branch_id),
                    event.request_id,
                    _json(event),
                ),
            )
        branch = Branch.model_validate_json(branch_row["payload"]).model_copy(
            update={"head_segment_id": segment.id}
        )
        updated = connection.execute(
            """
            UPDATE branches SET head_segment_id = ?, payload = ?
            WHERE id = ? AND story_id = ?
            """,
            (str(segment.id), _json(branch), str(segment.branch_id), str(segment.story_id)),
        )
        if updated.rowcount != 1:
            raise RuntimeError("segment branch disappeared during transaction")
        return segment

    def _insert_choice_point(
        self, connection: sqlite3.Connection, segment: StorySegment, choice_point: ChoicePoint
    ) -> None:
        if choice_point.selected_option_id is not None and choice_point.selected_option_id not in {
            option.id for option in choice_point.options
        }:
            raise ValueError("selected option must belong to the exact choice point")
        bound_options = [
            option.model_copy(update={"choice_point_id": choice_point.id})
            for option in choice_point.options
        ]
        bound_choice = choice_point.model_copy(
            update={"segment_id": segment.id, "options": bound_options}
        )
        connection.execute(
            """
            INSERT INTO choice_points (id, story_id, segment_id, selected_option_id, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(bound_choice.id),
                str(segment.story_id),
                str(segment.id),
                _optional_id(bound_choice.selected_option_id),
                _json(bound_choice),
            ),
        )
        for option in bound_options:
            connection.execute(
                """
                INSERT INTO choice_options (id, story_id, choice_point_id, position, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(option.id),
                    str(segment.story_id),
                    str(bound_choice.id),
                    option.position,
                    _json(option),
                ),
            )

    def get_segment(self, segment_id: UUID) -> StorySegment | None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload FROM story_segments WHERE id = ?", (str(segment_id),)
            ).fetchone()
        return StorySegment.model_validate_json(row["payload"]) if row else None

    def list_branch_path(self, branch_id: UUID) -> list[StorySegment]:
        """Follow a branch head's parent links from root through the current head."""
        with self.database.read() as connection:
            branch = connection.execute(
                "SELECT head_segment_id FROM branches WHERE id = ?", (str(branch_id),)
            ).fetchone()
            if branch is None or branch["head_segment_id"] is None:
                return []
            path: list[StorySegment] = []
            segment_id = branch["head_segment_id"]
            visited: set[str] = set()
            while segment_id is not None:
                if segment_id in visited:
                    raise ValueError("cycle detected in branch segment path")
                visited.add(segment_id)
                row = connection.execute(
                    "SELECT parent_segment_id, payload FROM story_segments WHERE id = ?", (segment_id,)
                ).fetchone()
                if row is None:
                    return []
                path.append(StorySegment.model_validate_json(row["payload"]))
                segment_id = row["parent_segment_id"]
        return list(reversed(path))

    def save_memory_snapshot(self, snapshot: MemorySnapshot) -> MemorySnapshot:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memory_snapshots (id, story_id, branch_id, segment_id, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(snapshot.id),
                    str(snapshot.story_id),
                    str(snapshot.branch_id),
                    _optional_id(snapshot.segment_id),
                    _json(snapshot),
                ),
            )
        return snapshot

    def get_latest_memory_snapshot(self, branch_id: UUID) -> MemorySnapshot | None:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT payload FROM memory_snapshots
                WHERE branch_id = ? ORDER BY rowid DESC LIMIT 1
                """,
                (str(branch_id),),
            ).fetchone()
        return MemorySnapshot.model_validate_json(row["payload"]) if row else None

    def fork_at_choice(
        self,
        choice_id: UUID,
        branch_name: str = "Branch",
    ) -> tuple[Branch, MemorySnapshot]:
        """Atomically create a fork branch at a selected choice and copy the pre-choice snapshot."""
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    choice_points.id                                   AS choice_id,
                    json_extract(choice_points.payload, '$.status')    AS choice_status,
                    choice_points.selected_option_id,
                    choice_points.story_id                             AS story_id,
                    choice_points.segment_id                           AS segment_id,
                    story_segments.branch_id                           AS original_branch_id
                FROM choice_points
                JOIN story_segments ON story_segments.id = choice_points.segment_id
                WHERE choice_points.id = ?
                """,
                (str(choice_id),),
            ).fetchone()
            if row is None:
                raise ChoiceNotFoundError("choice does not exist")
            if row["choice_status"] != "selected":
                raise ChoiceNotSelectedError("choice must be selected before branching")

            story_id_str = row["story_id"]
            segment_id_str = row["segment_id"]
            original_branch_id_str = row["original_branch_id"]
            fork_choice_option_id: str | None = row["selected_option_id"]

            # Find the pre-choice memory snapshot for the original branch.
            # submit_choice saves a snapshot with segment_id = fork_segment;
            # the snapshot just before that rowid is the pre-choice state.
            choice_snap = connection.execute(
                """
                SELECT rowid, payload FROM memory_snapshots
                WHERE branch_id = ? AND segment_id = ?
                ORDER BY rowid DESC LIMIT 1
                """,
                (original_branch_id_str, segment_id_str),
            ).fetchone()

            if choice_snap is not None:
                pre_snap = connection.execute(
                    """
                    SELECT payload FROM memory_snapshots
                    WHERE branch_id = ? AND rowid < ?
                    ORDER BY rowid DESC LIMIT 1
                    """,
                    (original_branch_id_str, choice_snap["rowid"]),
                ).fetchone()
            else:
                pre_snap = None

            if pre_snap is not None:
                base_snapshot = MemorySnapshot.model_validate_json(pre_snap["payload"])
            else:
                # Synthesise from initial character states when no explicit pre-choice snapshot exists
                char_rows = connection.execute(
                    """
                    SELECT payload FROM character_states
                    WHERE story_id = ? AND branch_id = ? ORDER BY rowid
                    """,
                    (story_id_str, original_branch_id_str),
                ).fetchall()
                base_snapshot = MemorySnapshot(
                    story_id=UUID(story_id_str),
                    branch_id=UUID(original_branch_id_str),
                    segment_id=UUID(segment_id_str),
                    characters=[
                        CharacterState.model_validate_json(r["payload"]) for r in char_rows
                    ],
                    context_version=0,
                )

            new_branch = Branch(
                story_id=UUID(story_id_str),
                parent_branch_id=UUID(original_branch_id_str),
                fork_segment_id=UUID(segment_id_str),
                fork_choice_id=UUID(fork_choice_option_id) if fork_choice_option_id else None,
                name=branch_name,
                # head_segment_id = fork_segment so generation chains from the fork point
                head_segment_id=UUID(segment_id_str),
            )
            connection.execute(
                """
                INSERT INTO branches (
                    id, story_id, parent_branch_id, fork_choice_id, fork_segment_id,
                    head_segment_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(new_branch.id),
                    str(new_branch.story_id),
                    _optional_id(new_branch.parent_branch_id),
                    _optional_id(new_branch.fork_choice_id),
                    _optional_id(new_branch.fork_segment_id),
                    _optional_id(new_branch.head_segment_id),
                    _json(new_branch),
                ),
            )

            new_snapshot = base_snapshot.model_copy(
                update={
                    "id": uuid4(),
                    "branch_id": new_branch.id,
                    "segment_id": UUID(segment_id_str),
                },
                deep=True,
            )
            connection.execute(
                """
                INSERT INTO memory_snapshots (id, story_id, branch_id, segment_id, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(new_snapshot.id),
                    str(new_snapshot.story_id),
                    str(new_snapshot.branch_id),
                    _optional_id(new_snapshot.segment_id),
                    _json(new_snapshot),
                ),
            )
        return new_branch, new_snapshot


def _optional_id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _is_exact_choice_replay(
    choice: ChoicePoint,
    submitted_version: int,
    *,
    option_id: UUID | None,
    custom_action: str | None,
) -> bool:
    """Recognize the original request without treating another stale choice as duplicate."""
    return (
        choice.status == "selected"
        and choice.version == submitted_version + 1
        and choice.selected_option_id == option_id
        and choice.selected_custom_action == custom_action
    )

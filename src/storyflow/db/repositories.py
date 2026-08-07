"""Persistence operations for StoryFlow's Pydantic domain models."""
import sqlite3
from uuid import UUID

from pydantic import BaseModel

from storyflow.db.database import Database
from storyflow.domain.models import (
    Branch,
    ChoicePoint,
    GenerationEvent,
    MemorySnapshot,
    Story,
    StoryBible,
    StorySegment,
)


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
                "SELECT story_id, payload FROM branches WHERE id = ?", (str(segment.branch_id),)
            ).fetchone()
            if branch_row is None:
                raise sqlite3.IntegrityError("segment branch does not exist")
            if branch_row["story_id"] != str(segment.story_id):
                raise ValueError("segment branch must belong to the segment story")
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
                    (str(event.id), str(event.story_id), str(event.branch_id), event.request_id, _json(event)),
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


def _optional_id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None

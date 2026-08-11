"""SQLite connection and transaction management."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Create configured connections to one StoryFlow SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        """Open a connection with all required SQLite settings enabled."""
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        """Install the schema and apply compatible structural migrations."""
        schema_path = Path(__file__).with_name("schema.sql")
        connection = self.connect()
        try:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            self._make_generation_event_branch_nullable(connection)
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _make_generation_event_branch_nullable(connection: sqlite3.Connection) -> None:
        """Preserve existing events while allowing aggregate-level recovery records."""
        branch_column = next(
            (
                row
                for row in connection.execute("PRAGMA table_info(generation_events)")
                if row["name"] == "branch_id"
            ),
            None,
        )
        if branch_column is None or branch_column["notnull"] == 0:
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN;
                ALTER TABLE generation_events RENAME TO generation_events_legacy;
                CREATE TABLE generation_events (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id),
                    branch_id TEXT,
                    request_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    FOREIGN KEY (branch_id, story_id) REFERENCES branches(id, story_id)
                );
                INSERT INTO generation_events (id, story_id, branch_id, request_id, payload)
                SELECT id, story_id, branch_id, request_id, payload
                FROM generation_events_legacy;
                DROP TABLE generation_events_legacy;
                COMMIT;
                """
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Yield a read connection and close it on every exit path."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection with an explicit transaction boundary."""
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

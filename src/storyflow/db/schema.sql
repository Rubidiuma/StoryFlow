CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    current_branch_id TEXT,
    payload TEXT NOT NULL,
    FOREIGN KEY (current_branch_id, id) REFERENCES branches(id, story_id)
);

CREATE TABLE IF NOT EXISTS story_bibles (
    story_id TEXT PRIMARY KEY REFERENCES stories(id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    parent_branch_id TEXT,
    fork_choice_id TEXT,
    fork_segment_id TEXT,
    head_segment_id TEXT,
    payload TEXT NOT NULL,
    UNIQUE (id, story_id),
    CHECK (parent_branch_id IS NULL OR parent_branch_id <> id),
    FOREIGN KEY (parent_branch_id, story_id) REFERENCES branches(id, story_id),
    FOREIGN KEY (fork_choice_id, story_id) REFERENCES choice_options(id, story_id),
    FOREIGN KEY (fork_segment_id, story_id) REFERENCES story_segments(id, story_id),
    FOREIGN KEY (head_segment_id, story_id) REFERENCES story_segments(id, story_id)
);

CREATE TABLE IF NOT EXISTS story_segments (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL,
    parent_segment_id TEXT,
    sequence INTEGER NOT NULL,
    generation_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    UNIQUE (id, story_id),
    CHECK (parent_segment_id IS NULL OR parent_segment_id <> id),
    FOREIGN KEY (branch_id, story_id) REFERENCES branches(id, story_id),
    FOREIGN KEY (parent_segment_id, story_id) REFERENCES story_segments(id, story_id)
);

CREATE TABLE IF NOT EXISTS choice_points (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    selected_option_id TEXT,
    payload TEXT NOT NULL,
    UNIQUE (id, story_id),
    FOREIGN KEY (segment_id, story_id) REFERENCES story_segments(id, story_id),
    FOREIGN KEY (selected_option_id, id)
        REFERENCES choice_options(id, choice_point_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS choice_options (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    choice_point_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (id, story_id),
    UNIQUE (id, choice_point_id),
    FOREIGN KEY (choice_point_id, story_id) REFERENCES choice_points(id, story_id)
);

CREATE TABLE IF NOT EXISTS generation_events (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    FOREIGN KEY (branch_id, story_id) REFERENCES branches(id, story_id)
);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL,
    segment_id TEXT,
    payload TEXT NOT NULL,
    FOREIGN KEY (branch_id, story_id) REFERENCES branches(id, story_id),
    FOREIGN KEY (segment_id, story_id) REFERENCES story_segments(id, story_id)
);

CREATE TRIGGER IF NOT EXISTS branch_fork_choice_matches_segment_insert
BEFORE INSERT ON branches
WHEN NEW.fork_choice_id IS NOT NULL
    AND NEW.fork_segment_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM choice_options AS choice_option
        JOIN choice_points AS choice_point
            ON choice_point.id = choice_option.choice_point_id
        WHERE choice_option.id = NEW.fork_choice_id
            AND choice_point.segment_id = NEW.fork_segment_id
    )
BEGIN
    SELECT RAISE(ABORT, 'branch fork choice must belong to its fork segment');
END;

CREATE TRIGGER IF NOT EXISTS branch_fork_choice_matches_segment_update
BEFORE UPDATE OF fork_choice_id, fork_segment_id ON branches
WHEN NEW.fork_choice_id IS NOT NULL
    AND NEW.fork_segment_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM choice_options AS choice_option
        JOIN choice_points AS choice_point
            ON choice_point.id = choice_option.choice_point_id
        WHERE choice_option.id = NEW.fork_choice_id
            AND choice_point.segment_id = NEW.fork_segment_id
    )
BEGIN
    SELECT RAISE(ABORT, 'branch fork choice must belong to its fork segment');
END;

CREATE TRIGGER IF NOT EXISTS branch_path_references_insert
BEFORE INSERT ON branches
WHEN
    (
        NEW.fork_segment_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE parent_path(id) AS (
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN parent_path ON branch.id = parent_path.id
                WHERE branch.parent_branch_id IS NOT NULL
            )
            SELECT 1
            FROM story_segments AS segment
            JOIN parent_path ON parent_path.id = segment.branch_id
            WHERE segment.id = NEW.fork_segment_id
        )
    )
    OR (
        NEW.fork_choice_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE parent_path(id) AS (
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN parent_path ON branch.id = parent_path.id
                WHERE branch.parent_branch_id IS NOT NULL
            )
            SELECT 1
            FROM choice_options AS choice_option
            JOIN choice_points AS choice_point
                ON choice_point.id = choice_option.choice_point_id
            JOIN story_segments AS segment ON segment.id = choice_point.segment_id
            JOIN parent_path ON parent_path.id = segment.branch_id
            WHERE choice_option.id = NEW.fork_choice_id
        )
    )
    OR (
        NEW.head_segment_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE branch_path(id) AS (
                SELECT NEW.id
                UNION
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN branch_path ON branch.id = branch_path.id
                WHERE branch.parent_branch_id IS NOT NULL
                    AND branch.id <> NEW.id
            )
            SELECT 1
            FROM story_segments AS segment
            JOIN branch_path ON branch_path.id = segment.branch_id
            WHERE segment.id = NEW.head_segment_id
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'branch path reference mismatch');
END;

CREATE TRIGGER IF NOT EXISTS branch_path_references_update
BEFORE UPDATE OF parent_branch_id, fork_choice_id, fork_segment_id, head_segment_id ON branches
WHEN
    (
        NEW.parent_branch_id IS NOT NULL
        AND EXISTS (
            WITH RECURSIVE parent_path(id) AS (
                SELECT NEW.parent_branch_id
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN parent_path ON branch.id = parent_path.id
                WHERE branch.parent_branch_id IS NOT NULL
                    AND branch.id <> NEW.id
            )
            SELECT 1 FROM parent_path WHERE id = NEW.id
        )
    )
    OR (
        NEW.fork_segment_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE parent_path(id) AS (
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN parent_path ON branch.id = parent_path.id
                WHERE branch.parent_branch_id IS NOT NULL
                    AND branch.id <> NEW.id
            )
            SELECT 1
            FROM story_segments AS segment
            JOIN parent_path ON parent_path.id = segment.branch_id
            WHERE segment.id = NEW.fork_segment_id
        )
    )
    OR (
        NEW.fork_choice_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE parent_path(id) AS (
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN parent_path ON branch.id = parent_path.id
                WHERE branch.parent_branch_id IS NOT NULL
                    AND branch.id <> NEW.id
            )
            SELECT 1
            FROM choice_options AS choice_option
            JOIN choice_points AS choice_point
                ON choice_point.id = choice_option.choice_point_id
            JOIN story_segments AS segment ON segment.id = choice_point.segment_id
            JOIN parent_path ON parent_path.id = segment.branch_id
            WHERE choice_option.id = NEW.fork_choice_id
        )
    )
    OR (
        NEW.head_segment_id IS NOT NULL
        AND NOT EXISTS (
            WITH RECURSIVE branch_path(id) AS (
                SELECT NEW.id
                UNION
                SELECT NEW.parent_branch_id WHERE NEW.parent_branch_id IS NOT NULL
                UNION
                SELECT branch.parent_branch_id
                FROM branches AS branch
                JOIN branch_path ON branch.id = branch_path.id
                WHERE branch.parent_branch_id IS NOT NULL
                    AND branch.id <> NEW.id
            )
            SELECT 1
            FROM story_segments AS segment
            JOIN branch_path ON branch_path.id = segment.branch_id
            WHERE segment.id = NEW.head_segment_id
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'branch path reference mismatch');
END;

CREATE INDEX IF NOT EXISTS idx_memory_snapshots_branch_id
    ON memory_snapshots(branch_id);

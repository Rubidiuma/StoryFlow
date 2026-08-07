CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story_bibles (
    story_id TEXT PRIMARY KEY REFERENCES stories(id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    parent_branch_id TEXT REFERENCES branches(id),
    fork_choice_id TEXT REFERENCES choice_options(id),
    fork_segment_id TEXT REFERENCES story_segments(id),
    head_segment_id TEXT REFERENCES story_segments(id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS story_segments (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL REFERENCES branches(id),
    parent_segment_id TEXT REFERENCES story_segments(id),
    sequence INTEGER NOT NULL,
    generation_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS choice_points (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES story_segments(id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS choice_options (
    id TEXT PRIMARY KEY,
    choice_point_id TEXT NOT NULL REFERENCES choice_points(id),
    position INTEGER NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_events (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL REFERENCES branches(id),
    request_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(id),
    branch_id TEXT NOT NULL REFERENCES branches(id),
    segment_id TEXT REFERENCES story_segments(id),
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_snapshots_branch_id
    ON memory_snapshots(branch_id);

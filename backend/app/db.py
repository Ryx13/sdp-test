"""SQLite connection handling and schema management."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('zip', 'clone')),
    source TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('cloning', 'ready', 'error')),
    error TEXT,
    progress INTEGER NOT NULL DEFAULT 0,
    default_branch TEXT,
    head_commit TEXT,
    size_bytes INTEGER,
    created_at TEXT NOT NULL,
    -- history extraction state (managed by services/history.py)
    parse_status TEXT NOT NULL DEFAULT 'none',
    parse_progress INTEGER NOT NULL DEFAULT 0,
    parse_error TEXT,
    commit_count INTEGER,
    analysed_head TEXT,
    parsed_at TEXT
);

CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_email TEXT NOT NULL,
    committer_ts INTEGER NOT NULL,
    parent_sha TEXT,
    added INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_ts ON commits (repo_id, committer_ts DESC);
CREATE INDEX IF NOT EXISTS idx_commits_repo_author ON commits (repo_id, author_email);

CREATE TABLE IF NOT EXISTS file_changes (
    repo_id TEXT NOT NULL,
    sha TEXT NOT NULL,
    path TEXT NOT NULL,
    added INTEGER NOT NULL,
    removed INTEGER NOT NULL,
    renamed_from TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_changes_repo_path ON file_changes (repo_id, path);
CREATE INDEX IF NOT EXISTS idx_file_changes_repo_sha ON file_changes (repo_id, sha);
"""

# Columns added to `repositories` after the initial release. Fresh databases get
# them from SCHEMA above; pre-existing ones are upgraded in place.
_REPOSITORY_MIGRATIONS = {
    "parse_status": "TEXT NOT NULL DEFAULT 'none'",
    "parse_progress": "INTEGER NOT NULL DEFAULT 0",
    "parse_error": "TEXT",
    "commit_count": "INTEGER",
    "analysed_head": "TEXT",
    "parsed_at": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(repositories)")}
    for column, ddl in _REPOSITORY_MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE repositories ADD COLUMN {column} {ddl}")


def connect() -> sqlite3.Connection:
    config.data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.repos_dir().mkdir(parents=True, exist_ok=True)
    config.tmp_dir().mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)

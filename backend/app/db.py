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
    created_at TEXT NOT NULL
);
"""


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

"""Persistence for the repository catalog."""

from __future__ import annotations

import datetime
import uuid

from ..db import get_db


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def list_repositories() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM repositories ORDER BY created_at DESC, name COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def get_repository(repo_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    return dict(row) if row else None


def create_repository(
    *,
    name: str,
    source_type: str,
    source: str,
    path: str,
    status: str = "cloning",
    progress: int = 0,
    error: str | None = None,
    default_branch: str | None = None,
    head_commit: str | None = None,
    size_bytes: int | None = None,
    repo_id: str | None = None,
) -> dict:
    repo_id = repo_id or uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO repositories
                (id, name, source_type, source, path, status, progress, created_at,
                 error, default_branch, head_commit, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id, name, source_type, source, path, status, progress, _utcnow(),
                error, default_branch, head_commit, size_bytes,
            ),
        )
    created = get_repository(repo_id)
    assert created is not None
    return created


def update_repository(repo_id: str, **fields) -> dict | None:
    if fields:
        columns = ", ".join(f"{key} = ?" for key in fields)
        with get_db() as conn:
            conn.execute(
                f"UPDATE repositories SET {columns} WHERE id = ?", (*fields.values(), repo_id)
            )
    return get_repository(repo_id)


def delete_repository(repo_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    return cursor.rowcount > 0

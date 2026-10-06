"""History extraction: stream non-merge commits with per-file stats into SQLite.

The brief fixes the semantics implemented here:

* only non-merge commits reachable from HEAD are analysed (the H̄ set);
* rename detection runs at a 50% similarity threshold (``--find-renames=50%``):
  a pure rename preserves a file's metrics, while later edits are attributed to
  the new path (``renamed_from`` records the old path for display);
* binary files are excluded entirely (git reports ``-`` for their line counts);
* deletions are recorded as line removals on the deleted path;
* commit timestamps use the *committer* date (``%ct``), matching the time-window
  definitions used by commit sets.

``git log`` is streamed and rows are committed in short batches so a long
extraction still reports progress while WAL readers stay unblocked.
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Iterator
from pathlib import Path

from .. import config, db
from . import catalog
from .git_commands import (
    count_history_commits,
    open_history_stream,
    run_git,
    tail_text,
)

# Byte-level layout produced by ``git_commands.open_history_stream``:
#
#   RS <sha> US <author> US <email> US <committer-ts> US <parents> NUL [LF]
#   { "<added>\t<removed>\t<path>" NUL
#   | "<added>\t<removed>\t" NUL "<old>" NUL "<new>" NUL }*
#
# RS/US never occur in commit metadata, and ``-z`` reports paths raw, so the
# stream can be parsed without quoting heuristics.
RS = b"\x1e"
US = b"\x1f"
NUL = b"\x00"

# Long histories are written in bounded batches; the repository row is updated
# with progress in the same short transactions.
_FLUSH_INTERVAL_SECONDS = 0.5
_MAX_PENDING_CHANGES = 20_000
_CHUNK_SIZE = 1 << 20


class HistoryError(Exception):
    """A repository could not be analysed."""


class NotAnalysableError(HistoryError):
    """The repository is not in a state that allows analysis."""


class AnalysisRunningError(HistoryError):
    """Another analysis is already running for this repository."""


class ParseError(HistoryError):
    """git log output could not be parsed (should never happen)."""


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def start_analysis(repo_id: str) -> dict:
    """Atomically flip a ready repository into the ``parsing`` state.

    The conditional UPDATE doubles as the concurrency guard: a second caller
    (double click, retry) sees zero affected rows and gets rejected.
    """
    repo = catalog.get_repository(repo_id)
    if repo is None:
        raise NotAnalysableError("Repository not found.")
    if repo["status"] != "ready":
        raise NotAnalysableError("Only successfully ingested repositories can be analysed.")
    with db.get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE repositories
               SET parse_status = 'parsing', parse_progress = 0, parse_error = NULL
             WHERE id = ? AND status = 'ready' AND parse_status != 'parsing'
            """,
            (repo_id,),
        )
    if cursor.rowcount == 0:
        raise AnalysisRunningError("An analysis is already running for this repository.")
    updated = catalog.get_repository(repo_id)
    assert updated is not None
    return updated


def analyse_repository(repo_id: str) -> None:
    """Background entry point: run the extraction, recording any failure."""
    try:
        _analyse(repo_id)
    except Exception as exc:  # every failure is surfaced on the catalog entry
        catalog.update_repository(
            repo_id,
            parse_status="error",
            parse_error=str(exc)[:1000],
            parse_progress=0,
        )


def _analyse(repo_id: str) -> None:
    repo = catalog.get_repository(repo_id)
    if repo is None:
        raise HistoryError("Repository not found.")
    if repo["status"] != "ready":
        raise NotAnalysableError("Repository is not ready for analysis.")

    path = Path(repo["path"])
    total = count_history_commits(path)  # also fails cleanly when HEAD is unborn
    head = run_git(["rev-parse", "HEAD"], cwd=path, timeout=30).strip()

    config.tmp_dir().mkdir(parents=True, exist_ok=True)
    stderr_path = config.tmp_dir() / f"analysis-{repo_id}.stderr"
    conn = db.connect()
    try:
        # Replace any previous extraction: nothing is visible mid-run except
        # batches of fresh rows, and a cached result only exists when
        # ``parse_status == 'ready'``.
        conn.execute("DELETE FROM file_changes WHERE repo_id = ?", (repo_id,))
        conn.execute("DELETE FROM commits WHERE repo_id = ?", (repo_id,))
        conn.commit()

        pending_commits: list[tuple] = []
        pending_changes: list[tuple] = []
        processed = 0
        last_flush = time.monotonic()

        def flush() -> None:
            if pending_commits:
                conn.executemany(
                    "INSERT OR REPLACE INTO commits (sha, repo_id, author_name,"
                    " author_email, committer_ts, parent_sha, added, removed)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    pending_commits,
                )
                pending_commits.clear()
            if pending_changes:
                conn.executemany(
                    "INSERT INTO file_changes (repo_id, sha, path, added, removed,"
                    " renamed_from) VALUES (?, ?, ?, ?, ?, ?)",
                    pending_changes,
                )
                pending_changes.clear()
            progress = min(99, processed * 100 // total) if total else 99
            conn.execute(
                "UPDATE repositories SET parse_progress = ? WHERE id = ?",
                (progress, repo_id),
            )
            conn.commit()

        with open(stderr_path, "wb") as stderr_file:
            proc = open_history_stream(path, stderr=stderr_file)
            assert proc.stdout is not None
            try:
                for record in _iter_records(_chunks(proc.stdout)):
                    commit, changes = _parse_record(record)
                    pending_commits.append(
                        (
                            commit["sha"],
                            repo_id,
                            commit["author_name"],
                            commit["author_email"],
                            commit["committer_ts"],
                            commit["parent_sha"],
                            sum(change[1] for change in changes),
                            sum(change[2] for change in changes),
                        )
                    )
                    for change_path, added, removed, source in changes:
                        pending_changes.append(
                            (repo_id, commit["sha"], change_path, added, removed, source)
                        )
                    processed += 1
                    now = time.monotonic()
                    if (
                        now - last_flush >= _FLUSH_INTERVAL_SECONDS
                        or len(pending_changes) >= _MAX_PENDING_CHANGES
                    ):
                        flush()
                        last_flush = now
                returncode = proc.wait()
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            finally:
                proc.stdout.close()

        if returncode != 0:
            raise HistoryError(
                tail_text(stderr_path.read_text(errors="replace"))
                or "git log failed while streaming history."
            )

        flush()
        conn.execute(
            """
            UPDATE repositories
               SET parse_status = 'ready', parse_progress = 100, parse_error = NULL,
                   commit_count = ?, analysed_head = ?, parsed_at = ?,
                   head_commit = ?
             WHERE id = ?
            """,
            (processed, head, _utcnow(), head, repo_id),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
        stderr_path.unlink(missing_ok=True)


def _chunks(stream, size: int = _CHUNK_SIZE) -> Iterator[bytes]:
    while True:
        chunk = stream.read(size)
        if not chunk:
            return
        yield chunk


def _iter_records(chunks: Iterator[bytes]) -> Iterator[bytes]:
    """Split raw stdout into records, each starting with the RS byte."""
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        while buffer.startswith(RS):
            end = buffer.find(RS, 1)
            if end == -1:
                break
            yield buffer[:end]
            buffer = buffer[end:]
    if buffer.startswith(RS):
        yield buffer


def _decode(raw: bytes) -> str:
    # Paths and names are stored as UTF-8; invalid sequences degrade to U+FFFD
    # instead of aborting a long extraction.
    return raw.decode("utf-8", "replace")


def _parse_record(record: bytes) -> tuple[dict, list[tuple[str, int, int, str | None]]]:
    """Parse one RS-prefixed record into a commit dict and file-change tuples.

    Change tuples are ``(path, added, removed, renamed_from)`` where ``path`` is
    the path the change applies to (the new path for renames).
    """
    body = record[1:]
    nul = body.find(NUL)
    if nul == -1:
        raise ParseError("Malformed git log record: missing header terminator.")
    fields = body[:nul].split(US)
    if len(fields) < 5:
        raise ParseError("Malformed git log record: short header.")
    parents = _decode(fields[4]).split()
    commit = {
        "sha": fields[0].decode("ascii", "replace"),
        "author_name": _decode(fields[1]),
        "author_email": _decode(fields[2]),
        "committer_ts": int(fields[3]),
        "parent_sha": parents[0] if parents else None,
    }

    entries = body[nul + 1 :]
    if entries.startswith(b"\n"):  # separator present only when changes follow
        entries = entries[1:]

    changes: list[tuple[str, int, int, str | None]] = []
    segments = entries.split(NUL)
    index = 0
    while index < len(segments):
        segment = segments[index]
        if not segment or segment == b"\n":
            index += 1
            continue
        added_raw, _, remainder = segment.partition(b"\t")
        removed_raw, _, path_raw = remainder.partition(b"\t")
        if path_raw:
            source = None
            index += 1
        else:
            # Rename: "A\tR\t" NUL <old> NUL <new> NUL (old first, then new).
            if index + 2 >= len(segments):
                raise ParseError("Malformed git log record: truncated rename entry.")
            source = _decode(segments[index + 1])
            path_raw = segments[index + 2]
            index += 3
        if added_raw == b"-" or removed_raw == b"-":
            continue  # binary file: excluded from line metrics entirely
        changes.append((_decode(path_raw), int(added_raw), int(removed_raw), source))
    return commit, changes


def commit_page(repo_id: str, offset: int = 0, limit: int = 50) -> dict:
    """A page of commits, newest (committer date) first."""
    with db.get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM commits WHERE repo_id = ?", (repo_id,)
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT sha, author_name, author_email, committer_ts, parent_sha, added, removed
              FROM commits
             WHERE repo_id = ?
             ORDER BY committer_ts DESC, sha DESC
             LIMIT ? OFFSET ?
            """,
            (repo_id, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [dict(row) for row in rows],
    }


def history_stats(repo_id: str) -> dict:
    """Aggregate counters over the extracted history of a repository."""
    with db.get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS commit_count,
                   COUNT(DISTINCT author_email) AS author_count,
                   COALESCE(SUM(added), 0) AS added,
                   COALESCE(SUM(removed), 0) AS removed
              FROM commits
             WHERE repo_id = ?
            """,
            (repo_id,),
        ).fetchone()
        files = conn.execute(
            "SELECT COUNT(DISTINCT path) AS count FROM file_changes WHERE repo_id = ?",
            (repo_id,),
        ).fetchone()["count"]
    return {
        "commit_count": row["commit_count"],
        "author_count": row["author_count"],
        "file_count": files,
        "added": row["added"],
        "removed": row["removed"],
    }

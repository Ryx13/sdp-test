"""Metric computation over the extracted history.

Implements the metric definitions from the project brief for every object
kind, following the same formulas the reference implementation uses:

- File metrics: added (l+), removed (l-), growth (delta = l+ - l-),
  churn (lambda = l+ + l-).
- Directory metrics: subtree rollups of the same quantities; the repository
  itself is the rollup at the root ("/").
- Commit-set metrics: modifications (n, commits with churn > 0 on the
  object), modification frequency (eta = n / |H|) and churn rate
  (rho = lambda / |H|).
- Author metrics: per-author modifications and churn on an object plus
  ownership (omega = author churn / object churn).

The object universe follows the brief's H[F] / H[D]: every path that appears
in any non-merge commit diff is an object -- including the *source* of a
rename (the rename target is recorded as a regular change) -- and
directories are the ancestors of those paths. Objects that were never
changed (a rename source with no other history) have all-zero metrics.

Commit sets are selected with ``since`` (inclusive) and ``until`` (exclusive)
UNIX timestamps: ``H_t`` is ``since=t``, ``H_i,j`` is ``since=i, until=j``.
A manual commit list (``commits``, full SHAs or prefixes) selects exactly those
commits instead (``H_S``). Author identities can be merged beyond .mailmap via
per-repository ``author_aliases`` rows, applied when author rows are produced.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from ..db import get_db

_CACHE_LIMIT = 4

# (repo_id, since, until, parsed_at) -> computed structure. ``parsed_at``
# identifies the analysis generation, so a re-analysis invalidates the cache.
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()


class MetricsNotReadyError(Exception):
    """Raised when metrics are requested before history extraction finished."""


def _object() -> dict:
    return {"added": 0, "removed": 0, "modifications": 0, "authors": {}}


def _contributor() -> dict:
    return {"added": 0, "removed": 0, "modifications": 0}


def _ancestors(path: str) -> tuple[str, ...]:
    """All non-root ancestor directories of ``path`` (outermost first)."""
    parts = path.split("/")
    return tuple("/".join(parts[:i]) for i in range(1, len(parts)))


def _bucket_key(ts: int, bucket: str) -> tuple[str, int]:
    """Bucket label and range start (UNIX seconds, UTC) for a timestamp."""
    moment = datetime.fromtimestamp(ts, tz=timezone.utc)
    if bucket == "day":
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.strftime("%Y-%m-%d"), int(start.timestamp())
    if bucket == "week":
        start = (moment - timedelta(days=moment.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        iso = start.isocalendar()
        return f"{iso.year}-W{iso.week:02d}", int(start.timestamp())
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m"), int(start.timestamp())


def _resolve_commits(conn, repo_id: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Match full SHAs or prefixes against the commits extracted so far.

    Unknown tokens are ignored, an ambiguous prefix selects the smallest
    SHA (deterministic), and duplicates collapse keeping first-seen order.
    """
    known = [
        row["sha"]
        for row in conn.execute("SELECT sha FROM commits WHERE repo_id = ?", (repo_id,))
    ]
    resolved: list[str] = []
    for token in tokens:
        token = token.strip().lower()
        if not token:
            continue
        matches = sorted(sha for sha in known if sha.startswith(token))
        if matches:
            resolved.append(matches[0])
    return tuple(dict.fromkeys(resolved))


def _build(
    repo_id: str,
    since: int | None,
    until: int | None,
    commits: tuple[str, ...] | None = None,
) -> dict:
    """Compute the full metric structure for a commit set (single pass)."""
    commit_query = "SELECT sha, committer_ts, author_name, author_email FROM commits WHERE repo_id = ?"
    commit_params: list = [repo_id]
    change_query = (
        "SELECT f.sha, f.path, f.renamed_from, f.added, f.removed, "
        "c.committer_ts, c.author_name, c.author_email "
        "FROM file_changes f JOIN commits c ON c.sha = f.sha "
        "WHERE f.repo_id = ?"
    )
    change_params: list = [repo_id]
    if since is not None:
        commit_query += " AND committer_ts >= ?"
        change_query += " AND c.committer_ts >= ?"
        commit_params.append(since)
        change_params.append(since)
    if until is not None:
        commit_query += " AND committer_ts < ?"
        change_query += " AND c.committer_ts < ?"
        commit_params.append(until)
        change_params.append(until)

    files: dict[str, dict] = {}
    directories: dict[str, dict] = {}
    root = _object()
    renamed_sources: set[str] = set()
    buckets = {name: {} for name in ("day", "week", "month")}
    ancestor_cache: dict[str, tuple[str, ...]] = {}

    with get_db() as conn:
        if commits is not None:
            resolved = _resolve_commits(conn, repo_id, commits)
            if not resolved:
                return {
                    "commit_count": 0,
                    "repository": _object(),
                    "files": {},
                    "directories": {},
                    "buckets": {name: {} for name in ("day", "week", "month")},
                }
            placeholders = ",".join("?" for _ in resolved)
            commit_query += f" AND sha IN ({placeholders})"
            change_query += f" AND f.sha IN ({placeholders})"
            commit_params.extend(resolved)
            change_params.extend(resolved)
        commit_rows = conn.execute(commit_query, commit_params).fetchall()
        commit_count = len(commit_rows)
        timestamps = {row["sha"]: row["committer_ts"] for row in commit_rows}
        for ts in timestamps.values():
            for name in buckets:
                key, start = _bucket_key(ts, name)
                entry = buckets[name].setdefault(key, {"start": start, "added": 0, "removed": 0, "commits": 0})
                entry["commits"] += 1

        cursor = conn.execute(change_query + " ORDER BY f.sha", change_params)
        current_sha: str | None = None
        touched: set[str] = set()
        root_touched = False
        author = ""
        commit_added = commit_removed = 0
        commit_ts = 0

        def flush_commit() -> None:
            nonlocal touched, root_touched, commit_added, commit_removed
            if root_touched:
                root["modifications"] += 1
                root["authors"][author]["modifications"] += 1
            for directory in touched:
                entry = directories[directory]
                entry["modifications"] += 1
                entry["authors"][author]["modifications"] += 1
            for name in buckets:
                key, _ = _bucket_key(commit_ts, name)
                buckets[name][key]["added"] += commit_added
                buckets[name][key]["removed"] += commit_removed
            touched = set()
            root_touched = False
            commit_added = commit_removed = 0

        for row in cursor:
            sha = row["sha"]
            if sha != current_sha:
                if current_sha is not None:
                    flush_commit()
                current_sha = sha
                author = f"{row['author_name']} <{row['author_email']}>"
                commit_ts = timestamps[sha]
                root["authors"].setdefault(author, _contributor())

            path = row["path"]
            added, removed = row["added"], row["removed"]
            churn = added + removed
            entry = files.setdefault(path, _object())
            entry["added"] += added
            entry["removed"] += removed
            contributor = entry["authors"].setdefault(author, _contributor())
            contributor["added"] += added
            contributor["removed"] += removed
            if row["renamed_from"]:
                renamed_sources.add(row["renamed_from"])

            if churn > 0:
                entry["modifications"] += 1
                contributor["modifications"] += 1
                commit_added += added
                commit_removed += removed
                root["added"] += added
                root["removed"] += removed
                root_contributor = root["authors"][author]
                root_contributor["added"] += added
                root_contributor["removed"] += removed
                root_touched = True
                try:
                    ancestors = ancestor_cache[path]
                except KeyError:
                    ancestors = ancestor_cache[path] = _ancestors(path)
                for directory in ancestors:
                    dir_entry = directories.setdefault(directory, _object())
                    dir_entry["added"] += added
                    dir_entry["removed"] += removed
                    dir_contributor = dir_entry["authors"].setdefault(author, _contributor())
                    dir_contributor["added"] += added
                    dir_contributor["removed"] += removed
                    touched.add(directory)

        if current_sha is not None:
            flush_commit()

    # The universe includes rename sources even when they have no other
    # history; such objects keep all-zero metrics.
    for source in renamed_sources:
        files.setdefault(source, _object())
    for path in files:
        for directory in _ancestors(path):
            directories.setdefault(directory, _object())

    return {
        "commit_count": commit_count,
        "repository": root,
        "files": files,
        "directories": directories,
        "buckets": buckets,
    }


def _get(repo_id: str, since: int | None, until: int | None,
         commits: tuple[str, ...] | None = None) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT parse_status, parsed_at FROM repositories WHERE id = ?", (repo_id,)
        ).fetchone()
    if row is None:
        raise KeyError(repo_id)
    if row["parse_status"] != "ready":
        raise MetricsNotReadyError(
            "The history of this repository has not been extracted (yet)."
        )
    key = (repo_id, since, until, commits, row["parsed_at"])
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    data = _build(repo_id, since, until, commits)
    with _cache_lock:
        _cache[key] = data
        while len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
    return data


def _all_metrics(entry: dict, commit_count: int) -> dict:
    added, removed = entry["added"], entry["removed"]
    modifications = entry["modifications"]
    churn = added + removed
    # Rates are computed as ``value * (1 / |H|)`` rather than ``value / |H|``:
    # this reproduces the reference implementation's floating-point results
    # exactly (the two forms can differ in the last ulp).
    inverse = 1.0 / commit_count if commit_count else 0.0
    return {
        "added": added,
        "removed": removed,
        "growth": added - removed,
        "churn": churn,
        "modifications": modifications,
        "modification_frequency": modifications * inverse,
        "churn_rate": churn * inverse,
    }


def _resolve_alias(identity: str, aliases: dict[str, str]) -> str:
    """Follow an alias chain to its final target, guarding against cycles."""
    seen = {identity}
    while identity in aliases:
        identity = aliases[identity]
        if identity in seen:
            break
        seen.add(identity)
    return identity


def _author_metrics(entry: dict, aliases: dict[str, str] | None = None) -> list[dict]:
    total = entry["added"] + entry["removed"]
    contributions = entry["authors"]
    if aliases and contributions:
        # Merge alias identities into their targets on a copy, so the cached
        # structure stays alias-independent (aliases can change per request).
        merged: dict[str, dict] = {}
        for author, contribution in contributions.items():
            target = _resolve_alias(author, aliases)
            bucket = merged.setdefault(target, _contributor())
            for key in ("added", "removed", "modifications"):
                bucket[key] += contribution[key]
        contributions = merged
    rows = []
    for author, contribution in contributions.items():
        added, removed = contribution["added"], contribution["removed"]
        churn = added + removed
        if churn == 0:
            # Authors who never changed anything (rename-only touches, zero
            # line changes) carry no metrics for this object.
            continue
        rows.append(
            {
                "author": author,
                "added": added,
                "removed": removed,
                "growth": added - removed,
                "churn": churn,
                "modifications": contribution["modifications"],
                "ownership": churn / total if total else 0.0,
            }
        )
    rows.sort(key=lambda row: (-row["churn"], row["author"]))
    return rows


def _require_repo(repo_id: str) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    if row is None:
        raise KeyError(repo_id)


def load_aliases(repo_id: str) -> dict[str, str]:
    """Manual author merges (on top of .mailmap), keyed by raw identity."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT alias, target FROM author_aliases WHERE repo_id = ?", (repo_id,)
        ).fetchall()
    return {row["alias"]: row["target"] for row in rows}


def author_aliases(repo_id: str) -> dict:
    """The configured merges plus every identity seen during extraction."""
    _require_repo(repo_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT author_name, author_email FROM commits WHERE repo_id = ?",
            (repo_id,),
        ).fetchall()
    identities = sorted(f"{row['author_name']} <{row['author_email']}>" for row in rows)
    return {"aliases": load_aliases(repo_id), "identities": identities}


def set_author_alias(repo_id: str, alias: str, target: str) -> dict:
    _require_repo(repo_id)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO author_aliases (repo_id, alias, target) VALUES (?, ?, ?) "
            "ON CONFLICT(repo_id, alias) DO UPDATE SET target = excluded.target",
            (repo_id, alias, target),
        )
    return author_aliases(repo_id)


def delete_author_alias(repo_id: str, alias: str) -> dict:
    _require_repo(repo_id)
    with get_db() as conn:
        conn.execute(
            "DELETE FROM author_aliases WHERE repo_id = ? AND alias = ?", (repo_id, alias)
        )
    return author_aliases(repo_id)


def _format_metric(value: float) -> str:
    """Format a metric float exactly like the reference implementation.

    Shortest round-trip digits with ryu-style notation: integral values keep
    a fractional part (``0.0``, ``1.0``), positional notation is used while
    the decimal exponent lies in [-5, 16), and scientific notation with a
    minimal unpadded exponent otherwise (``6.208981913235687e-7``).
    """
    if value == 0:
        return "0.0"
    text = repr(value)  # shortest round-trip representation
    mantissa, _, exponent = text.partition("e")
    scale = int(exponent) if exponent else 0
    integer_part, _, fraction_part = mantissa.lstrip("-").partition(".")
    digits = (integer_part + fraction_part).lstrip("0")
    # value == digits × 10**power, exponent10 is the scientific exponent
    power = scale - len(fraction_part)
    exponent10 = power + len(digits) - 1
    if -5 <= exponent10 < 16:
        if exponent10 >= 0:
            before = digits[: exponent10 + 1].ljust(exponent10 + 1, "0")
            after = digits[exponent10 + 1 :]
            return f"{before}.{after}" if after else f"{before}.0"
        return "0." + "0" * (-exponent10 - 1) + digits
    shortened = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    return f"{shortened}e{exponent10}"


_SORTS = {
    "path": lambda row: row["path"],
    "added": lambda row: row["added"],
    "removed": lambda row: row["removed"],
    "growth": lambda row: row["growth"],
    "churn": lambda row: row["churn"],
    "modifications": lambda row: row["modifications"],
    "churn_rate": lambda row: row["churn_rate"],
    "modification_frequency": lambda row: row["modification_frequency"],
}


def _page(entries: dict, commit_count: int, *, sort: str, order: str, limit: int, offset: int, query: str | None) -> dict:
    items = [
        {"path": path, **_all_metrics(entry, commit_count)}
        for path, entry in entries.items()
        if not query or query.lower() in path.lower()
    ]
    key = _SORTS.get(sort, _SORTS["churn"])
    items.sort(key=key, reverse=(order == "desc"))
    total = len(items)
    return {"total": total, "offset": offset, "limit": limit, "items": items[offset : offset + limit]}


def repository_metrics(repo_id: str, since: int | None = None, until: int | None = None,
                       commits: tuple[str, ...] | None = None) -> dict:
    data = _get(repo_id, since, until, commits)
    return {
        "commit_count": data["commit_count"],
        "metrics": _all_metrics(data["repository"], data["commit_count"]),
        "authors": _author_metrics(data["repository"], load_aliases(repo_id)),
    }


def files_page(
    repo_id: str,
    *,
    since: int | None = None,
    until: int | None = None,
    commits: tuple[str, ...] | None = None,
    sort: str = "churn",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
) -> dict:
    data = _get(repo_id, since, until, commits)
    return _page(data["files"], data["commit_count"], sort=sort, order=order, limit=limit, offset=offset, query=query)


def directories_page(
    repo_id: str,
    *,
    since: int | None = None,
    until: int | None = None,
    commits: tuple[str, ...] | None = None,
    sort: str = "churn",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    query: str | None = None,
) -> dict:
    data = _get(repo_id, since, until, commits)
    return _page(data["directories"], data["commit_count"], sort=sort, order=order, limit=limit, offset=offset, query=query)


def author_metrics(repo_id: str, since: int | None = None, until: int | None = None,
                   commits: tuple[str, ...] | None = None) -> list[dict]:
    data = _get(repo_id, since, until, commits)
    return _author_metrics(data["repository"], load_aliases(repo_id))


def object_detail(repo_id: str, path: str, since: int | None = None, until: int | None = None,
                  commits: tuple[str, ...] | None = None) -> dict | None:
    data = _get(repo_id, since, until, commits)
    aliases = load_aliases(repo_id)
    if path == "/":
        return {
            "path": "/",
            "object_type": "repository",
            "metrics": _all_metrics(data["repository"], data["commit_count"]),
            "authors": _author_metrics(data["repository"], aliases),
        }
    for object_type, entries in (("file", data["files"]), ("directory", data["directories"])):
        entry = entries.get(path)
        if entry is not None:
            return {
                "path": path,
                "object_type": object_type,
                "metrics": _all_metrics(entry, data["commit_count"]),
                "authors": _author_metrics(entry, aliases),
            }
    return None


def timeline(
    repo_id: str,
    *,
    since: int | None = None,
    until: int | None = None,
    commits: tuple[str, ...] | None = None,
    bucket: str = "month",
) -> dict:
    data = _get(repo_id, since, until, commits)
    entries = data["buckets"].get(bucket) or data["buckets"]["month"]
    items = [
        {
            "key": key,
            "start": entry["start"],
            "added": entry["added"],
            "removed": entry["removed"],
            "churn": entry["added"] + entry["removed"],
            "commits": entry["commits"],
        }
        for key, entry in entries.items()
    ]
    items.sort(key=lambda item: item["start"])
    return {"bucket": bucket, "items": items}


def export_rows(repo_id: str, name: str, since: int | None = None, until: int | None = None,
                commits: tuple[str, ...] | None = None):
    """Yield CSV rows in the reference format used for metric validation."""
    from ..services import catalog

    repo = catalog.get_repository(repo_id)
    if repo is None:
        raise KeyError(repo_id)
    data = _get(repo_id, since, until, commits)
    commit_count = data["commit_count"]
    ref_sha = repo["analysed_head"] or ""
    if commits is not None:
        commit_set = "manual" if since is None and until is None else "manual+window"
    elif since is None and until is None:
        commit_set = "all"
    else:
        commit_set = f"custom:{since or ''}:{until or ''}"
    aliases = load_aliases(repo_id)

    yield [
        "repo", "ref_sha", "commit_set", "commit_count", "object_type", "path",
        "author", "added", "removed", "growth", "churn", "modifications",
        "modification_frequency", "churn_rate", "ownership",
    ]

    def rows_for(object_type: str, path: str, entry: dict):
        metrics = _all_metrics(entry, commit_count)
        yield [
            name, ref_sha, commit_set, commit_count, object_type, path, "ALL",
            metrics["added"], metrics["removed"], metrics["growth"], metrics["churn"],
            metrics["modifications"], _format_metric(metrics["modification_frequency"]),
            _format_metric(metrics["churn_rate"]), "",
        ]
        for author in _author_metrics(entry, aliases):
            yield [
                name, ref_sha, commit_set, commit_count, object_type, path,
                author["author"], author["added"], author["removed"], author["growth"],
                author["churn"], author["modifications"], "", "",
                _format_metric(author["ownership"]),
            ]

    yield from rows_for("repository", "/", data["repository"])
    for path in sorted(data["directories"]):
        yield from rows_for("directory", path, data["directories"][path])
    for path in sorted(data["files"]):
        yield from rows_for("file", path, data["files"][path])

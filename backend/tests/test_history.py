"""History extraction semantics, verified against hand-built repository fixtures.

Each scenario mirrors a rule from the brief: non-merge commits only, renames at
50% detection, binary exclusion, deletions as removals, mailmap-aware author
identities and committer dates for commit sets.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.history import _iter_records, _parse_record

from .conftest import make_zip

# ---------------------------------------------------------------------------
# Fixture: a repository whose every commit exercises one extraction rule.
# ---------------------------------------------------------------------------


def _git(repo: Path, args: list[str], *, when: str | None = None, name="Ada Lovelace",
         email="ada@example.com") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, env=env
    )


def _stage(repo: Path) -> None:
    _git(repo, ["add", "-A"])


def _commit(repo: Path, message: str, when: str, *, name="Ada Lovelace",
            email="ada@example.com", allow_empty=False) -> str:
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _git(repo, args, when=when, name=name, email=email)
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


@pytest.fixture()
def history_repo(tmp_path: Path) -> dict:
    """Repository with 10 non-merge commits + 1 merge, exercising every rule."""
    repo = tmp_path / "history-lab"
    repo.mkdir()
    _git(repo, ["init", "-b", "main"])

    (repo / "README.md").write_text("# hi\n")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("a\nb\n")
    _stage(repo)
    c1 = _commit(repo, "c1 initial", "2024-01-01T10:00:00+00:00")  # +3

    (repo / "README.md").write_text("# hi\nmore\n")  # +1
    (repo / "utils.py").write_text("x\n")  # +1
    _stage(repo)
    c2 = _commit(repo, "c2 edit and add", "2024-01-02T10:00:00+00:00")

    (repo / "src" / "app.py").unlink()  # -2
    _stage(repo)
    c3 = _commit(
        repo, "c3 delete app", "2024-01-03T10:00:00+00:00",
        name="Bob Stone", email="bob@example.com",
    )

    (repo / "docs").mkdir()
    (repo / "docs" / "README.md").write_text("# hi\nmore\n")
    (repo / "README.md").unlink()  # pure rename, content identical
    _stage(repo)
    c4 = _commit(repo, "c4 pure rename", "2024-01-04T10:00:00+00:00")

    (repo / "docs" / "README.md").write_text("# hi\nmore\nline3\n")  # +1 on new path
    _stage(repo)
    c5 = _commit(
        repo, "c5 edit after rename", "2024-01-05T10:00:00+00:00",
        name="Bob Stone", email="bob@example.com",
    )

    (repo / "data.bin").write_bytes(b"\x00\x01\x02BIN\x00")  # binary: excluded
    _stage(repo)
    c6 = _commit(repo, "c6 binary", "2024-01-06T10:00:00+00:00")

    (repo / "src" / "with space.txt").write_text("hello\n")  # +1
    (repo / "src" / "ünïcode.txt").write_text("wörld\n")  # +1
    _stage(repo)
    c7 = _commit(repo, "c7 odd names", "2024-01-07T10:00:00+00:00")

    c8 = _commit(repo, "c8 empty", "2024-01-08T10:00:00+00:00", allow_empty=True)

    # A side branch merged back: the side commit is part of H̄, the merge is not.
    _git(repo, ["checkout", "-b", "side"])
    (repo / "side.txt").write_text("side\n")  # +1
    _stage(repo)
    c_side = _commit(repo, "side commit", "2024-01-09T10:00:00+00:00")
    _git(repo, ["checkout", "main"])
    (repo / "main.txt").write_text("main\n")  # +1
    _stage(repo)
    c_main = _commit(repo, "main commit", "2024-01-10T10:00:00+00:00")
    _git(repo, ["merge", "--no-ff", "side", "-m", "merge side"], when="2024-01-11T10:00:00+00:00")
    merge = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()

    return {
        "path": repo,
        "head": merge,  # the merge commit IS HEAD, it is just not in H̄
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5,
        "c6": c6, "c7": c7, "c8": c8, "c_side": c_side, "c_main": c_main,
        "merge": merge,
        # hand-computed expectations
        "count": 10,
        "added": 10,
        "removed": 2,
        "paths": 8,  # data.bin is excluded; every other path touched >= once
        "authors": 2,
    }


def _wait_for_parse(client: TestClient, repo_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/repositories/{repo_id}").json()
        if body["parse_status"] in {"ready", "error"}:
            return body
        time.sleep(0.05)
    raise AssertionError("history extraction did not finish in time")


@pytest.fixture()
def analysed(client: TestClient, upload_zip, tmp_path: Path, history_repo: dict) -> dict:
    archive = make_zip(history_repo["path"], tmp_path / "history-lab.zip", arc_prefix="history-lab")
    created = upload_zip(archive, filename="history-lab.zip").json()
    final = _wait_for_parse(client, created["id"])
    assert final["parse_status"] == "ready", final["parse_error"]
    return {**history_repo, "id": created["id"], "detail": final}


def _rows(data_dir: Path, query: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(data_dir / "rat.sqlite3")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def _changes(data_dir: Path, repo_id: str, sha: str) -> list[tuple]:
    rows = _rows(
        data_dir,
        "SELECT path, added, removed, renamed_from FROM file_changes"
        " WHERE repo_id = ? AND sha = ? ORDER BY path",
        (repo_id, sha),
    )
    return [(r["path"], r["added"], r["removed"], r["renamed_from"]) for r in rows]


def _git_reference_totals(repo: Path) -> tuple[int, int]:
    """Independent totals straight from git numstat (no -z, no renames split)."""
    result = subprocess.run(
        ["git", "log", "--no-merges", "-M50%", "--numstat", "--format="],
        cwd=str(repo), check=True, capture_output=True, text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    added = removed = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        first, second, _ = parts
        if first == "-" or second == "-":
            continue  # binary
        added += int(first)
        removed += int(second)
    return added, removed


# ---------------------------------------------------------------------------
# Extraction semantics
# ---------------------------------------------------------------------------


def test_analysis_runs_after_upload_and_matches_hand_computed_totals(
    client: TestClient, analysed: dict
):
    detail = analysed["detail"]
    assert detail["commit_count"] == analysed["count"]
    assert detail["analysed_head"] == analysed["head"]
    assert detail["parsed_at"]
    assert detail["parse_progress"] == 100

    summary = client.get(f"/api/repositories/{analysed['id']}/summary").json()
    assert summary == {
        "commit_count": analysed["count"],
        "author_count": analysed["authors"],
        "file_count": analysed["paths"],
        "added": analysed["added"],
        "removed": analysed["removed"],
    }
    # Double-check against git itself: an independent implementation of the
    # same rules must produce the same totals.
    reference = _git_reference_totals(analysed["path"])
    assert reference == (summary["added"], summary["removed"])


def test_upload_response_already_reports_parsing(client: TestClient, upload_zip, tmp_path, history_repo):
    archive = make_zip(history_repo["path"], tmp_path / "h.zip", arc_prefix="history-lab")
    created = upload_zip(archive, filename="h.zip").json()
    assert created["parse_status"] == "parsing"


def test_pure_rename_preserves_metrics_and_moves_path(client: TestClient, analysed: dict, data_dir):
    # The rename commit itself contributes no lines to either path.
    changes = _changes(data_dir, analysed["id"], analysed["c4"])
    assert changes == [("docs/README.md", 0, 0, "README.md")]
    row = _rows(
        data_dir, "SELECT added, removed FROM commits WHERE sha = ?", (analysed["c4"],)
    )[0]
    assert (row["added"], row["removed"]) == (0, 0)
    # Edits after the rename attach to the new path only.
    assert _changes(data_dir, analysed["id"], analysed["c5"]) == [
        ("docs/README.md", 1, 0, None)
    ]


def test_deletion_is_recorded_as_removal_on_the_deleted_path(client: TestClient, analysed: dict, data_dir):
    changes = _changes(data_dir, analysed["id"], analysed["c3"])
    assert changes == [("src/app.py", 0, 2, None)]
    row = _rows(
        data_dir, "SELECT added, removed FROM commits WHERE sha = ?", (analysed["c3"],)
    )[0]
    assert (row["added"], row["removed"]) == (0, 2)


def test_binary_files_are_excluded_entirely(client: TestClient, analysed: dict, data_dir):
    binary_rows = _rows(
        data_dir,
        "SELECT 1 FROM file_changes WHERE repo_id = ? AND path = 'data.bin'",
        (analysed["id"],),
    )
    assert binary_rows == []
    row = _rows(
        data_dir, "SELECT added, removed FROM commits WHERE sha = ?", (analysed["c6"],)
    )[0]
    assert (row["added"], row["removed"]) == (0, 0)


def test_odd_paths_are_preserved_verbatim(client: TestClient, analysed: dict, data_dir):
    paths = {
        r["path"]
        for r in _rows(
            data_dir, "SELECT DISTINCT path FROM file_changes WHERE repo_id = ?", (analysed["id"],)
        )
    }
    assert "src/with space.txt" in paths
    assert "src/ünïcode.txt" in paths
    assert "README.md" in paths  # the pre-rename path keeps its own history
    assert "docs/README.md" in paths


def test_empty_commit_is_extracted_with_zero_changes(client: TestClient, analysed: dict, data_dir):
    rows = _rows(
        data_dir, "SELECT added, removed FROM commits WHERE sha = ?", (analysed["c8"],)
    )
    assert len(rows) == 1
    assert (rows[0]["added"], rows[0]["removed"]) == (0, 0)
    assert _changes(data_dir, analysed["id"], analysed["c8"]) == []


def test_merge_commits_are_excluded_from_history(client: TestClient, analysed: dict, data_dir):
    merged = _rows(
        data_dir, "SELECT 1 FROM commits WHERE sha = ?", (analysed["merge"],)
    )
    assert merged == []
    # ...but the side-branch commit merged in is part of the H-bar set.
    side = _rows(
        data_dir, "SELECT added FROM commits WHERE sha = ?", (analysed["c_side"],)
    )
    assert len(side) == 1 and side[0]["added"] == 1


def test_commit_page_is_ordered_newest_first_and_paginates(client: TestClient, analysed: dict):
    first = client.get(f"/api/repositories/{analysed['id']}/commits", params={"limit": 3}).json()
    assert first["total"] == analysed["count"]
    assert [item["sha"] for item in first["items"]][0] == analysed["c_main"]

    second = client.get(
        f"/api/repositories/{analysed['id']}/commits", params={"limit": 3, "offset": 3}
    ).json()
    assert [item["sha"] for item in first["items"]] and not (
        {item["sha"] for item in first["items"]} & {item["sha"] for item in second["items"]}
    )

    everything = client.get(
        f"/api/repositories/{analysed['id']}/commits", params={"limit": 500}
    ).json()["items"]
    shas = {item["sha"] for item in everything}
    assert analysed["merge"] not in shas
    assert len(shas) == analysed["count"]


def test_reanalysis_replaces_data_idempotently(client: TestClient, analysed: dict, data_dir):
    before = client.get(f"/api/repositories/{analysed['id']}/summary").json()
    changes_before = _rows(
        data_dir, "SELECT COUNT(*) AS c FROM file_changes WHERE repo_id = ?", (analysed["id"],)
    )[0]["c"]

    response = client.post(f"/api/repositories/{analysed['id']}/analyse")
    assert response.status_code == 202, response.text
    _wait_for_parse(client, analysed["id"])

    after = client.get(f"/api/repositories/{analysed['id']}/summary").json()
    changes_after = _rows(
        data_dir, "SELECT COUNT(*) AS c FROM file_changes WHERE repo_id = ?", (analysed["id"],)
    )[0]["c"]
    assert after == before
    assert changes_after == changes_before


def test_analyse_conflict_while_parsing(client: TestClient, analysed: dict, data_dir):
    conn = sqlite3.connect(data_dir / "rat.sqlite3")
    conn.execute("UPDATE repositories SET parse_status = 'parsing' WHERE id = ?", (analysed["id"],))
    conn.commit()
    conn.close()
    response = client.post(f"/api/repositories/{analysed['id']}/analyse")
    assert response.status_code == 409


def test_analyse_rejects_repositories_that_are_not_ready(client: TestClient, analysed: dict, data_dir):
    conn = sqlite3.connect(data_dir / "rat.sqlite3")
    conn.execute("UPDATE repositories SET status = 'cloning' WHERE id = ?", (analysed["id"],))
    conn.commit()
    conn.close()
    response = client.post(f"/api/repositories/{analysed['id']}/analyse")
    assert response.status_code == 400


def test_unknown_repository_endpoints_return_404(client: TestClient):
    assert client.post("/api/repositories/nope/analyse").status_code == 404
    assert client.get("/api/repositories/nope/commits").status_code == 404
    assert client.get("/api/repositories/nope/summary").status_code == 404


def test_clone_ingestion_also_runs_analysis(client: TestClient, remote_url: str):
    created = client.post("/api/repositories/clone", json={"url": remote_url}).json()
    final = _wait_for_parse(client, created["id"], timeout=60.0)
    assert final["status"] == "ready", final["error"]
    assert final["parse_status"] == "ready", final["parse_error"]
    assert final["commit_count"] == 2  # the sample repository has two commits


# ---------------------------------------------------------------------------
# Parser unit tests (byte-level layout)
# ---------------------------------------------------------------------------


def test_parse_record_handles_rename_then_binary():
    record = (
        b"\x1e" + b"a" * 40 + b"\x1fAda\x1fada@example.com\x1f1700000000\x1f" + b"b" * 40 + b"\x00"
        b"\n0\t0\t\x00old.txt\x00new.txt\x00-\t-\tblob.bin\x00"
    )
    commit, changes = _parse_record(record)
    assert commit["sha"] == "a" * 40
    assert commit["parent_sha"] == "b" * 40
    assert changes == [("new.txt", 0, 0, "old.txt")]  # binary entry skipped


def test_parse_record_handles_bodyless_record_and_root_commit():
    record = b"\x1e" + b"c" * 40 + b"\x1fAda\x1fada@example.com\x1f1700000000\x1f\x00"
    commit, changes = _parse_record(record)
    assert commit["parent_sha"] is None
    assert changes == []


def test_iter_records_reassembles_records_across_chunk_boundaries():
    chunks = iter([b"\x1e" + b"r1\x00\n1\t0\ta", b"\x1e" + b"r2\x00"])
    assert list(_iter_records(chunks)) == [b"\x1e" + b"r1\x00\n1\t0\ta", b"\x1e" + b"r2\x00"]


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def test_migration_upgrades_a_version_1_database(tmp_path: Path, monkeypatch):
    data = tmp_path / "legacy-data"
    data.mkdir()
    conn = sqlite3.connect(data / "rat.sqlite3")
    conn.executescript(
        """
        CREATE TABLE repositories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            default_branch TEXT,
            head_commit TEXT,
            size_bytes INTEGER,
            created_at TEXT NOT NULL
        );
        INSERT INTO repositories (id, name, source_type, path, status, created_at)
        VALUES ('legacy', 'old', 'zip', '/nowhere', 'ready', '2024-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("RAT_DATA_DIR", str(data))
    from app import db

    db.init_db()

    conn = sqlite3.connect(data / "rat.sqlite3")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM repositories WHERE id = 'legacy'").fetchone()
        assert row["parse_status"] == "none"
        assert row["parse_progress"] == 0
        assert row["commit_count"] is None
        # The new tables exist and are queryable.
        assert conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM file_changes").fetchone()[0] == 0
    finally:
        conn.close()

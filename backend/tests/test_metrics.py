"""Metric computation semantics, verified against a hand-computed fixture.

The fixture exercises every metric category from the brief: file metrics
(l+, l-, delta, lambda), directory rollups, the repository rollup, commit-set
metrics (n, eta, rho) over the full history and over time windows, author
metrics (n, omega) including .mailmap identity merging, the rename-source
object universe rule (zero-metric objects), and the reference CSV export
format. Every expected value below is hand-computed from the fixture's known
line counts.

Formulas match the reference implementation (reproduced exactly, including
floating-point arithmetic, against the provided sample repositories):

* ``eta = n * (1 / |H|)`` and ``rho = lambda * (1 / |H|)`` — multiplication by
  the reciprocal of the commit-set size;
* ``omega = lambda_a / lambda`` — plain division;
* ``n`` counts commits with churn > 0; merge commits are never part of H.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.metrics import _format_metric

from .conftest import make_zip

# ---------------------------------------------------------------------------
# Fixture: a repository whose every commit exercises one metric rule.
# ---------------------------------------------------------------------------

MAILMAP = "Bob <bob@example.com> <robert@example.com>\nBob <bob@example.com> <bob@example.com>\n"


def _git(repo: Path, args: list[str], *, when: str | None = None, name="Ada Lovelace",
         email="ada@example.com", check=True) -> subprocess.CompletedProcess:
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
        ["git", *args], cwd=str(repo), check=check, capture_output=True, text=True, env=env
    )


def _stage(repo: Path) -> None:
    _git(repo, ["add", "-A"])


def _commit(repo: Path, message: str, when: str, *, name="Ada Lovelace",
            email="ada@example.com") -> str:
    _git(repo, ["commit", "-m", message], when=when, name=name, email=email)
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


@pytest.fixture()
def metrics_repo(tmp_path: Path) -> dict:
    """10 commits (9 non-merge + 1 merge) with hand-computed metrics.

    Commit-by-commit line changes (added/removed):

    * c1 Ada:    .mailmap +2, README.md +1, src/app.py +3, src/lib/util.py +2
    * c2 Ada:    README.md +1/-1, src/app.py +2/-1
    * c3 Robert: src/lib/util.py +1/-1          (mailmapped to Bob)
    * c4 Bobby:  src/app.py +4, init.txt +1     (mailmapped to Bob)
    * c5 Robert: docs/notes.md +2               (mailmapped to Bob)
    * side Ada:  init.txt +1/-1
    * main Ada:  init.txt +1/-1
    * merge:     conflict resolution adds seed.txt (NEVER counted: merge)
    * c7 Ada:    seed.txt -> archive/seed.txt   (pure rename, zero churn)
    * c8 Bob:    docs/notes.md rewritten +5/-2

    Repository totals: added 26, removed 7, growth 19, churn 33, n 8, |H| 9.
    """
    repo = tmp_path / "metrics-lab"
    repo.mkdir()
    _git(repo, ["init", "-b", "main"])

    (repo / ".mailmap").write_text(MAILMAP)
    (repo / "README.md").write_text("# hi\n")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("a\nb\nc\n")
    (repo / "src" / "lib").mkdir()
    (repo / "src" / "lib" / "util.py").write_text("x\ny\n")
    _stage(repo)
    _commit(repo, "c1 initial", "2024-01-01T10:00:00+00:00")

    (repo / "README.md").write_text("# hello\n")  # +1/-1
    (repo / "src" / "app.py").write_text("a\nb\nc2\nd\n")  # +2/-1
    _stage(repo)
    _commit(repo, "c2 edits", "2024-01-02T10:00:00+00:00")

    (repo / "src" / "lib" / "util.py").write_text("X\ny\n")  # +1/-1
    _stage(repo)
    _commit(repo, "c3 robert", "2024-01-08T10:00:00+00:00",
            name="Robert", email="robert@example.com")

    (repo / "src" / "app.py").write_text("a\nb\nc2\nd\ne\nf\ng\nh\n")  # +4
    (repo / "init.txt").write_text("one\n")  # +1
    _stage(repo)
    _commit(repo, "c4 bobby", "2024-01-09T10:00:00+00:00",
            name="Bobby", email="bob@example.com")

    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text("n1\nn2\n")  # +2
    _stage(repo)
    _commit(repo, "c5 robert notes", "2024-02-05T10:00:00+00:00",
            name="Robert", email="robert@example.com")

    # A side branch merged back; the merge commit itself is not part of H.
    _git(repo, ["checkout", "-b", "side"])
    (repo / "init.txt").write_text("two\n")  # +1/-1
    _stage(repo)
    c_side = _commit(repo, "side edit", "2024-02-06T09:00:00+00:00")
    _git(repo, ["checkout", "main"])
    (repo / "init.txt").write_text("three\n")  # +1/-1
    _stage(repo)
    c_main = _commit(repo, "main edit", "2024-02-06T10:00:00+00:00")
    merge = _git(repo, ["merge", "side", "-m", "merge side"], check=False)

    # Conflict resolution: keep main's init.txt and add a brand-new file.
    # Because the merge commit is excluded from H, seed.txt has no history of
    # its own -- it only exists as the source of the later rename.
    (repo / "init.txt").write_text("three\n")
    (repo / "seed.txt").write_text("s1\ns2\ns3\n")  # +3, but merge: not counted
    _stage(repo)
    _commit(repo, "merge side", "2024-02-06T12:00:00+00:00")
    merge_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()

    (repo / "archive").mkdir()
    _git(repo, ["mv", "seed.txt", "archive/seed.txt"])  # pure rename, 0/0
    c7 = _commit(repo, "c7 move seed", "2024-02-10T10:00:00+00:00")

    (repo / "docs" / "notes.md").write_text("m1\nm2\nm3\nm4\nm5\n")  # +5/-2
    _stage(repo)
    c8 = _commit(repo, "c8 rewrite notes", "2024-03-01T10:00:00+00:00",
                 name="Bob", email="bob@example.com")

    return {
        "path": repo,
        "head": c8,
        "c_side": c_side,
        "c_main": c_main,
        "merge": merge_sha,
        "c7": c7,
        "c8": c8,
        "merge_conflict": merge,  # non-zero exit expected
        "count": 9,
        "added": 26,
        "removed": 7,
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
def lab(client: TestClient, upload_zip, tmp_path: Path, metrics_repo: dict) -> dict:
    assert metrics_repo["merge_conflict"].returncode != 0  # merge conflicted
    archive = make_zip(metrics_repo["path"], tmp_path / "metrics-lab.zip", arc_prefix="metrics-lab")
    created = upload_zip(archive, filename="metrics-lab.zip", name="metrics-lab").json()
    final = _wait_for_parse(client, created["id"])
    assert final["parse_status"] == "ready", final["parse_error"]
    assert final["commit_count"] == metrics_repo["count"]
    return {**metrics_repo, "id": created["id"], "detail": final}


ADA = "Ada Lovelace <ada@example.com>"
BOB = "Bob <bob@example.com>"
FEB_1 = int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp())
JAN_8 = int(datetime(2024, 1, 8, tzinfo=timezone.utc).timestamp())
JAN_10 = int(datetime(2024, 1, 10, tzinfo=timezone.utc).timestamp())

# ---------------------------------------------------------------------------
# Repository + author metrics
# ---------------------------------------------------------------------------


def test_repository_metrics_all_time(client: TestClient, lab: dict):
    body = client.get(f"/api/repositories/{lab['id']}/metrics/repository").json()
    assert body["commit_count"] == 9
    assert body["metrics"] == {
        "added": 26, "removed": 7, "growth": 19, "churn": 33, "modifications": 8,
        "modification_frequency": 0.8888888888888888,  # 8 * (1/9)
        "churn_rate": 3.6666666666666665,  # 33 * (1/9)
    }
    # Bob's raw identities (Robert, Bobby, Bob) are merged by .mailmap.
    assert body["authors"] == [
        {"author": ADA, "added": 13, "removed": 4, "growth": 9, "churn": 17,
         "modifications": 4, "ownership": 0.5151515151515151},
        {"author": BOB, "added": 13, "removed": 3, "growth": 10, "churn": 16,
         "modifications": 4, "ownership": 0.48484848484848486},
    ]


def test_author_metrics_endpoint_matches_repository(client: TestClient, lab: dict):
    repository = client.get(f"/api/repositories/{lab['id']}/metrics/repository").json()
    authors = client.get(f"/api/repositories/{lab['id']}/metrics/authors").json()
    assert authors == repository["authors"]
    assert [row["author"] for row in authors] == [ADA, BOB]


def test_commit_set_since_is_inclusive(client: TestClient, lab: dict):
    body = client.get(
        f"/api/repositories/{lab['id']}/metrics/repository", params={"since": FEB_1}
    ).json()
    assert body["commit_count"] == 5  # c5, side, main, rename, c8
    assert body["metrics"] == {
        "added": 9, "removed": 4, "growth": 5, "churn": 13, "modifications": 4,
        "modification_frequency": 4 * (1 / 5), "churn_rate": 13 * (1 / 5),
    }
    assert body["authors"] == [
        {"author": BOB, "added": 7, "removed": 2, "growth": 5, "churn": 9,
         "modifications": 2, "ownership": 9 / 13},
        {"author": ADA, "added": 2, "removed": 2, "growth": 0, "churn": 4,
         "modifications": 2, "ownership": 4 / 13},
    ]


def test_commit_set_until_is_exclusive(client: TestClient, lab: dict):
    body = client.get(
        f"/api/repositories/{lab['id']}/metrics/repository", params={"until": FEB_1}
    ).json()
    assert body["commit_count"] == 4  # c1..c4
    assert body["metrics"] == {
        "added": 17, "removed": 3, "growth": 14, "churn": 20, "modifications": 4,
        "modification_frequency": 1.0, "churn_rate": 5.0,
    }
    assert [(row["author"], row["churn"], row["ownership"]) for row in body["authors"]] == [
        (ADA, 13, 13 / 20),
        (BOB, 7, 7 / 20),  # c3 +1/-1 and c4 +4/+1
    ]


def test_commit_set_between_two_instants(client: TestClient, lab: dict):
    body = client.get(
        f"/api/repositories/{lab['id']}/metrics/repository",
        params={"since": JAN_8, "until": JAN_10},
    ).json()
    assert body["commit_count"] == 2  # c3 (Jan 8) and c4 (Jan 9)
    assert body["metrics"] == {
        "added": 6, "removed": 1, "growth": 5, "churn": 7, "modifications": 2,
        "modification_frequency": 1.0, "churn_rate": 3.5,
    }


def test_reanalysis_keeps_metrics_consistent(client: TestClient, lab: dict):
    before = client.get(f"/api/repositories/{lab['id']}/metrics/repository").json()
    response = client.post(f"/api/repositories/{lab['id']}/analyse")
    assert response.status_code == 202, response.text
    _wait_for_parse(client, lab["id"])
    after = client.get(f"/api/repositories/{lab['id']}/metrics/repository").json()
    assert after == before


# ---------------------------------------------------------------------------
# File + directory metrics
# ---------------------------------------------------------------------------


def test_file_metrics_all_time(client: TestClient, lab: dict):
    body = client.get(
        f"/api/repositories/{lab['id']}/metrics/files", params={"sort": "path", "order": "asc"}
    ).json()
    assert body["total"] == 8
    rows = {row["path"]: row for row in body["items"]}
    assert rows[".mailmap"] == {
        "path": ".mailmap", "added": 2, "removed": 0, "growth": 2, "churn": 2,
        "modifications": 1, "modification_frequency": 1 * (1 / 9),
        "churn_rate": 2 * (1 / 9),
    }
    assert rows["src/app.py"]["added"] == 9
    assert rows["src/app.py"]["removed"] == 1
    assert rows["src/app.py"]["growth"] == 8
    assert rows["src/app.py"]["churn"] == 10
    assert rows["src/app.py"]["modifications"] == 3
    assert rows["init.txt"]["churn"] == 5
    # A rename source with no line history is a zero-metric object.
    assert rows["seed.txt"]["churn"] == 0
    assert rows["seed.txt"]["modification_frequency"] == 0.0
    assert rows["archive/seed.txt"]["churn"] == 0


def test_file_page_sorting_pagination_and_filter(client: TestClient, lab: dict):
    first = client.get(
        f"/api/repositories/{lab['id']}/metrics/files",
        params={"sort": "churn", "order": "desc", "limit": 2},
    ).json()
    assert [row["path"] for row in first["items"]] == ["src/app.py", "docs/notes.md"]
    assert first["total"] == 8 and first["offset"] == 0 and first["limit"] == 2

    second = client.get(
        f"/api/repositories/{lab['id']}/metrics/files",
        params={"sort": "churn", "order": "desc", "limit": 2, "offset": 2},
    ).json()
    assert [row["path"] for row in second["items"]] == ["init.txt", "src/lib/util.py"]

    filtered = client.get(
        f"/api/repositories/{lab['id']}/metrics/files",
        params={"q": "seed", "sort": "path", "order": "asc"},
    ).json()
    assert filtered["total"] == 2
    assert [row["path"] for row in filtered["items"]] == ["archive/seed.txt", "seed.txt"]


def test_directory_metrics_roll_up_descendants(client: TestClient, lab: dict):
    body = client.get(
        f"/api/repositories/{lab['id']}/metrics/directories",
        params={"sort": "path", "order": "asc"},
    ).json()
    assert [row["path"] for row in body["items"]] == ["archive", "docs", "src", "src/lib"]
    rows = {row["path"]: row for row in body["items"]}
    assert rows["src"] == {
        "path": "src", "added": 12, "removed": 2, "growth": 10, "churn": 14,
        "modifications": 4, "modification_frequency": 4 * (1 / 9),
        "churn_rate": 14 * (1 / 9),
    }
    assert rows["src/lib"]["churn"] == 4
    assert rows["docs"]["churn"] == 9
    assert rows["archive"]["modifications"] == 0


def test_object_detail_for_file_directory_and_root(client: TestClient, lab: dict):
    base = f"/api/repositories/{lab['id']}/metrics/object"

    file_body = client.get(base, params={"path": "init.txt"}).json()
    assert file_body["object_type"] == "file"
    assert file_body["metrics"]["churn"] == 5
    assert file_body["metrics"]["modification_frequency"] == 3 * (1 / 9)
    assert file_body["authors"] == [
        {"author": ADA, "added": 2, "removed": 2, "growth": 0, "churn": 4,
         "modifications": 2, "ownership": 0.8},
        {"author": BOB, "added": 1, "removed": 0, "growth": 1, "churn": 1,
         "modifications": 1, "ownership": 0.2},
    ]

    rename_source = client.get(base, params={"path": "seed.txt"}).json()
    assert rename_source["object_type"] == "file"
    assert rename_source["metrics"]["churn"] == 0
    assert rename_source["authors"] == []

    directory = client.get(base, params={"path": "src/lib"}).json()
    assert directory["object_type"] == "directory"
    assert directory["metrics"]["churn"] == 4

    root = client.get(base, params={"path": "/"}).json()
    assert root["object_type"] == "repository"
    assert root["metrics"]["churn"] == 33

    assert client.get(base, params={"path": "nope.txt"}).status_code == 404


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_month_buckets(client: TestClient, lab: dict):
    body = client.get(f"/api/repositories/{lab['id']}/metrics/timeline").json()
    assert body["bucket"] == "month"
    assert body["items"] == [
        {"key": "2024-01", "start": 1704067200, "added": 17, "removed": 3,
         "churn": 20, "commits": 4},
        {"key": "2024-02", "start": 1706745600, "added": 4, "removed": 2,
         "churn": 6, "commits": 4},  # the rename contributes 0/0 but is in H
        {"key": "2024-03", "start": 1709251200, "added": 5, "removed": 2,
         "churn": 7, "commits": 1},
    ]


def test_timeline_day_and_week_buckets(client: TestClient, lab: dict):
    url = f"/api/repositories/{lab['id']}/metrics/timeline"

    days = client.get(url, params={"bucket": "day"}).json()["items"]
    assert len(days) == 8
    feb_6 = next(item for item in days if item["start"] == 1707177600)
    assert feb_6 == {"key": "2024-02-06", "start": 1707177600, "added": 2,
                     "removed": 2, "churn": 4, "commits": 2}

    weeks = client.get(url, params={"bucket": "week"}).json()["items"]
    assert [item["key"] for item in weeks] == ["2024-W01", "2024-W02", "2024-W06", "2024-W09"]


# ---------------------------------------------------------------------------
# Reference CSV export
# ---------------------------------------------------------------------------


def test_export_matches_reference_format(client: TestClient, lab: dict):
    response = client.get(f"/api/repositories/{lab['id']}/metrics/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="rat-metrics-lab-metrics.csv"' in response.headers[
        "content-disposition"
    ]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "repo", "ref_sha", "commit_set", "commit_count", "object_type", "path",
        "author", "added", "removed", "growth", "churn", "modifications",
        "modification_frequency", "churn_rate", "ownership",
    ]
    assert len(rows) == 30  # 1 header + 13 object rows + 16 author rows

    # Block order: repository, then directories and files by ascending path,
    # each with the ALL row first followed by author rows sorted by churn.
    sequence = [(row[4], row[5], row[6]) for row in rows[1:]]
    assert sequence == [
        ("repository", "/", "ALL"),
        ("repository", "/", ADA),
        ("repository", "/", BOB),
        ("directory", "archive", "ALL"),
        ("directory", "docs", "ALL"),
        ("directory", "docs", BOB),
        ("directory", "src", "ALL"),
        ("directory", "src", ADA),
        ("directory", "src", BOB),
        ("directory", "src/lib", "ALL"),
        ("directory", "src/lib", ADA),
        ("directory", "src/lib", BOB),
        ("file", ".mailmap", "ALL"),
        ("file", ".mailmap", ADA),
        ("file", "README.md", "ALL"),
        ("file", "README.md", ADA),
        ("file", "archive/seed.txt", "ALL"),
        ("file", "docs/notes.md", "ALL"),
        ("file", "docs/notes.md", BOB),
        ("file", "init.txt", "ALL"),
        ("file", "init.txt", ADA),
        ("file", "init.txt", BOB),
        ("file", "seed.txt", "ALL"),
        ("file", "src/app.py", "ALL"),
        ("file", "src/app.py", ADA),
        ("file", "src/app.py", BOB),
        ("file", "src/lib/util.py", "ALL"),
        ("file", "src/lib/util.py", ADA),
        ("file", "src/lib/util.py", BOB),
    ]

    by_key = {(row[4], row[5], row[6]): row for row in rows[1:]}
    head = lab["detail"]["analysed_head"]

    root_all = by_key[("repository", "/", "ALL")]
    assert root_all == [
        "metrics-lab", head, "all", "9", "repository", "/", "ALL",
        "26", "7", "19", "33", "8", "0.8888888888888888", "3.6666666666666665", "",
    ]
    root_ada = by_key[("repository", "/", ADA)]
    assert root_ada == [
        "metrics-lab", head, "all", "9", "repository", "/", ADA,
        "13", "4", "9", "17", "4", "", "", "0.5151515151515151",
    ]

    # Zero-metric rename source: counts are integers, rates are the string 0.0.
    seed_all = by_key[("file", "seed.txt", "ALL")]
    assert seed_all == [
        "metrics-lab", head, "all", "9", "file", "seed.txt", "ALL",
        "0", "0", "0", "0", "0", "0.0", "0.0", "",
    ]
    # All rows carry eta/rho and an empty ownership; author rows the reverse.
    assert by_key[("file", ".mailmap", "ALL")][12:] == ["0.1111111111111111", "0.2222222222222222", ""]
    assert by_key[("file", "init.txt", ADA)][11:] == ["2", "", "", "0.8"]


def test_export_uses_custom_commit_set_label(client: TestClient, lab: dict):
    response = client.get(
        f"/api/repositories/{lab['id']}/metrics/export.csv", params={"since": FEB_1}
    )
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[1][2] == f"custom:{FEB_1}:"  # commit_set label
    assert rows[1][3] == "5"  # commit_count of the window


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_metrics_require_finished_analysis(client: TestClient, lab: dict, data_dir: Path):
    conn = sqlite3.connect(data_dir / "rat.sqlite3")
    conn.execute("UPDATE repositories SET parse_status = 'none' WHERE id = ?", (lab["id"],))
    conn.commit()
    conn.close()
    response = client.get(f"/api/repositories/{lab['id']}/metrics/repository")
    assert response.status_code == 400
    assert "extracted" in response.json()["detail"]


def test_metrics_unknown_repository_returns_404(client: TestClient):
    assert client.get("/api/repositories/nope/metrics/repository").status_code == 404
    assert client.get("/api/repositories/nope/metrics/files").status_code == 404
    assert client.get("/api/repositories/nope/metrics/export.csv").status_code == 404


# ---------------------------------------------------------------------------
# Reference float formatting (unit)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0.0"),
        (1.0, "1.0"),
        (0.9984942963290289, "0.9984942963290289"),
        (105.49704587486292, "105.49704587486292"),
        (0.056770310154786514, "0.056770310154786514"),
        (9.990730649746547e-05, "0.00009990730649746547"),
        (1.0083811991203813e-05, "0.000010083811991203813"),
        (9.928676422108369e-06, "9.928676422108369e-6"),
        (6.208981913235687e-07, "6.208981913235687e-7"),
        (0.0001, "0.0001"),
        (3.444444444444444, "3.444444444444444"),
    ],
)
def test_reference_float_formatting(value: float, expected: str):
    assert _format_metric(value) == expected

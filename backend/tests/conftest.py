"""Shared fixtures: synthetic git repositories, archives and a test client."""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Ada Lovelace",
    "GIT_AUTHOR_EMAIL": "ada@example.com",
    "GIT_COMMITTER_NAME": "Ada Lovelace",
    "GIT_COMMITTER_EMAIL": "ada@example.com",
    "GIT_AUTHOR_DATE": "2024-01-02T10:00:00+00:00",
    "GIT_COMMITTER_DATE": "2024-01-02T10:00:00+00:00",
}


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_IDENTITY},
    )


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """A tiny repository with two commits."""
    repo = tmp_path / "sample"
    repo.mkdir()
    git(["init", "-b", "main"], repo)
    (repo / "README.md").write_text("# Sample\n")
    git(["add", "."], repo)
    git(["commit", "-m", "Initial commit"], repo)
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hello')\n")
    git(["add", "."], repo)
    git(["commit", "-m", "Add app"], repo)
    return repo


@pytest.fixture()
def head_commit(sample_repo: Path) -> str:
    return git(["rev-parse", "HEAD"], sample_repo).stdout.strip()


def make_zip(source: Path, zip_path: Path, arc_prefix: str | None = None) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            arcname = str(Path(arc_prefix) / rel) if arc_prefix else str(rel)
            zf.write(path, arcname)
    return zip_path


@pytest.fixture()
def repo_zip(tmp_path: Path, sample_repo: Path) -> Path:
    """A zip with the repository inside a wrapping folder (like GitHub exports)."""
    return make_zip(sample_repo, tmp_path / "sample.zip", arc_prefix="sample")


@pytest.fixture()
def flat_repo_zip(tmp_path: Path, sample_repo: Path) -> Path:
    """A zip whose root is the repository itself."""
    return make_zip(sample_repo, tmp_path / "flat.zip")


@pytest.fixture()
def remote_url(tmp_path: Path, sample_repo: Path) -> str:
    """A local bare repository acting as a clone remote."""
    bare = tmp_path / "origin.git"
    git(["clone", "--bare", str(sample_repo), str(bare)], tmp_path)
    return bare.as_uri()


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "rat-data"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("RAT_DATA_DIR", str(tmp_path / "rat-data"))
    from app.main import create_app  # imported after the env var is set

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def upload_zip(client: TestClient):
    def _upload(zip_path: Path, filename: str | None = None, name: str | None = None):
        data = {"name": name} if name else {}
        with open(zip_path, "rb") as fh:
            return client.post(
                "/api/repositories/upload",
                files={"file": (filename or zip_path.name, fh, "application/zip")},
                data=data,
            )

    return _upload

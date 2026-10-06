"""ZIP ingestion: validation, extraction layout and failure modes."""

from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import make_zip


def test_zip_upload_happy_path(client: TestClient, upload_zip, repo_zip: Path):
    response = upload_zip(repo_zip)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "zip"
    assert body["source"] == "sample.zip"
    assert body["name"] == "sample"
    assert body["default_branch"] == "main"
    assert body["head_commit"] and len(body["head_commit"]) == 40
    assert body["progress"] == 100
    assert body["size_bytes"] > 0
    assert body["error"] is None


def test_zip_upload_extracts_only_git_directory(
    client: TestClient, upload_zip, repo_zip: Path, data_dir: Path
):
    body = upload_zip(repo_zip).json()
    root = data_dir / "repos" / body["id"]
    assert (root / "sample" / ".git").is_dir()
    # The worktree is deliberately not extracted: metrics only need the object DB.
    assert not (root / "sample" / "README.md").exists()
    assert not (root / "sample" / "src").exists()


def test_zip_upload_flat_archive(
    client: TestClient, upload_zip, flat_repo_zip: Path, data_dir: Path
):
    response = upload_zip(flat_repo_zip, filename="myrepo.zip")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "myrepo"
    assert (data_dir / "repos" / body["id"] / ".git").is_dir()


def test_zip_upload_custom_name_is_sanitized(client: TestClient, upload_zip, repo_zip: Path):
    body = upload_zip(repo_zip, name="My Sample Repo!").json()
    assert body["name"] == "My-Sample-Repo"


def test_upload_rejects_non_zip_file(client: TestClient):
    response = client.post(
        "/api/repositories/upload",
        files={"file": ("notes.txt", b"definitely not a zip", "text/plain")},
    )
    assert response.status_code == 400
    assert "zip" in response.json()["detail"].lower()


def test_upload_rejects_archive_without_git(client: TestClient, tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "file.txt").write_text("nothing to see\n")
    archive = make_zip(plain, tmp_path / "plain.zip")
    with open(archive, "rb") as fh:
        response = client.post(
            "/api/repositories/upload", files={"file": ("plain.zip", fh, "application/zip")}
        )
    assert response.status_code == 400
    assert ".git" in response.json()["detail"]


def test_upload_rejects_zip_slip(client: TestClient, tmp_path: Path, data_dir: Path):
    malicious = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious, "w") as zf:
        zf.writestr(zipfile.ZipInfo("../evil.txt"), "boom")
        zf.writestr(zipfile.ZipInfo(".git/HEAD"), "ref: refs/heads/main\n")
    with open(malicious, "rb") as fh:
        response = client.post(
            "/api/repositories/upload", files={"file": ("evil.zip", fh, "application/zip")}
        )
    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"].lower()
    # Nothing escaped the extraction root.
    assert not (data_dir / "evil.txt").exists()
    assert not (data_dir / "repos" / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


def test_upload_rejects_oversized_upload(
    client: TestClient, upload_zip, repo_zip: Path, monkeypatch
):
    monkeypatch.setenv("RAT_MAX_UPLOAD_BYTES", "10")
    response = upload_zip(repo_zip)
    assert response.status_code == 413


def test_upload_rejects_oversized_extraction(
    client: TestClient, upload_zip, repo_zip: Path, monkeypatch
):
    monkeypatch.setenv("RAT_MAX_EXTRACTED_BYTES", "10")
    response = upload_zip(repo_zip)
    assert response.status_code == 400
    assert "size limit" in response.json()["detail"].lower()


def test_upload_rejects_repository_without_commits(
    client: TestClient, tmp_path: Path, upload_zip
):
    empty = tmp_path / "empty"
    empty.mkdir()
    from .conftest import git

    git(["init", "-b", "main"], empty)
    archive = make_zip(empty, tmp_path / "empty.zip")
    response = upload_zip(archive)
    assert response.status_code == 400
    assert "no commits" in response.json()["detail"].lower()

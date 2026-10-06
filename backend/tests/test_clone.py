"""Remote clone ingestion: async status, progress, failures and URL handling."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.services.ingestion import name_from_url, mask_credentials, validate_clone_url


def _wait_for_finish(client: TestClient, repo_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/repositories/{repo_id}").json()
        if body["status"] != "cloning":
            return body
        time.sleep(0.05)
    raise AssertionError("clone did not finish in time")


def test_clone_from_remote_url(
    client: TestClient, remote_url: str, head_commit: str, data_dir: Path
):
    response = client.post("/api/repositories/clone", json={"url": remote_url})
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["source_type"] == "clone"
    assert created["status"] in {"cloning", "ready"}
    assert created["source"] == remote_url

    final = _wait_for_finish(client, created["id"])
    assert final["status"] == "ready", final["error"]
    assert final["name"] == "origin"
    assert final["default_branch"] == "main"
    assert final["head_commit"] == head_commit
    assert final["progress"] == 100
    assert final["size_bytes"] > 0
    assert (data_dir / "repos" / created["id"] / ".git").is_dir()


def test_clone_with_custom_name(client: TestClient, remote_url: str):
    response = client.post(
        "/api/repositories/clone", json={"url": remote_url, "name": "My Clone"}
    )
    assert response.status_code == 201
    assert response.json()["name"] == "My-Clone"


def test_clone_rejects_unsupported_scheme(client: TestClient):
    response = client.post("/api/repositories/clone", json={"url": "ftp://host/repo.git"})
    assert response.status_code == 400
    assert "scheme" in response.json()["detail"].lower()


def test_clone_rejects_garbage_url(client: TestClient):
    response = client.post("/api/repositories/clone", json={"url": "not a url"})
    assert response.status_code == 400


def test_clone_failure_is_recorded_on_entry(
    client: TestClient, tmp_path: Path, data_dir: Path
):
    missing = (tmp_path / "missing.git").as_uri()
    response = client.post("/api/repositories/clone", json={"url": missing})
    assert response.status_code == 201
    repo_id = response.json()["id"]

    final = _wait_for_finish(client, repo_id)
    assert final["status"] == "error"
    assert final["error"]
    assert final["progress"] == 0
    # Partial clone data is cleaned up and the entry can be deleted.
    assert not (data_dir / "repos" / repo_id).exists()
    assert client.delete(f"/api/repositories/{repo_id}").status_code == 204


def test_mask_credentials_removes_passwords_and_tokens():
    assert "s3cret" not in mask_credentials("https://alice:s3cret@example.com/repo.git")
    assert "token123" not in mask_credentials("https://token123@example.com/repo.git")
    assert mask_credentials("https://example.com/repo.git") == "https://example.com/repo.git"
    assert mask_credentials("git@github.com:owner/repo.git") == "git@github.com:owner/repo.git"


def test_name_from_url():
    assert name_from_url("https://github.com/redis/redis.git") == "redis"
    assert name_from_url("git@github.com:owner/my-repo.git") == "my-repo"
    assert name_from_url("file:///tmp/somewhere/origin.git/") == "origin"


def test_validate_clone_url_accepts_expected_forms():
    for url in (
        "https://github.com/owner/repo.git",
        "http://host/repo.git",
        "ssh://git@host/repo.git",
        "git://host/repo.git",
        "git@github.com:owner/repo.git",
        "/tmp/local/repo.git",
        "file:///tmp/local/repo.git",
    ):
        validate_clone_url(url)  # must not raise

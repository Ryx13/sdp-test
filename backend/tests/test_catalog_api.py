"""Catalog endpoints: list, detail, delete and error handling."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_health(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_is_empty_initially(client: TestClient):
    response = client.get("/api/repositories")
    assert response.status_code == 200
    assert response.json() == []


def test_detail_of_unknown_repository(client: TestClient):
    assert client.get("/api/repositories/nope").status_code == 404


def test_delete_of_unknown_repository(client: TestClient):
    assert client.delete("/api/repositories/nope").status_code == 404


def test_upload_list_detail_delete_roundtrip(
    client: TestClient, upload_zip, repo_zip: Path, data_dir: Path
):
    created = upload_zip(repo_zip).json()

    listed = client.get("/api/repositories").json()
    assert [repo["id"] for repo in listed] == [created["id"]]
    # Internal fields (like the on-disk path) are not exposed.
    assert "path" not in listed[0]

    detail = client.get(f"/api/repositories/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]

    assert client.delete(f"/api/repositories/{created['id']}").status_code == 204
    assert client.get(f"/api/repositories/{created['id']}").status_code == 404
    assert client.get("/api/repositories").json() == []
    assert not (data_dir / "repos" / created["id"]).exists()


def test_multiple_repositories_are_listed(client: TestClient, upload_zip, repo_zip, flat_repo_zip):
    first = upload_zip(repo_zip, name="First").json()
    second = upload_zip(flat_repo_zip, name="Second").json()
    listed = client.get("/api/repositories").json()
    ids = {repo["id"] for repo in listed}
    assert ids == {first["id"], second["id"]}

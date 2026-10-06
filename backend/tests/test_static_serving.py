"""Single-server mode: the backend serves the built frontend when available."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>RAT dashboard</html>")
    (dist / "assets" / "app.js").write_text("console.log('rat')")
    return dist


def test_serves_spa_and_assets_when_dist_exists(tmp_path: Path, monkeypatch):
    dist = _make_dist(tmp_path)
    monkeypatch.setenv("RAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAT_FRONTEND_DIST", str(dist))

    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/").text == "<html>RAT dashboard</html>"
        # SPA routes fall back to index.html
        assert client.get("/repositories/abc").text == "<html>RAT dashboard</html>"
        # Hashed bundles are served from /assets
        assert client.get("/assets/app.js").text == "console.log('rat')"
        # API routes are matched before the SPA fallback
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/nope").status_code == 404


def test_spa_fallback_rejects_path_traversal(tmp_path: Path, monkeypatch):
    dist = _make_dist(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-serve")
    monkeypatch.setenv("RAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAT_FRONTEND_DIST", str(dist))

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/../secret.txt")
        assert "do-not-serve" not in response.text


def test_no_spa_fallback_without_dist(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("RAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAT_FRONTEND_DIST", str(tmp_path / "missing"))

    from app.main import create_app

    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 404

"""FastAPI application factory for the RAT backend."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import metrics, repositories


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(
        title="RAT — Repo Analysis Tool",
        version="0.3.0",
        description="Measures how git repositories evolve: churn, growth, ownership and more.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(repositories.router)
    app.include_router(metrics.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built frontend from the backend when ``frontend/dist`` exists.

    This enables single-server mode (``make serve``). API routes are registered
    before the SPA fallback, so ``/api/*`` always wins.
    """
    dist = config.frontend_dist()
    index = dist / "index.html"
    if not index.is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
        return FileResponse(index)


app = create_app()

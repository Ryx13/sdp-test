"""FastAPI application factory for the RAT backend."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api import repositories


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(
        title="RAT — Repo Analysis Tool",
        version="0.1.0",
        description="Measures how git repositories evolve: churn, growth, ownership and more.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(repositories.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()

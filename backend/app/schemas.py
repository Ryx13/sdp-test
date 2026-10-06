"""Pydantic schemas for the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CloneRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class RepositoryOut(BaseModel):
    id: str
    name: str
    source_type: Literal["zip", "clone"]
    source: str
    status: Literal["cloning", "ready", "error"]
    error: str | None = None
    progress: int
    default_branch: str | None = None
    head_commit: str | None = None
    size_bytes: int | None = None
    created_at: str

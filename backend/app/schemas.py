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
    # history extraction
    parse_status: Literal["none", "parsing", "ready", "error"]
    parse_progress: int
    parse_error: str | None = None
    commit_count: int | None = None
    analysed_head: str | None = None
    parsed_at: str | None = None


class CommitOut(BaseModel):
    sha: str
    author_name: str
    author_email: str
    committer_ts: int
    parent_sha: str | None = None
    added: int
    removed: int


class CommitPageOut(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CommitOut]


class HistorySummaryOut(BaseModel):
    commit_count: int
    author_count: int
    file_count: int
    added: int
    removed: int

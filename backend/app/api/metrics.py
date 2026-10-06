"""Metric endpoints: repository, file, directory, commit-set and author metrics.

All endpoints accept an optional commit set defined by ``since`` (inclusive)
and ``until`` (exclusive) UNIX timestamps -- the brief's H_t and H_i,j.
"""

from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..schemas import (
    AuthorMetricsOut,
    ObjectDetailOut,
    ObjectMetricsPageOut,
    RepositoryMetricsOut,
    TimelineOut,
)
from ..services import metrics

router = APIRouter(prefix="/api/repositories", tags=["metrics"])

_Sort = Literal[
    "path", "added", "removed", "growth", "churn",
    "modifications", "churn_rate", "modification_frequency",
]
_Order = Literal["asc", "desc"]

SINCE = Query(default=None, ge=0, description="Commit set start (UNIX seconds, inclusive).")
UNTIL = Query(default=None, ge=0, description="Commit set end (UNIX seconds, exclusive).")


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Repository not found.")
    except metrics.MetricsNotReadyError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{repo_id}/metrics/repository", response_model=RepositoryMetricsOut)
def repository_metrics(repo_id: str, since: int | None = SINCE, until: int | None = UNTIL) -> dict:
    return _call(metrics.repository_metrics, repo_id, since, until)


@router.get("/{repo_id}/metrics/files", response_model=ObjectMetricsPageOut)
def file_metrics(
    repo_id: str,
    since: int | None = SINCE,
    until: int | None = UNTIL,
    sort: _Sort = "churn",
    order: _Order = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=500, description="Case-insensitive path filter."),
) -> dict:
    return _call(
        metrics.files_page, repo_id,
        since=since, until=until, sort=sort, order=order, limit=limit, offset=offset, query=q,
    )


@router.get("/{repo_id}/metrics/directories", response_model=ObjectMetricsPageOut)
def directory_metrics(
    repo_id: str,
    since: int | None = SINCE,
    until: int | None = UNTIL,
    sort: _Sort = "churn",
    order: _Order = "desc",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=500, description="Case-insensitive path filter."),
) -> dict:
    return _call(
        metrics.directories_page, repo_id,
        since=since, until=until, sort=sort, order=order, limit=limit, offset=offset, query=q,
    )


@router.get("/{repo_id}/metrics/authors", response_model=list[AuthorMetricsOut])
def author_metrics(repo_id: str, since: int | None = SINCE, until: int | None = UNTIL) -> list[dict]:
    return _call(metrics.author_metrics, repo_id, since, until)


@router.get("/{repo_id}/metrics/object", response_model=ObjectDetailOut)
def object_metrics(
    repo_id: str,
    path: str = Query(min_length=1, max_length=4096),
    since: int | None = SINCE,
    until: int | None = UNTIL,
) -> dict:
    detail = _call(metrics.object_detail, repo_id, path, since, until)
    if detail is None:
        raise HTTPException(404, "No such file or directory in this repository.")
    return detail


@router.get("/{repo_id}/metrics/timeline", response_model=TimelineOut)
def timeline_metrics(
    repo_id: str,
    since: int | None = SINCE,
    until: int | None = UNTIL,
    bucket: Literal["day", "week", "month"] = "month",
) -> dict:
    return _call(metrics.timeline, repo_id, since=since, until=until, bucket=bucket)


@router.get("/{repo_id}/metrics/export.csv")
def export_metrics(repo_id: str, since: int | None = SINCE, until: int | None = UNTIL) -> Response:
    """Every metric row in the reference CSV format (repository, directories, files)."""
    repo = _call(_repository_name, repo_id)
    try:
        # Materialised eagerly so readiness errors surface as HTTP responses.
        rows = list(metrics.export_rows(repo_id, repo["name"], since, until))
    except KeyError:
        raise HTTPException(404, "Repository not found.")
    except metrics.MetricsNotReadyError as exc:
        raise HTTPException(400, str(exc)) from exc
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="rat-{repo["name"]}-metrics.csv"'},
    )


def _repository_name(repo_id: str) -> dict:
    from ..services import catalog

    repo = catalog.get_repository(repo_id)
    if repo is None:
        raise KeyError(repo_id)
    return repo

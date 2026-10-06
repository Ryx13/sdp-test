"""REST endpoints for the repository catalog."""

from __future__ import annotations

import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status

from .. import config
from ..schemas import CloneRequest, RepositoryOut
from ..services import catalog, ingestion
from ..services.storage import IngestionError

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


def _get_or_404(repo_id: str) -> dict:
    repo = catalog.get_repository(repo_id)
    if repo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found.")
    return repo


@router.get("", response_model=list[RepositoryOut])
def list_repositories() -> list[dict]:
    return catalog.list_repositories()


@router.get("/{repo_id}", response_model=RepositoryOut)
def get_repository(repo_id: str) -> dict:
    return _get_or_404(repo_id)


@router.post("/upload", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def upload_repository(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> dict:
    """Ingest a zipped repository (must include its ``.git`` folder)."""
    config.tmp_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = config.tmp_dir() / f"upload-{uuid.uuid4().hex}.zip"
    limit = config.max_upload_bytes()
    written = 0
    try:
        with open(tmp_path, "wb") as sink:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        413,  # Payload Too Large
                        f"Upload exceeds the {limit // (1024 * 1024)} MiB limit.",
                    )
                sink.write(chunk)
        if written == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
        try:
            return ingestion.ingest_zip(
                tmp_path,
                original_filename=file.filename or "repository.zip",
                display_name=name,
            )
        except IngestionError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/clone", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
def clone_repository(payload: CloneRequest, background: BackgroundTasks) -> dict:
    """Start a deep clone of a remote repository (async, poll the entry for status)."""
    url = payload.url.strip()
    try:
        repo = ingestion.start_clone(url, display_name=payload.name)
    except IngestionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    background.add_task(ingestion.perform_clone, repo["id"], url)
    return repo


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repository(repo_id: str) -> None:
    repo = _get_or_404(repo_id)
    if repo["status"] == "cloning":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Repository is still cloning; wait for it to finish before deleting.",
        )
    shutil.rmtree(config.repos_dir() / repo_id, ignore_errors=True)
    catalog.delete_repository(repo_id)

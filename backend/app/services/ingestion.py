"""Repository ingestion: zip uploads and remote clones."""

from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .. import config
from . import catalog, history, storage
from .git_commands import (
    GitError,
    clone_repository,
    directory_size,
    is_git_repository,
    read_repo_state,
)
from .storage import IngestionError

_NAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_SCHEMES = {"http", "https", "git", "ssh", "file"}
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^ ]+$")


def sanitize_name(raw: str, fallback: str = "repository") -> str:
    cleaned = _NAME_SAFE.sub("-", raw.strip()).strip("-._")
    return cleaned[:200] or fallback


def mask_credentials(url: str) -> str:
    """Strip any password/token from a clone URL before it is persisted."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme in _ALLOWED_SCHEMES and "@" in parts.netloc:
        userinfo, host = parts.netloc.rsplit("@", 1)
        if ":" in userinfo:
            userinfo = userinfo.split(":", 1)[0] + ":***"
        else:
            userinfo = "***"
        parts = parts._replace(netloc=f"{userinfo}@{host}")
        return urlunsplit(parts)
    return url


def validate_clone_url(url: str) -> None:
    candidate = url.strip()
    if not candidate:
        raise IngestionError("Provide a repository URL to clone.")
    if "://" in candidate:
        scheme = candidate.split("://", 1)[0].lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise IngestionError(
                f"Unsupported URL scheme {scheme!r}. Use https, http, ssh, git or a local path."
            )
        return
    if _SCP_LIKE.match(candidate) or Path(candidate).is_absolute():
        return
    raise IngestionError(
        "That does not look like a git URL. Use https://, ssh://, user@host:path or an absolute local path."
    )


def name_from_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if "://" in cleaned:
        cleaned = urlsplit(cleaned).path or cleaned
    elif _SCP_LIKE.match(cleaned):
        cleaned = cleaned.split(":", 1)[1]
    segment = Path(cleaned).name
    if segment.endswith(".git"):
        segment = segment[:-4]
    return sanitize_name(segment)


def ingest_zip(
    zip_path: Path,
    *,
    original_filename: str,
    display_name: str | None = None,
) -> dict:
    """Validate and ingest an uploaded repository archive."""
    if not zipfile.is_zipfile(zip_path):
        raise IngestionError("The uploaded file is not a valid zip archive.")

    repo_id = uuid.uuid4().hex
    dest = config.repos_dir() / repo_id
    try:
        with zipfile.ZipFile(zip_path) as zf:
            storage.validate_archive_entries(zf)
            root = storage.find_repository_root(zf.namelist())
            storage.extract_repository(zf, dest, root)

        repo_path = dest / root if root else dest
        if not is_git_repository(repo_path):
            raise IngestionError(
                "The .git data in the archive is not a valid git repository. "
                "If you zipped a checkout, include the full .git directory."
            )
        try:
            state = read_repo_state(repo_path)
        except GitError as exc:
            raise IngestionError("The repository has no commits to analyse.") from exc
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    raw_name = display_name or (Path(root).name if root else Path(original_filename).stem)
    return catalog.create_repository(
        repo_id=repo_id,
        name=sanitize_name(raw_name),
        source_type="zip",
        source=original_filename,
        path=str(repo_path),
        status="ready",
        progress=100,
        default_branch=state["default_branch"],
        head_commit=state["head_commit"],
        size_bytes=directory_size(repo_path),
    )


def start_clone(url: str, *, display_name: str | None = None) -> dict:
    """Validate a clone URL and create the catalog entry in ``cloning`` state."""
    validate_clone_url(url)
    url = url.strip()
    repo_id = uuid.uuid4().hex
    dest = config.repos_dir() / repo_id
    name = sanitize_name(display_name) if display_name else name_from_url(url)
    return catalog.create_repository(
        repo_id=repo_id,
        name=name,
        source_type="clone",
        source=mask_credentials(url),
        path=str(dest),
        status="cloning",
        progress=0,
    )


def perform_clone(repo_id: str, url: str) -> None:
    """Deep-clone ``url`` for an existing catalog entry (runs in background)."""

    def on_progress(percent: int) -> None:
        catalog.update_repository(repo_id, progress=percent)

    repo = catalog.get_repository(repo_id)
    if repo is None:
        return
    dest = Path(repo["path"])
    try:
        clone_repository(
            url,
            dest,
            timeout=config.clone_timeout_seconds(),
            on_progress=on_progress,
        )
        state = read_repo_state(dest)
    except Exception as exc:  # any failure must be surfaced to the UI
        shutil.rmtree(dest, ignore_errors=True)
        catalog.update_repository(
            repo_id, status="error", error=str(exc)[:1000], progress=0
        )
        return

    catalog.update_repository(
        repo_id,
        status="ready",
        progress=100,
        default_branch=state["default_branch"],
        head_commit=state["head_commit"],
        size_bytes=directory_size(dest),
        # Flip straight into "parsing" so pollers never observe a
        # ready-but-not-yet-queued window, then analyse inline (this already
        # runs on a background worker).
        parse_status="parsing",
        parse_progress=0,
        parse_error=None,
    )
    history.analyse_repository(repo_id)

"""Archive validation and safe extraction for uploaded repository zips."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from .. import config


class IngestionError(Exception):
    """A user-correctable problem with an uploaded archive or clone target."""


def validate_archive_entries(zf: zipfile.ZipFile) -> None:
    """Reject archives whose entries would escape the extraction root."""
    for info in zf.infolist():
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        if raw.startswith("/") or (path.parts and ":" in path.parts[0]):
            raise IngestionError(f"Archive contains an absolute path entry: {info.filename!r}")
        if ".." in path.parts:
            raise IngestionError(f"Archive contains an unsafe path entry: {info.filename!r}")


def find_repository_root(names: list[str]) -> str:
    """Locate the repository root inside the archive.

    The root is the shortest directory prefix containing a ``.git`` entry.
    Repositories are frequently zipped inside a wrapping folder; those are
    supported, while ambiguous archives (two repositories side by side) are
    rejected. Returns ``""`` when the archive root itself is the repository.
    """
    candidates: set[str] = set()
    for name in names:
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if ".git" in parts:
            index = parts.index(".git")
            candidates.add("/".join(parts[:index]))
    if not candidates:
        raise IngestionError(
            "The archive does not contain a .git file or directory, so history "
            "cannot be extracted. Note: archives downloaded from GitHub "
            "(\"Download ZIP\" / source archives) never include .git. Zip a local "
            "git clone including its .git folder, or use the Clone URL option."
        )

    def depth(value: str) -> int:
        return len([part for part in value.split("/") if part])

    shallowest = min(depth(candidate) for candidate in candidates)
    roots = {candidate for candidate in candidates if depth(candidate) == shallowest}
    if len(roots) > 1:
        preview = ", ".join(sorted(repr(root or ".") for root in roots))
        raise IngestionError(
            f"The archive contains multiple repositories ({preview}); "
            "it must contain exactly one."
        )
    return roots.pop()


def _is_worktree_metadata(name: str) -> bool:
    """Worktree files that change analysis output and must survive extraction.

    All metrics come from the git object database, so the checked-out worktree
    is skipped -- except for these two files, which git itself reads from the
    worktree rather than from history when producing log output:

    * a top-level ``.mailmap`` defines author aliases, which ``%aN``/``%aE``
      apply during extraction;
    * ``.gitattributes`` files influence how diffs are computed.
    """
    basename = name.rstrip("/").rsplit("/", 1)[-1]
    return basename in {".mailmap", ".gitattributes"}


def extract_repository(zf: zipfile.ZipFile, dest: Path, root: str) -> None:
    """Extract the repository's ``.git`` contents into ``dest``.

    Only ``<root>/.git`` plus the worktree metadata files listed in
    :func:`_is_worktree_metadata` are written to disk: every metric is derived
    from the git object database, so the rest of the checked-out worktree is
    redundant. Skipping it keeps ingestion fast and storage small for large
    repositories.
    """
    prefix = f"{root}/" if root else ""
    git_dir = f"{prefix}.git/"
    budget = config.max_extracted_bytes()
    total = 0
    extracted = False
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if (
            name != f"{prefix}.git"
            and not name.startswith(git_dir)
            and not _is_worktree_metadata(name)
        ):
            continue
        total += info.file_size
        if total > budget:
            raise IngestionError("The archive expands past the configured size limit.")
        target = dest / PurePosixPath(name)
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)
        extracted = True
        mode = (info.external_attr >> 16) & 0o777
        if mode and os.name == "posix":
            try:
                os.chmod(target, mode)
            except OSError:
                pass
    if not extracted:
        raise IngestionError("The archive does not contain the .git contents needed for analysis.")

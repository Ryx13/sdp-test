"""Runtime configuration.

Every path and limit can be overridden with environment variables so that
tests and deployments can isolate their own data directory.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("RAT_DATA_DIR", str(BASE_DIR / "data")))


def repos_dir() -> Path:
    return data_dir() / "repos"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def db_path() -> Path:
    return data_dir() / "rat.sqlite3"


def max_upload_bytes() -> int:
    return int(os.environ.get("RAT_MAX_UPLOAD_BYTES", 2 * 1024**3))


def max_extracted_bytes() -> int:
    return int(os.environ.get("RAT_MAX_EXTRACTED_BYTES", 8 * 1024**3))


def clone_timeout_seconds() -> int:
    return int(os.environ.get("RAT_CLONE_TIMEOUT", 900))


def frontend_dist() -> Path:
    """Production frontend build served by the backend, when present."""
    return Path(os.environ.get("RAT_FRONTEND_DIST", str(BASE_DIR / "frontend" / "dist")))

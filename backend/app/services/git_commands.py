"""Thin, safe wrappers around the git CLI.

The RAT deliberately shells out to the system git: it is the reference
implementation for history walking, rename detection and binary detection,
and streaming `git log` output is far cheaper than re-implementing packfile
parsing.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

_GIT_ENV = {
    **os.environ,
    # never block on credential prompts; fail fast instead
    "GIT_TERMINAL_PROMPT": "0",
    # stable, parseable messages when git output is consumed later
    "LC_ALL": "C",
}


class GitError(Exception):
    """Raised when a git invocation fails or times out."""


def tail_text(text: str, max_lines: int = 4, max_chars: int = 500) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])[-max_chars:]


def run_git(args: list[str], cwd: Path | None = None, timeout: float = 60.0) -> str:
    """Run git with the given arguments and return stdout.

    Raises GitError with a trimmed stderr tail on failure.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            env=_GIT_ENV,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise GitError(tail_text(proc.stderr) or f"git {' '.join(args)} failed")
    return proc.stdout


def is_git_repository(path: Path) -> bool:
    try:
        run_git(["rev-parse", "--git-dir"], cwd=path, timeout=30)
        return True
    except GitError:
        return False


def read_repo_state(path: Path) -> dict:
    """Return the resolved HEAD commit and branch of a repository with commits."""
    head_commit = run_git(["rev-parse", "HEAD"], cwd=path, timeout=30).strip()
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, timeout=30).strip()
    return {
        "head_commit": head_commit,
        "default_branch": None if branch == "HEAD" else branch,
    }


# Streaming format for history extraction: every record starts with an RS byte
# and header fields are separated by US bytes — both cannot appear in commit
# metadata, so parsing is unambiguous. See services/history.py for the reader.
LOG_RECORD = "%x1e%H%x1f%an%x1f%ae%x1f%ct%x1f%P"


def count_history_commits(path: Path, timeout: float = 120.0) -> int:
    """Number of non-merge commits reachable from HEAD (the H̄ set size)."""
    output = run_git(["rev-list", "--no-merges", "--count", "HEAD"], cwd=path, timeout=timeout)
    return int(output.strip())


def open_history_stream(path: Path, stderr=None) -> subprocess.Popen:
    """Start ``git log`` for non-merge commits with per-file numstat output.

    ``-z`` makes paths NUL-separated and unquoted (no C-style escaping), and
    rename detection runs at the 50% similarity threshold required by the
    brief. The caller owns the process: read ``stdout`` (bytes), then
    ``wait()``; pass an open binary file as ``stderr`` to capture diagnostics.
    """
    return subprocess.Popen(
        [
            "git",
            "log",
            "--no-merges",
            "--find-renames=50%",
            "--numstat",
            "-z",
            "--no-show-signature",
            f"--format={LOG_RECORD}",
            "HEAD",
        ],
        cwd=str(path),
        env=_GIT_ENV,
        stdout=subprocess.PIPE,
        stderr=stderr if stderr is not None else subprocess.DEVNULL,
    )


def directory_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# Clone phases are scaled into an overall 0-100 progress range. Receiving
# objects dominates real-world clones, so it gets the largest slice.
_CLONE_PHASES = (
    ("Receiving objects", 5.0, 65.0),
    ("Resolving deltas", 70.0, 20.0),
    ("Checking out files", 90.0, 10.0),
)
_PERCENT = re.compile(r"(\d+)%")


def _clone_percent(line: str) -> float | None:
    for phase, base, span in _CLONE_PHASES:
        if phase in line:
            match = _PERCENT.search(line)
            if match:
                return base + span * int(match.group(1)) / 100.0
    return None


def clone_repository(
    url: str,
    dest: Path,
    *,
    timeout: float = 900.0,
    on_progress=None,
) -> None:
    """Deep-clone ``url`` into ``dest``, reporting progress 0-100.

    Runs ``git clone --progress`` and parses stderr so long-running external
    clones surface meaningful progress in the UI. Raises GitError on failure
    or when the clone exceeds ``timeout`` seconds.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            ["git", "clone", "--progress", url, str(dest)],
            env=_GIT_ENV,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc

    lines: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def _reader() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    deadline = time.monotonic() + timeout
    last_reported = -1.0
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is None and time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise GitError(f"clone timed out after {timeout:.0f}s")
            continue
        if line is None:
            break
        stderr_lines.append(line)
        if on_progress is not None:
            percent = _clone_percent(line)
            if percent is not None and percent != last_reported:
                last_reported = percent
                on_progress(int(percent))

    if proc.wait() != 0:
        raise GitError(tail_text("".join(stderr_lines)) or "git clone failed")

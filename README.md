# RAT — Repo Analysis Tool

A web dashboard that measures how git repositories evolve: per-file, per-directory,
per-repository, per-commit-set and per-author metrics (added/removed lines, growth,
churn, modifications, frequency, churn rate and ownership).

> COMS3011A project. Build status: **Part 2/8 — history extraction**.

## Features (progress)

- [x] **Part 1** — Repository ingestion: ZIP upload (with `.git`) and full remote clone,
      multi-repository catalog, status tracking, repository management UI
- [x] **Part 2** — History extraction: non-merge commit walking, rename-aware per-file
      line stats streamed into SQLite with progress, repository detail page with commit list
- [ ] **Part 3** — Metrics engine + API (file / directory / repository / commit-set / author)
- [ ] **Part 4** — Dashboard visualisations
- [ ] **Part 5** — Filtering (repo, author, object, commit ranges / manual commit lists)
- [ ] **Part 6** — Author merging (`.mailmap` + manual)
- [ ] **Part 7** — Multi-repo comparison & quality-of-life polish
- [ ] **Part 8** — Performance at ~100k commits and final validation

## Architecture

```
backend/    FastAPI + SQLite. Shells out to the git CLI (reference semantics for
            rename detection, binary detection and history walking).
frontend/   React + Vite + TypeScript dashboard.
data/       Runtime state (gitignored): cloned/extracted repos + rat.sqlite3.
```

Ingestion notes:

- ZIP uploads are extracted to `data/repos/<id>/`. Only the `.git` contents are
  written to disk — all metrics are derived from the git object database, so the
  checked-out worktree is redundant. This keeps ingestion fast and storage small,
  and archives are validated (zip-slip, size limits, `.git` presence) before use.
- Clones are full (deep) clones performed with `git clone --progress`; progress is
  reported to the UI and failures are recorded on the repository entry.

Analysis notes:

- As soon as a repository becomes `ready`, its history is analysed automatically;
  a manual restart is available from the UI (Analyse / Retry) and via
  `POST /api/repositories/{id}/analyse`.
- `git log --no-merges --find-renames=50% --numstat` is streamed and parsed from raw
  bytes into `commits` + `file_changes` tables. Merge commits are skipped, renames are
  attributed to the destination path (source recorded), binary files are excluded.
- Extraction runs in short write transactions so the API (progress polling, commit
  pages) stays responsive; re-analysis is idempotent and replaces prior data.

## Setup

Requirements: Python 3.12+, Node 18+, git 2.40+.

```bash
./start.sh     # handles setup automatically (or use `make setup` manually)
```

## Run

### One command (recommended)

```bash
./start.sh           # first run installs deps, builds the frontend, serves on :8000
PORT=9000 ./start.sh # serve on another port
```

Then open <http://127.0.0.1:8000>. The script is idempotent, so it is also the
fastest way to restart the app after a `git pull`.

### Manual commands

Development (two terminals):

```bash
make setup           # python venv (backed by .venv) + npm install
make dev-backend     # http://localhost:8000 (API + docs at /docs)
make dev-frontend    # http://localhost:5173 (proxies /api to the backend)
```

Single-server mode:

```bash
make serve           # builds the frontend and serves everything on :8000
```

## Test

```bash
make test            # pytest (backend) + vitest (frontend)
```

## API (Parts 1–2)

| Method | Path                        | Description                                  |
| ------ | --------------------------- | -------------------------------------------- |
| GET    | `/api/health`               | Health probe                                 |
| GET    | `/api/repositories`         | List all repositories                        |
| POST   | `/api/repositories/upload`  | Upload a repository ZIP (multipart `file`)   |
| POST   | `/api/repositories/clone`   | `{ "url": "..." }` — deep-clone a remote repo |
| GET    | `/api/repositories/{id}`    | Repository detail                            |
| DELETE | `/api/repositories/{id}`    | Delete a repository and its local data       |
| POST   | `/api/repositories/{id}/analyse` | (Re)start history extraction — 202 accepted, 409 while already running |
| GET    | `/api/repositories/{id}/commits` | Paginated non-merge commits (`offset`, `limit`) |
| GET    | `/api/repositories/{id}/summary` | Repository totals (commits, authors, files, lines) |

Environment overrides: `RAT_DATA_DIR`, `RAT_MAX_UPLOAD_BYTES`,
`RAT_MAX_EXTRACTED_BYTES`, `RAT_CLONE_TIMEOUT`.

# RAT — Repo Analysis Tool

A web dashboard that measures how git repositories evolve: per-file, per-directory,
per-repository, per-commit-set and per-author metrics (added/removed lines, growth,
churn, modifications, frequency, churn rate and ownership).

> COMS3011A project. Build status: **Part 1/8 — foundation & repository ingestion**.

## Features (progress)

- [x] **Part 1** — Repository ingestion: ZIP upload (with `.git`) and full remote clone,
      multi-repository catalog, status tracking, repository management UI
- [ ] **Part 2** — History extraction: non-merge commit walking, rename-aware per-file metrics
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

## API (Part 1)

| Method | Path                        | Description                                  |
| ------ | --------------------------- | -------------------------------------------- |
| GET    | `/api/health`               | Health probe                                 |
| GET    | `/api/repositories`         | List all repositories                        |
| POST   | `/api/repositories/upload`  | Upload a repository ZIP (multipart `file`)   |
| POST   | `/api/repositories/clone`   | `{ "url": "..." }` — deep-clone a remote repo |
| GET    | `/api/repositories/{id}`    | Repository detail                            |
| DELETE | `/api/repositories/{id}`    | Delete a repository and its local data       |

Environment overrides: `RAT_DATA_DIR`, `RAT_MAX_UPLOAD_BYTES`,
`RAT_MAX_EXTRACTED_BYTES`, `RAT_CLONE_TIMEOUT`.

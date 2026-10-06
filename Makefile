PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup setup-backend setup-frontend test test-backend test-frontend \
        dev-backend dev-frontend build serve

## Install everything (python venv + npm packages)
setup: setup-backend setup-frontend

setup-backend:
	python3 -m venv .venv
	$(PIP) install -r backend/requirements.txt

setup-frontend:
	cd frontend && npm install

## Run all test suites
test: test-backend test-frontend

test-backend:
	cd backend && ../$(PY) -m pytest

test-frontend:
	cd frontend && npm test

## Development servers (run in two terminals)
dev-backend:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

## Build the frontend and serve the whole app from the backend
build:
	cd frontend && npm run build

serve: build
	cd backend && ../$(PY) -m uvicorn app.main:app --port 8000

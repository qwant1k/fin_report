# Convenience targets — run from project root.

.PHONY: help install backend frontend test docker-up docker-down clean

help:
	@echo "Targets:"
	@echo "  install       — install backend (pip) and frontend (npm) deps"
	@echo "  backend       — run backend dev server (uvicorn --reload)"
	@echo "  frontend      — run frontend dev server (vite)"
	@echo "  test          — run backend pytest"
	@echo "  docker-up     — docker compose up --build"
	@echo "  docker-down   — docker compose down"
	@echo "  clean         — remove venv, node_modules, build artefacts"

install:
	cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -q tests

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf backend/.venv backend/__pycache__ backend/.pytest_cache
	rm -rf frontend/node_modules frontend/dist

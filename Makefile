.DEFAULT_GOAL := help

# Keep bytecode out of the source tree.
export PYTHONPYCACHEPREFIX := $(CURDIR)/.cache/pycache

# macOS: WeasyPrint loads Pango/GObject installed by Homebrew.
ifeq ($(shell uname -s),Darwin)
export DYLD_FALLBACK_LIBRARY_PATH := /opt/homebrew/lib:/usr/local/lib
endif

.PHONY: help menu sync run dev lint lint-fix format format-check \
	typecheck test test-v coverage check clean openapi openapi-check \
	docs docs-build \
	dev-up dev-down dev-logs dev-shell prod-build prod-up prod-down \
	prod-logs

# --- meta --------------------------------------------------------------

help: ## Show available commands
	@echo "jodit-python - make <target> (or 'make menu')"
	@echo
	@grep -E '^[a-zA-Z_-]+:[^#]*## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":[^#]*## "}; \
			{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

menu: ## Interactive menu
	@bash scripts/menu.sh

# --- development -------------------------------------------------------

sync: ## Install/update dependencies
	uv sync --all-groups

run: ## Run the connector (PORT, default 8081)
	uv run jcpy

dev: ## Run with auto-reload
	uv run uvicorn jcpy.app:create_app --factory --reload \
		--host $${HOST:-127.0.0.1} --port $${PORT:-8081}

# --- quality -----------------------------------------------------------

lint: ## Lint (ruff check)
	uv run ruff check .

lint-fix: ## Lint and auto-fix
	uv run ruff check --fix .

format: ## Format code (ruff format)
	uv run ruff format .

format-check: ## Check formatting
	uv run ruff format --check .

typecheck: ## Type-check (mypy --strict)
	uv run mypy

test: ## Run tests
	uv run pytest

test-v: ## Run tests verbosely
	uv run pytest -v

coverage: ## Run tests with coverage (fails under 90%)
	uv run pytest --cov --cov-report=term-missing --cov-report=html

check: lint format-check typecheck openapi-check docs-build coverage ## Run everything (as in CI)

# --- docs ---------------------------------------------------------------

openapi: ## Generate the OpenAPI document (docs/content/api-swagger)
	uv run python scripts/generate_openapi.py

openapi-check: ## Fail when the OpenAPI document is out of date
	uv run python scripts/generate_openapi.py --check

docs: ## Serve the documentation with live reload (DOCS_PORT, default 8000)
	uv run mkdocs serve -f docs/mkdocs.yml -a 127.0.0.1:$${DOCS_PORT:-8000}

docs-build: ## Build the documentation into site/ (fails on warnings)
	uv run mkdocs build -f docs/mkdocs.yml --strict

# --- docker: dev ------------------------------------------------------

DEV_COMPOSE := docker compose -f docker-compose.dev.yml

dev-up: ## Start dev container (hot reload)
	$(DEV_COMPOSE) up -d --build

dev-down: ## Stop dev container
	$(DEV_COMPOSE) down

dev-logs: ## Follow dev container logs
	$(DEV_COMPOSE) logs -f

dev-shell: ## Open a shell in the dev container
	$(DEV_COMPOSE) exec jcpy bash

# --- docker: prod -----------------------------------------------------

prod-build: ## Build prod image
	docker compose build

prod-up: ## Start prod container
	docker compose up -d --build

prod-down: ## Stop prod container
	docker compose down

prod-logs: ## Follow prod container logs
	docker compose logs -f

# --- misc -------------------------------------------------------------

clean: ## Remove caches and build artifacts
	rm -rf .cache dist build site
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

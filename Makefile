.DEFAULT_GOAL := help

.PHONY: help menu sync run dev lint lint-fix format format-check \
	typecheck test test-v coverage check clean

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
		--port $${PORT:-8081}

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

check: lint format-check typecheck coverage ## Run everything (as in CI)

clean: ## Remove caches and build artifacts
	rm -rf .cache dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

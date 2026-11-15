# AgentHive — developer tasks
#
# Windows note: PowerShell users should use the helper scripts in scripts/
# (e.g. scripts\install.ps1, scripts\start.ps1) instead of this Makefile.
# GNU Make is still available on Windows via MSYS2, choco, or WSL.

.DEFAULT_GOAL := help
.PHONY: help install dev-install test lint typecheck run start init-db \
        recover diagnose docker-build docker-up docker-down clean

help: ## Show this help
	@echo "AgentHive targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install runtime deps + package (delegates to scripts/install.sh)
	bash scripts/install.sh

dev-install: ## Create venv and install dev deps + editable package
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt
	.venv/bin/pip install -e .[dev]
	@echo "Activate the venv:  source .venv/bin/activate"

test: ## Run the test suite (quiet)
	pytest -q

lint: ## Run ruff over src and tests
	ruff check src tests

typecheck: ## Run mypy on the package
	mypy src

run: start ## Alias for start

start: ## Start the FastAPI server (uses env API_HOST/API_PORT)
	agent-hive start

init-db: ## Create database tables
	agent-hive init-db

recover: ## Reset orphaned running tasks
	agent-hive recover

diagnose: ## Print environment diagnostics
	agent-hive diagnose

docker-build: ## Build the Docker image
	docker build -t agent-hive .

docker-up: ## Start db + app via docker compose (builds if needed)
	docker compose up -d --build

docker-down: ## Stop and remove the compose stack
	docker compose down

clean: ## Remove caches, build artifacts, and the virtual environment
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache build dist
	rm -rf src/*.egg-info *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

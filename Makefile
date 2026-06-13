# Crisis Resource Navigator — dev verbs.
# Single-package repo: every target runs at the root via uv.

.PHONY: install test unit-tests integration-tests lint-check lint-fix \
        format-check format-fix pre-commit build ci run board seed-demo help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Install/refresh deps + git hooks
	uv sync
	uvx pre-commit install --hook-type pre-commit --hook-type pre-push

# pytest exit code 5 = "no tests collected" — fine until the first test lands (W1/W2).
test: ## Run the full test suite
	uv run pytest || test $$? -eq 5

unit-tests: ## Unit tests only
	uv run pytest tests/unit || test $$? -eq 5

integration-tests: ## Integration tests only
	uv run pytest tests/integration || test $$? -eq 5

lint-check: ## ruff check (no write)
	uv run ruff check

lint-fix: ## ruff check --fix
	uv run ruff check --fix

format-check: ## ruff format --check (no write)
	uv run ruff format --check

format-fix: ## ruff format (writes)
	uv run ruff format

pre-commit: format-check lint-check unit-tests ## Fast pre-commit gate

build: ## No build artifact — the agent runs via `slack run`
	@echo "Nothing to build: Slack agent runs via 'make run' (slack run)."

ci: install format-check lint-check test ## Full pre-PR fan

run: ## Run the agent against the sandbox (verify after W1 scaffold)
	slack run

board: ## Open the coordinator board — reuse the one titled tab, never delete. `ARGS=--fresh` forces a clean re-render (no new tab).
	uv run python -m scripts.open_board $(ARGS)

seed-demo: ## Seed the Exmouth scenario into CRISIS_CHANNEL (idempotent; ARGS=--fresh to wipe + re-seed)
	uv run python -m scripts.seed_demo $(ARGS)

# OptionsScout AI — developer commands. Run `make help`.
PY        ?= .venv/bin/python
UV        ?= uv
PORT_API  ?= 8000
PORT_UI   ?= 8501

.PHONY: help install test test-live lint fmt eval api ui demo clean check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## create .venv and install all deps (uv)
	$(UV) venv .venv --python 3.12 --allow-existing
	$(UV) pip install --python $(PY) -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Installed. Edit .env if you want live data / an LLM key."

test: ## unit + agent tests (offline, fixtures only)
	$(PY) -m pytest

test-live: ## integration tests that hit the network
	$(PY) -m pytest -m live --override-ini="addopts=-q --strict-markers"

lint: ## ruff + mypy (strict on core/)
	$(PY) -m ruff check src tests evals ui
	$(PY) -m ruff format --check src tests evals ui
	$(PY) -m mypy

fmt: ## auto-format
	$(PY) -m ruff format src tests evals ui
	$(PY) -m ruff check --fix src tests evals ui

check: lint test ## lint + test

eval: ## run the eval suite, write evals/reports/latest.md
	$(PY) evals/run_evals.py

api: ## FastAPI on :8000
	$(PY) -m uvicorn options_scout.api.main:app --host 0.0.0.0 --port $(PORT_API) --reload

ui: ## Streamlit on :8501
	$(PY) -m streamlit run ui/streamlit_app.py --server.port $(PORT_UI)

demo: ## full pipeline in fixture mode, prints a report
	$(PY) -m options_scout.cli demo $(ARGS)

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache data/cache.sqlite data/checkpoints.sqlite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

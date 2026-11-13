# OptionsScout AI: developer commands. Run `make help`.
PY        ?= .venv/bin/python
UV        ?= uv
PORT_API  ?= 8000
PORT_UI   ?= 8501

.PHONY: help install test test-cov test-live mutation lint fmt eval eval-check record-llm bench requirements requirements-check api ui mcp demo demo-core bottlenecks index clean check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## create .venv and install all deps at the versions in requirements.txt (uv)
	$(UV) venv .venv --python 3.12 --allow-existing
	$(UV) pip install --python $(PY) -c requirements.txt -e ".[dev,mcp]"
	@test -f .env || cp .env.example .env
	@echo "Installed. Edit .env if you want live data / an LLM key."

test: ## unit + agent tests (offline, fixtures only)
	$(PY) -m pytest

test-cov: ## offline tests with coverage; fails below 85% on core/, rag/, agent/, bottleneck/ (COV_ARGS="--cov-report=xml" in CI)
	$(PY) -m pytest --cov=options_scout --cov-report=term-missing:skip-covered $(COV_ARGS)
	$(PY) -m coverage report --include='src/options_scout/core/*,src/options_scout/rag/*,src/options_scout/agent/*,src/options_scout/bottleneck/*' --skip-covered --fail-under=85

test-live: ## integration tests that hit the network
	$(PY) -m pytest -m live --override-ini="addopts=-q --strict-markers"

mutation: ## mutation testing on sizing, risk, screeners and compliance (slow; run before a release, not on every push)
	$(PY) -m mutmut run
	$(PY) -m mutmut results

lint: ## ruff + mypy (strict on core/)
	$(PY) -m ruff check src tests evals ui
	$(PY) -m ruff format --check src tests evals ui
	$(PY) -m mypy

fmt: ## auto-format
	$(PY) -m ruff format src tests evals ui
	$(PY) -m ruff check --fix src tests evals ui

check: lint test ## lint + test

eval: ## run the eval suite (incl. the full test suite with coverage), write evals/reports/latest.md, re-render the doc numbers
	$(PY) evals/run_evals.py; status=$$?; $(PY) scripts/render_doc_numbers.py; exit $$status

eval-check: ## fail when evals/reports/latest.md is older than the code, prompts or datasets it describes
	$(PY) scripts/check_eval_report.py

record-llm: ## record live model outputs into tests/fixtures/llm so fixture mode replays them (spends LLM credits)
	$(PY) scripts/record_llm_fixtures.py

bench: ## performance benchmarks in fixture mode (latency per agent, tokens, cost, cache hits, retrieval) → evals/reports/bench.md
	$(PY) evals/bench.py

requirements: ## export requirements.txt from pyproject.toml (pinned, universal); pyproject stays the source of truth
	$(PY) scripts/export_requirements.py --uv $(UV)

requirements-check: ## fail when requirements.txt is out of date with pyproject.toml (CI)
	$(PY) scripts/export_requirements.py --uv $(UV)
	git diff --exit-code -- requirements.txt

api: ## FastAPI on localhost:8000 (local dev: anonymous allowed because it is not published)
	OPTIONS_SCOUT_ALLOW_ANONYMOUS=$${OPTIONS_SCOUT_ALLOW_ANONYMOUS:-1} $(PY) -m uvicorn options_scout.api.main:app --host 127.0.0.1 --port $(PORT_API) --reload

ui: ## Streamlit on :8501
	$(PY) -m streamlit run ui/streamlit_app.py --server.port $(PORT_UI)

mcp: ## MCP server over stdio for Claude Desktop (see README "Use it from Claude Desktop")
	$(PY) -m options_scout.mcp.server

demo: ## full agent pipeline in fixture mode, prints a report (ARGS="--no-llm" to skip LLM steps)
	$(PY) -m options_scout.cli demo $(ARGS)

demo-core: ## deterministic screeners + sizing + risk for every profile × account type
	$(PY) -m options_scout.cli demo-core $(ARGS)

bottlenecks: ## bottleneck board + thesis monitor in fixture mode, writes a snapshot (ARGS="--no-llm" / "--mode live")
	$(PY) -m options_scout.jobs.refresh_bottlenecks --fixture $(ARGS)

index: ## regenerate knowledge/rules from PRD + config and rebuild data/knowledge.sqlite (offline, hash embedder)
	$(PY) -m options_scout.rag.index

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache data/cache.sqlite data/checkpoints.sqlite data/knowledge.sqlite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

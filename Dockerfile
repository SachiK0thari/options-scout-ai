# Base images pinned by digest (multi-arch index), so a rebuild gets the same OS and Python (W42).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1 OPTIONS_SCOUT_ROOT=/app
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.4@sha256:40775a79214294fb51d097c9117592f193bcfdfc634f4daa0e169ee965b10ef0 /uv /usr/local/bin/uv
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
# Runtime dependencies only, constrained to requirements.txt: the versions the tests ran against.
RUN uv pip install --no-cache -c requirements.txt .
COPY config ./config
COPY prompts ./prompts
COPY knowledge ./knowledge
COPY data/brand_map.yaml ./data/brand_map.yaml
COPY tests/fixtures ./tests/fixtures
COPY ui ./ui
# The knowledge index is built into the image (knowledge/rules is committed, so no PRD.md needed).
# Without knowledge/ the app answered every concept question "no source" and nothing failed.
# It lives outside data/ (W39): the shared volume is seeded only once, so an index there would
# go stale after an upgrade and every service would race to rebuild it. Each container reads
# the copy built with its own image.
ENV OPTIONS_SCOUT_RAG_INDEX_DB=/app/index/knowledge.sqlite
RUN python -m options_scout.rag.index --no-rules
# Run as an unprivileged user; it owns data/ (the named volume is seeded from it on first use).
RUN useradd --create-home --uid 10001 scout && chown -R scout /app/data /app/index
USER scout
ENV OPTIONS_SCOUT_DATA_MODE=fixture OPTIONS_SCOUT_LLM_MODE=fixture
EXPOSE 8000 8501
# Default: API. docker-compose overrides the command for the UI and scheduler services.
CMD ["python", "-m", "uvicorn", "options_scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --no-cache .
COPY config ./config
COPY prompts ./prompts
COPY data/brand_map.yaml ./data/brand_map.yaml
COPY tests/fixtures ./tests/fixtures
COPY ui ./ui
ENV OPTIONS_SCOUT_DATA_MODE=fixture OPTIONS_SCOUT_LLM_MODE=fixture OPTIONS_SCOUT_ROOT=/app
EXPOSE 8000 8501
# Default: API. docker-compose overrides the command for the UI and scheduler services.
CMD ["python", "-m", "uvicorn", "options_scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

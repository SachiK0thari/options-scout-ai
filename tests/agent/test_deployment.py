"""W42: the documented deployment works. The image's file set answers with citations, an empty
knowledge base fails loudly, settings are checked once at start-up, live mode starts without a
key of its own, the scheduler keeps its data, and the Docker files meet the hygiene list.

The image itself is not built here (no Docker daemon in CI); the file-set test stands in for it:
it copies exactly what the Dockerfile copies and runs the app from that folder.
"""

from __future__ import annotations

import shlex
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from options_scout.agent.deps import Deps
from options_scout.agent.graph import answer_question
from options_scout.config import AppConfig, load_config
from options_scout.env import EnvConfigError, check_startup, env_settings
from options_scout.rag.index import build_index
from options_scout.rag.retriever import KnowledgeBaseEmptyError
from tests.conftest import REPO_ROOT

DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"
KEY = "test-key-w42"


def dockerfile_copies() -> list[tuple[str, str]]:
    """``(source, destination)`` for every ``COPY`` from the build context, in order."""
    out: list[tuple[str, str]] = []
    for line in DOCKERFILE.read_text().splitlines():
        parts = shlex.split(line.split("#", 1)[0]) if line.strip().startswith("COPY") else []
        if not parts or any(p.startswith("--from") for p in parts):
            continue
        *sources, dest = parts[1:]
        out += [(s, dest) for s in sources]
    return out


def image_file_set(dest_root: Path, *, skip: tuple[str, ...] = ()) -> Path:
    """Copy exactly the Dockerfile's ``COPY`` set (relative to WORKDIR /app) into ``dest_root``."""
    for src, dest in dockerfile_copies():
        if src in skip:
            continue
        source = REPO_ROOT / src
        target = dest_root / dest
        if dest.endswith("/") or dest in (".", "./"):
            target = target / Path(src).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target)
    return dest_root


def _image_deps(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AppConfig, Deps]:
    monkeypatch.setenv("OPTIONS_SCOUT_ROOT", str(root))
    cfg = load_config(root)
    return cfg, Deps.from_config(cfg)


# ------------------------------------------------------------------ step 1: the image's files
def test_the_dockerfile_copies_the_knowledge_base_and_builds_its_index() -> None:
    copied = {src for src, _ in dockerfile_copies()}
    assert {"knowledge", "config", "prompts", "src", "requirements.txt"} <= copied
    text = DOCKERFILE.read_text()
    index_at = text.index("RUN python -m options_scout.rag.index")
    assert text.index("COPY knowledge") < index_at < text.index("USER ")


def test_the_image_keeps_its_index_outside_the_shared_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W39: data/ is the scout-data volume, seeded once; the index must not live there."""
    text = DOCKERFILE.read_text()
    env_at = text.index("ENV OPTIONS_SCOUT_RAG_INDEX_DB=/app/index/")
    assert env_at < text.index("RUN python -m options_scout.rag.index")
    compose = (DOCKERFILE.parent / "docker-compose.yml").read_text()
    assert "/app/index" not in compose  # no volume over it
    target = tmp_path / "index" / "knowledge.sqlite"
    monkeypatch.setenv("OPTIONS_SCOUT_RAG_INDEX_DB", str(target))
    cfg = load_config(DOCKERFILE.parent)
    assert cfg.rag.index_db == target
    assert build_index(cfg)["chunks"] > 0  # type: ignore[operator]
    assert target.exists()


def test_the_image_file_set_answers_a_concept_question_with_a_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = image_file_set(tmp_path / "app")
    cfg, deps = _image_deps(root, monkeypatch)
    summary = build_index(cfg)  # the Dockerfile's RUN step
    assert summary["chunks"] > 0  # type: ignore[operator]
    final = answer_question(deps, "what is a cash-secured put?", "t-w42-image")
    assert final["citations"] and final["citations"][0].doc_id == "cash-secured-put"
    assert final["answer"].paragraphs[0].mode == "education"
    assert final["verification"].passed


# ------------------------------------------------------- step 3: an empty knowledge base fails
def test_without_the_knowledge_base_the_agents_fail_at_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = image_file_set(tmp_path / "app", skip=("knowledge",))
    cfg, deps = _image_deps(root, monkeypatch)
    with pytest.raises(KnowledgeBaseEmptyError, match="knowledge base is empty"):
        deps.knowledge()
    # a deployment without a corpus on purpose says so, and then gets the fixed reply
    rag = cfg.rag.model_copy(update={"allow_empty_corpus": True})
    deps_ok = Deps.from_config(cfg.model_copy(update={"rag": rag}))
    assert len(deps_ok.knowledge().store) == 0


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Any:
    import options_scout.api.main as api_mod

    monkeypatch.setenv("OPTIONS_SCOUT_API_KEY", KEY)
    monkeypatch.setattr(api_mod, "_RATE_LIMIT_PER_MIN", 10_000)
    monkeypatch.setattr(api_mod, "_registry", None)
    api_mod._hits.clear()
    yield api_mod
    api_mod._hits.clear()


def test_healthz_reports_the_chunk_count_and_answers_503_when_empty(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(api.app)
    ok = client.get("/healthz")
    assert ok.status_code == 200 and ok.json()["knowledge_chunks"] > 0
    keyed = client.get("/healthz", headers={"X-API-Key": KEY}).json()
    assert keyed["knowledge_chunks"] == ok.json()["knowledge_chunks"] and keyed["status"] == "ok"
    monkeypatch.setattr(api, "knowledge_chunks", lambda _reg: 0)
    empty = client.get("/healthz")
    assert empty.status_code == 503
    assert empty.json() == {
        "status": "knowledge base empty",
        "version": empty.json()["version"],
        "knowledge_chunks": 0,
    }


def test_startup_refuses_an_empty_knowledge_base(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def empty(_cfg: AppConfig) -> int:
        raise KnowledgeBaseEmptyError("the knowledge base is empty: no documents")

    monkeypatch.setattr(api, "ensure_knowledge_base", empty)
    with pytest.raises(KnowledgeBaseEmptyError):
        api.startup_checks()


# --------------------------------------------------- step 4: settings checked once, at start-up
@pytest.mark.parametrize(
    ("name", "value", "says"),
    [
        ("OPTIONS_SCOUT_DATA_MODE", "bogus", "OPTIONS_SCOUT_DATA_MODE='bogus'"),
        ("OPTIONS_SCOUT_LLM_MODE", "gpt", "OPTIONS_SCOUT_LLM_MODE='gpt'"),
        ("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "abc", "OPTIONS_SCOUT_RATE_LIMIT_PER_MIN='abc'"),
        ("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "0", "greater than or equal to 1"),
        ("OPTIONS_SCOUT_LOG_LEVEL", "loud", "OPTIONS_SCOUT_LOG_LEVEL='LOUD'"),
        ("OPTIONS_SCOUT_MARKET_PROVIDER", "polygon", "OPTIONS_SCOUT_MARKET_PROVIDER='polygon'"),
        ("OPTIONS_SCOUT_ALLOW_ANONYMOUS", "yes", "OPTIONS_SCOUT_ALLOW_ANONYMOUS='yes'"),
        ("OPTIONS_SCOUT_TRACING", "langsmth", "OPTIONS_SCOUT_TRACING='langsmth'"),
    ],
)
def test_a_bad_setting_stops_start_up_with_its_name(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, says: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(EnvConfigError, match="Invalid environment configuration") as exc:
        check_startup(REPO_ROOT)
    assert says in str(exc.value)


def test_every_bad_setting_is_named_in_one_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "bogus")
    monkeypatch.setenv("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "abc")
    with pytest.raises(EnvConfigError) as exc:
        env_settings()
    assert "OPTIONS_SCOUT_DATA_MODE" in str(exc.value)
    assert "OPTIONS_SCOUT_RATE_LIMIT_PER_MIN" in str(exc.value)


def test_case_and_spaces_are_normalised_and_empty_means_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", " LIVE ")
    monkeypatch.setenv("OPTIONS_SCOUT_LOG_LEVEL", "debug")
    monkeypatch.setenv("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "")  # compose passes ${X:-}
    s = env_settings()
    assert (s.data_mode, s.log_level, s.rate_limit_per_min) == ("live", "DEBUG", 30)
    assert load_config(REPO_ROOT).settings.data_mode == "live"  # was a 500 on every request


def test_the_api_imports_with_a_bad_rate_limit_and_refuses_to_start(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "abc")
    assert api._initial_rate_limit() == 30  # the import no longer crashes
    with pytest.raises(EnvConfigError, match="RATE_LIMIT_PER_MIN"):
        api.startup_checks()
    monkeypatch.setenv("OPTIONS_SCOUT_RATE_LIMIT_PER_MIN", "45")
    api.startup_checks()
    assert api._RATE_LIMIT_PER_MIN == 45


# ------------------------------------------------- step 5: live mode without a key of its own
def test_live_mode_without_a_key_starts_and_serves_requests_that_bring_one(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.api.schemas import MarketDataAuth

    monkeypatch.setenv("OPTIONS_SCOUT_DATA_MODE", "live")
    monkeypatch.delenv("MARKETDATA_TOKEN", raising=False)
    monkeypatch.delenv("TRADIER_API_KEY", raising=False)
    from options_scout.config import get_config

    get_config.cache_clear()
    try:
        reg = api.registry()  # used to raise MarketDataError, taking /healthz down with it
        assert not reg.deps.md.available
        assert "MARKETDATA_TOKEN" in (reg.deps.md.unavailable_reason or "")
        assert TestClient(api.app).get("/healthz").status_code == 200
        with pytest.raises(HTTPException) as exc:
            reg.graph_for(None)
        assert exc.value.status_code == 422 and "own key" in str(exc.value.detail)
        own = MarketDataAuth(provider="marketdata", api_key=SecretStr("caller-token"))
        assert reg.graph_for(own) is not reg.graph  # a source of its own, no network yet
    finally:
        get_config.cache_clear()


# ------------------------------------------------------ step 7: the scheduler keeps its data
def test_the_fixture_trend_refresh_keeps_the_snapshot_it_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from options_scout.jobs import refresh_trends
    from options_scout.social.pipeline import TrendStore

    db = tmp_path / "trends.sqlite"
    monkeypatch.setattr(refresh_trends, "TrendStore", lambda _path: TrendStore(db))
    assert refresh_trends.main(["--mode", "fixture"]) == 0
    rows = sqlite3.connect(db).execute("SELECT COUNT(*) FROM trend_snapshots").fetchone()[0]
    assert rows == 1  # the wall-clock purge used to delete the fixture-dated snapshot


# ---------------------------------------------------------- steps 2, 6, 8: Docker file hygiene
def test_the_dockerfile_runs_unprivileged_from_pinned_images_and_the_lock() -> None:
    text = DOCKERFILE.read_text()
    froms = [ln for ln in text.splitlines() if ln.startswith("FROM ")]
    assert froms and all("@sha256:" in ln for ln in froms)
    assert "ghcr.io/astral-sh/uv:0.8.4@sha256:" in text
    assert "-c requirements.txt" in text
    user = [ln for ln in text.splitlines() if ln.startswith("USER ")]
    assert user and user[-1].split()[1] not in ("root", "0")
    ignored = (REPO_ROOT / ".dockerignore").read_text().split()
    assert {".env", ".git", ".venv", "data/*.sqlite"} <= set(ignored)


def test_compose_passes_the_provider_settings_and_watches_every_service() -> None:
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    for name in ("api", "ui", "scheduler"):
        svc = services[name]
        env = svc["environment"]
        assert {"MARKETDATA_TOKEN", "TRADIER_API_KEY", "OPTIONS_SCOUT_MARKET_PROVIDER"} <= set(env)
        assert svc["restart"] == "unless-stopped"
        assert "healthcheck" in svc
    assert services["ui"]["ports"] == ["127.0.0.1:8501:8501"]  # W37
    assert "|| true" not in services["scheduler"]["command"]
    assert "failed" in services["scheduler"]["command"]


def test_sqlite_side_files_are_ignored_by_git() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert {"data/*.sqlite-wal", "data/*.sqlite-shm"} <= set(ignored)

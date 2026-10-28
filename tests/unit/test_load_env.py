"""load_env reads <repo>/.env into os.environ without clobbering the shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from options_scout.config import load_env


def test_missing_file_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPTIONS_SCOUT_DOTENV", raising=False)
    assert load_env(tmp_path / ".env") is False


def test_opt_out_skips_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("OS_TEST_SKIPPED=1\n")
    monkeypatch.setenv("OPTIONS_SCOUT_DOTENV", "0")
    monkeypatch.delenv("OS_TEST_SKIPPED", raising=False)
    assert load_env(env) is False
    assert "OS_TEST_SKIPPED" not in __import__("os").environ


def test_loads_new_vars_but_shell_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPTIONS_SCOUT_DOTENV", raising=False)
    monkeypatch.delenv("OS_TEST_NEW", raising=False)
    monkeypatch.setenv("OS_TEST_EXISTING", "from-shell")
    env = tmp_path / ".env"
    env.write_text("OS_TEST_NEW=from-file\nOS_TEST_EXISTING=from-file\n")

    assert load_env(env) is True
    assert __import__("os").environ["OS_TEST_NEW"] == "from-file"
    assert __import__("os").environ["OS_TEST_EXISTING"] == "from-shell"
    monkeypatch.delenv("OS_TEST_NEW", raising=False)

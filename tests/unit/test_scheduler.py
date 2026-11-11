"""The compose scheduler runs the daily jobs at a fixed New York time (W42, W11 step 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from options_scout.jobs import scheduler

NY = scheduler.NEW_YORK


def test_next_run_is_the_next_seven_oclock_in_new_york() -> None:
    before = datetime(2026, 11, 10, 6, 30, tzinfo=NY)
    assert scheduler.next_run(before, (7, 0)) == datetime(2026, 11, 10, 7, 0, tzinfo=NY)
    after = datetime(2026, 11, 10, 7, 0, tzinfo=NY)  # exactly at the time: tomorrow
    assert scheduler.next_run(after, (7, 0)) == datetime(2026, 11, 11, 7, 0, tzinfo=NY)
    # a container clock in UTC: 01:22 UTC on 11 Nov is 20:22 on 10 Nov in New York
    utc = datetime(2026, 11, 11, 1, 22, tzinfo=UTC)
    assert scheduler.next_run(utc, (7, 0)) == datetime(2026, 11, 11, 7, 0, tzinfo=NY)


def test_next_run_follows_daylight_saving() -> None:
    # US clocks fall back on 1 Nov 2026: 07:00 New York is 11:00 UTC before, 12:00 UTC after
    oct_31 = scheduler.next_run(datetime(2026, 10, 31, 6, 0, tzinfo=NY), (7, 0))
    nov_1 = scheduler.next_run(datetime(2026, 11, 1, 6, 0, tzinfo=NY), (7, 0))
    assert oct_31.astimezone(UTC).hour == 11 and nov_1.astimezone(UTC).hour == 12


def test_bad_schedule_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        scheduler.parse_at("25:00")


def test_a_failed_job_is_logged_and_the_heartbeat_is_left_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beat = tmp_path / "scheduler.heartbeat"
    runs: list[str] = []

    def runner(job: str) -> int:
        runs.append(job)
        return 3 if job == "refresh_trends" else 0

    assert scheduler.run_pass(runner=runner, heartbeat=beat) is False
    assert runs == list(scheduler.JOBS)  # a failure does not stop the later jobs
    assert "scheduler: refresh_trends failed (exit 3)" in capsys.readouterr().err
    assert not beat.exists()
    assert scheduler.run_pass(runner=lambda _job: 0, heartbeat=beat) is True
    assert beat.exists()


def test_main_runs_at_start_then_sleeps_until_the_next_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPTIONS_SCOUT_SCHEDULE_AT", "07:00")
    clock = [datetime(2026, 11, 10, 20, 0, tzinfo=NY)]
    slept: list[float] = []
    passes: list[datetime] = []

    def runner(job: str) -> int:
        if job == scheduler.JOBS[0]:
            passes.append(clock[0])
        return 0

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] = clock[0] + __import__("datetime").timedelta(seconds=seconds)

    scheduler.main(
        now=lambda: clock[0],
        sleep=sleep,
        runner=runner,
        passes=3,
        heartbeat=tmp_path / "hb",
    )
    assert passes[0] == datetime(2026, 11, 10, 20, 0, tzinfo=NY)  # at start
    assert passes[1] == datetime(2026, 11, 11, 7, 0, tzinfo=NY)  # 11 h later, not 24
    assert passes[2] == datetime(2026, 11, 12, 7, 0, tzinfo=NY)
    assert slept == [11 * 3600, 24 * 3600]

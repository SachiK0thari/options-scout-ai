"""The compose scheduler: the daily jobs at a fixed New York time (W42, W11 step 4).

It replaces a shell loop that ran the jobs and then slept 86,400 s from whenever the container
started, so after a restart the IV snapshot could land at any hour. Now: one pass at start (a
fresh deployment has data at once and the healthcheck's start period is met), then a pass every
day at ``OPTIONS_SCOUT_SCHEDULE_AT`` (default 07:00) America/New_York, after the previous session
has closed. Each job runs in its own process; a failure is logged with its exit code and the
heartbeat is left alone, so the healthcheck turns unhealthy. The IV job skips tickers whose
reading for the expected session is already stored, so the weekend passes cost nothing.

Run: ``python -m options_scout.jobs.scheduler`` (the compose ``scheduler`` service does).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
JOBS: tuple[str, ...] = ("snapshot_iv", "refresh_trends", "refresh_bottlenecks")
DEFAULT_AT = "07:00"
HEARTBEAT = Path(os.environ.get("OPTIONS_SCOUT_HEARTBEAT", "/app/data/scheduler.heartbeat"))


def parse_at(value: str) -> tuple[int, int]:
    hour, minute = (int(x) for x in value.strip().split(":"))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"OPTIONS_SCOUT_SCHEDULE_AT must be HH:MM, got {value!r}")
    return hour, minute


def next_run(now: datetime, at: tuple[int, int]) -> datetime:
    """The next ``at`` o'clock in New York strictly after ``now`` (DST handled by the zone)."""
    local = now.astimezone(NEW_YORK)
    candidate = local.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    if candidate <= local:
        candidate = (local + timedelta(days=1)).replace(
            hour=at[0], minute=at[1], second=0, microsecond=0
        )
    return candidate


def run_pass(
    jobs: Sequence[str] = JOBS,
    runner: Callable[[str], int] | None = None,
    heartbeat: Path = HEARTBEAT,
) -> bool:
    """Run every job once; touch the heartbeat only when all succeeded."""
    run = runner or _run_job
    ok = True
    for job in jobs:
        code = run(job)
        if code != 0:
            print(f"scheduler: {job} failed (exit {code})", file=sys.stderr, flush=True)
            ok = False
    if ok:
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        heartbeat.touch()
    return ok


def _run_job(job: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", f"options_scout.jobs.{job}"], check=False
    ).returncode


def main(
    *,
    now: Callable[[], datetime] = lambda: datetime.now(tz=NEW_YORK),
    sleep: Callable[[float], None] = time.sleep,
    runner: Callable[[str], int] | None = None,
    passes: int | None = None,
    heartbeat: Path = HEARTBEAT,
) -> int:
    at = parse_at(os.environ.get("OPTIONS_SCOUT_SCHEDULE_AT", DEFAULT_AT))
    done = 0
    while True:
        run_pass(runner=runner, heartbeat=heartbeat)
        done += 1
        if passes is not None and done >= passes:
            return 0
        current = now()
        target = next_run(current, at)
        print(f"scheduler: next pass at {target.isoformat()}", flush=True)
        sleep(max((target - current).total_seconds(), 0.0))


if __name__ == "__main__":
    raise SystemExit(main())

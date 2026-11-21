"""Print or install the weekly local jobs. No remote writes.

Friday at 16:00 this checkout syncs GitHub read-only, assembles the digest if
the cache changed, then assembles the maintenance note. Nothing is posted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "SteadWeekly"


class ScheduleError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def weekly_command(root: Path) -> str:
    """One command a scheduler can run. It stays inside this checkout."""
    exe = sys.executable
    folder = str(root)
    return (
        f'cd /d "{folder}" && "{exe}" -m stead sync github --limit 30 --digest '
        f'&& "{exe}" -m stead factory run --factory context-maintenance --shadow'
    )


def show(root: Path) -> str:
    command = weekly_command(root)
    return (
        f"Weekly Friday 16:00, from {root}\n"
        "Read-only sync, then a local digest if the cache changed, then a\n"
        "maintenance draft. Nothing is posted, pushed, or merged.\n\n"
        f"Command:\n{command}\n\n"
        "Windows:\n"
        f'schtasks /Create /TN {TASK_NAME} /SC WEEKLY /D FRI /ST 16:00 '
        f'/TR "cmd /c {command}" /F\n\n'
        "cron:\n"
        f"0 16 * * 5 {command}\n"
    )


def install(root: Path, *, runner=None, platform: str | None = None) -> str:
    """Create the current user's weekly task. Does not touch GitHub."""
    if (platform or sys.platform) != "win32":
        raise ScheduleError("this install is for Windows Task Scheduler. Use `stead schedule show` for the cron line.")
    command = weekly_command(root)
    argv = [
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "WEEKLY", "/D", "FRI",
        "/ST", "16:00", "/TR", f"cmd /c {command}", "/F",
    ]
    if any(part in {"push", "merge", "pr"} for part in argv):
        raise ScheduleError("refusing a schedule that writes to GitHub")
    run = runner or _run
    run(argv)
    return TASK_NAME


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ScheduleError(detail or "schtasks failed") from exc
    except FileNotFoundError as exc:
        raise ScheduleError("schtasks is not installed") from exc
    return done.stdout or ""

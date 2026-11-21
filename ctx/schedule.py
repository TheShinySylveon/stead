"""Print or install the weekly local jobs. No remote writes.

Friday at 16:00 this checkout syncs GitHub read-only, assembles the digest if
the cache changed, then assembles the maintenance note. With `--project`, it
also assembles that project's status. Nothing is posted.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SteadWeekly"
_PROJECT = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class ScheduleError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def weekly_command(root: Path, project: str | None = None) -> str:
    """One command a scheduler can run. It stays inside this checkout."""
    exe = sys.executable
    folder = str(root)
    command = (
        f'cd /d "{folder}" && "{exe}" -m stead sync github --limit 30 --digest '
        f'&& "{exe}" -m stead factory run --factory context-maintenance --shadow'
    )
    if project:
        project = project.strip()
        if not _PROJECT.match(project):
            raise ScheduleError("project must be a plain id, not a shell fragment")
        command += (
            f' && "{exe}" -m stead factory run --factory weekly-project-status '
            f'--project {project} --shadow'
        )
    return command


def launcher_path(root: Path) -> Path:
    """Short, stable path for Task Scheduler. The command itself is too long."""
    return root / "private" / "run-weekly.cmd"


def _write_launcher(root: Path, command: str) -> Path:
    path = launcher_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@echo off\r\n" + command + "\r\n", encoding="utf-8")
    return path


def show(root: Path, project: str | None = None) -> str:
    command = weekly_command(root, project)
    extra = f", and {project}'s status" if project else ""
    return (
        f"Weekly Friday 16:00, from {root}\n"
        f"Read-only sync, a local digest if the cache changed, a maintenance\n"
        f"draft{extra}. Nothing is posted, pushed, or merged.\n\n"
        f"Command:\n{command}\n\n"
        "Windows (install writes this to private/run-weekly.cmd so the task\n"
        "command stays under the 261 character limit):\n"
        f'schtasks /Create /TN {TASK_NAME} /SC WEEKLY /D FRI /ST 16:00 '
        f'/TR "cmd /c {launcher_path(root)}" /F\n\n'
        "cron:\n"
        f"0 16 * * 5 {command}\n"
    )


def install(root: Path, *, runner=None, platform: str | None = None,
            project: str | None = None) -> str:
    """Create the current user's weekly task. Does not touch GitHub."""
    if (platform or sys.platform) != "win32":
        raise ScheduleError("this install is for Windows Task Scheduler. Use `stead schedule show` for the cron line.")
    command = weekly_command(root, project)
    launcher = _write_launcher(root, command)
    trigger = f'cmd /c "{launcher}"'
    if len(trigger) > 261:
        raise ScheduleError("the launcher path is too long for Task Scheduler")
    argv = [
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "WEEKLY", "/D", "FRI",
        "/ST", "16:00", "/TR", trigger, "/F",
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

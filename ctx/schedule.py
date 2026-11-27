"""Print or install the weekly local jobs. No remote writes.

Friday at 16:00 this checkout syncs GitHub read-only, assembles the digest if
the cache changed, then assembles the maintenance note. With `--project`, it
also assembles that project's status. Nothing is posted.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SteadWeekly"
_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
# The folder that holds the Stead code (`ctx/` and `stead/`), where the
# scheduled command runs so `python -m stead` resolves. The store is a separate
# `--root`, so the two folders may differ (as they do for a dogfood run).
_CODE_DIR = str(Path(__file__).resolve().parents[1])


def _stead(store: str) -> str:
    """The `python -m stead` prefix for a scheduled call, pointed at a store."""
    return f'"{sys.executable}" -m stead --root "{store}"'


def _posix_dq(value: str) -> str:
    """Double-quote a path for POSIX sh, escaping command/var expansions."""
    escaped = value.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def _stead_posix(store: str) -> str:
    return f"{_posix_dq(sys.executable)} -m stead --root {_posix_dq(store)}"


class ScheduleError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def weekly_command(root: Path, project: str | None = None, *,
                   watch: bool = False, merge: bool = False) -> str:
    """One command a scheduler can run. It changes into the code folder and
    points every `stead` call at the store with `--root`."""
    if merge and not watch:
        raise ScheduleError("--merge needs --watch")
    stead = _stead(str(root))
    command = (
        f'cd /d "{_CODE_DIR}" && {stead} sync github --limit 30 --digest '
        f'&& {stead} factory run --factory context-maintenance --shadow'
    )
    if project:
        project = project.strip()
        if not _PROJECT.match(project):
            raise ScheduleError("project must be a plain id, not a shell fragment")
        command += (
            f' && {stead} factory run --factory weekly-project-status '
            f'--project {project} --shadow'
        )
    if watch:
        command += (
            f' && {stead} factory watch --build --publish'
            + (" --merge" if merge else "")
        )
    return command


def monitor_command(root: Path, *, watch: bool = True, merge: bool = False) -> str:
    """The shorter monitor cadence (Windows `cmd` syntax): read-only sync, then
    auto-draft any new spec, then watch/build enabled specs. The weekly digest
    and maintenance jobs stay on the weekly schedule."""
    if merge and not watch:
        raise ScheduleError("--merge needs --watch")
    stead = _stead(str(root))
    command = (f'cd /d "{_CODE_DIR}" && {stead} sync github --limit 30'
               f' && {stead} spec draft --all')
    if watch:
        command += (f' && {stead} factory watch --build --publish'
                    + (" --merge" if merge else ""))
    return command


def _weekly_posix(root: Path, project: str | None = None, *,
                  watch: bool = False, merge: bool = False) -> str:
    if merge and not watch:
        raise ScheduleError("--merge needs --watch")
    stead = _stead_posix(str(root))
    command = (
        f"cd {_posix_dq(_CODE_DIR)} && {stead} sync github --limit 30 --digest "
        f"&& {stead} factory run --factory context-maintenance --shadow"
    )
    if project:
        project = project.strip()
        if not _PROJECT.match(project):
            raise ScheduleError("project must be a plain id, not a shell fragment")
        command += (
            f" && {stead} factory run --factory weekly-project-status "
            f"--project {project} --shadow"
        )
    if watch:
        command += (
            f" && {stead} factory watch --build --publish"
            + (" --merge" if merge else "")
        )
    return command


def _monitor_posix(root: Path, *, watch: bool = True, merge: bool = False) -> str:
    """The monitor command in POSIX syntax, for the cron line."""
    stead = _stead_posix(str(root))
    command = (f"cd {_posix_dq(_CODE_DIR)} && {stead} sync github --limit 30"
               f" && {stead} spec draft --all")
    if watch:
        command += (f" && {stead} factory watch --build --publish"
                    + (" --merge" if merge else ""))
    return command


def monitor_launcher_path(root: Path) -> Path:
    """Short, stable path for the monitor task. Distinct from the weekly job."""
    return root / "private" / "run-monitor.cmd"


def monitor_show(root: Path, *, interval: str = "hourly", watch: bool = True,
                 merge: bool = False) -> str:
    """The command a shorter scheduler runs, printed with the cron/task line."""
    if interval not in ("hourly", "daily"):
        raise ScheduleError("interval must be hourly or daily")
    if interval == "hourly":
        cron, schtasks = "0 * * * *", "HOURLY"
    else:
        cron, schtasks = "0 9 * * *", "DAILY /ST 09:00"
    return (
        f"Monitor ({interval}), from {root}\n"
        f"Read-only sync, then an auto-draft of new specs, then a watched "
        f"build + publish for enabled specs. Nothing merges unless the repo "
        f"says reach: merge.\n\n"
        "Windows Task Scheduler (install writes this to "
        "private/run-monitor.cmd):\n"
        f'schtasks /Create /TN SteadMonitor /SC {schtasks} '
        f'/TR "cmd /c \\"{monitor_launcher_path(root)}\\"" /F\n\n'
        f"cron:\n{cron} {_monitor_posix(root, watch=watch, merge=merge)}\n"
    )


def launcher_path(root: Path) -> Path:
    """Short, stable path for Task Scheduler. The command itself is too long."""
    return root / "private" / "run-weekly.cmd"


def _write_launcher(root: Path, command: str, name: str = "run-weekly.cmd") -> Path:
    path = root / "private" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@echo off\r\n" + command + "\r\n", encoding="utf-8")
    return path


def show(root: Path, project: str | None = None, *, watch: bool = False,
         merge: bool = False) -> str:
    command = weekly_command(root, project, watch=watch, merge=merge)
    extra = f", and {project}'s status" if project else ""
    build = ", and a model build + PR for every watched spec" if watch else ""
    merged = " A merged PR needs reach: merge and green checks." if merge else ""
    return (
        f"Weekly Friday 16:00, from {root}\n"
        f"Read-only sync, a local digest if the cache changed, a maintenance\n"
        f"draft{extra}{build}.{merged} Nothing runs in shadow.\n\n"
        f"Command:\n{command}\n\n"
        "Windows (install writes this to private/run-weekly.cmd so the task\n"
        "command stays under the 261 character limit):\n"
        f'schtasks /Create /TN {TASK_NAME} /SC WEEKLY /D FRI /ST 16:00 '
        f'/TR "cmd /c \\"{launcher_path(root)}\\"" /F\n\n'
        "cron:\n"
        f"0 16 * * 5 {_weekly_posix(root, project, watch=watch, merge=merge)}\n"
    )


def install(root: Path, *, runner=None, platform: str | None = None,
            project: str | None = None, watch: bool = False,
            merge: bool = False) -> str:
    """Create the current user's weekly task. Does not touch GitHub itself."""
    if (platform or sys.platform) != "win32":
        raise ScheduleError("this install is for Windows Task Scheduler. Use `stead schedule show` for the cron line.")
    command = weekly_command(root, project, watch=watch, merge=merge)
    launcher = _write_launcher(root, command)
    trigger = f'cmd /c "{launcher}"'
    if len(trigger) > 261:
        raise ScheduleError("the launcher path is too long for Task Scheduler")
    argv = [
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "WEEKLY", "/D", "FRI",
        "/ST", "16:00", "/TR", trigger, "/F",
    ]
    run = runner or _run
    run(argv)
    return TASK_NAME


def install_monitor(root: Path, *, runner=None, platform: str | None = None,
                    interval: str = "hourly", watch: bool = True,
                    merge: bool = False) -> str:
    """Create the current user's shorter monitor task (Windows)."""
    if interval not in ("hourly", "daily"):
        raise ScheduleError("interval must be hourly or daily")
    if (platform or sys.platform) != "win32":
        raise ScheduleError(
            "this install is for Windows Task Scheduler. Use "
            "`stead schedule show --interval` for the cron line.")
    if merge and not watch:
        raise ScheduleError("--merge needs --watch")
    command = monitor_command(root, watch=watch, merge=merge)
    launcher = _write_launcher(root, command, name="run-monitor.cmd")
    trigger = f'cmd /c "{launcher}"'
    if len(trigger) > 261:
        raise ScheduleError("the launcher path is too long for Task Scheduler")
    if interval == "hourly":
        argv = ["schtasks", "/Create", "/TN", "SteadMonitor",
                "/SC", "HOURLY", "/TR", trigger, "/F"]
    else:
        argv = ["schtasks", "/Create", "/TN", "SteadMonitor",
                "/SC", "DAILY", "/ST", "09:00", "/TR", trigger, "/F"]
    run = runner or _run
    run(argv)
    return "SteadMonitor"


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ScheduleError(detail or "schtasks failed") from exc
    except FileNotFoundError as exc:
        raise ScheduleError("schtasks is not installed") from exc
    return done.stdout or ""

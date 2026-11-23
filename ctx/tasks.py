"""Background tasks for the cockpit.

Long model operations (build, spec draft, review) run off the HTTP request in a
daemon thread and are polled by id. A task carries bounded progress lines, a
status, and a result or error. This is the cockpit's view only — the durable
record stays in the build-record and run folders, not here, and a server
restart forgets any in-flight task.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

PROGRESS_KEEP = 200


@dataclass
class Task:
    id: str
    kind: str
    target: str
    started: float = field(default_factory=time.time)
    status: str = "running"  # running | done | failed
    result: dict | None = None
    error: str = ""
    lines: list[str] = field(default_factory=list)
    line_count: int = 0  # monotonic total of lines ever appended

    def snapshot(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "target": self.target,
            "status": self.status, "started": self.started,
            "elapsed": round(time.time() - self.started, 1),
            "error": self.error, "result": self.result,
            "progress": list(self.lines[-PROGRESS_KEEP:]),
            "progress_total": self.line_count,
        }


class TaskRunner:
    """A small registry of in-flight tasks. Not persisted."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._tasks: dict[str, Task] = {}

    def start(self, kind: str, target: str, fn) -> str:
        """Run ``fn(progress)`` in a background thread; return the task id.

        ``progress(line)`` appends a line to the task's tail. ``fn``'s return
        value becomes the task result; an exception makes status ``failed``."""

        with self._lock:
            self._seq += 1
            task_id = f"{int(time.time())}-{self._seq}"
            task = Task(id=task_id, kind=kind, target=target)
            self._tasks[task_id] = task

        def progress(line: str) -> None:
            with self._lock:
                task.lines.append(str(line))
                task.line_count += 1
                del task.lines[:-PROGRESS_KEEP]

        def run() -> None:
            try:
                task.result = fn(progress)
                task.status = "done"
            except BaseException as exc:  # noqa: BLE001 — surfaced to the poller
                task.status = "failed"
                task.error = (str(exc).splitlines()[0][:400]
                              if str(exc) else type(exc).__name__)

        threading.Thread(target=run, daemon=True, name=f"stead-task-{task_id}").start()
        return task_id

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
        return task.snapshot() if task else None

    def list(self) -> list[dict]:
        with self._lock:
            return [task.snapshot() for task in self._tasks.values()]

    def active_targets(self) -> set[str]:
        """The targets of tasks still running, so deletion can refuse to touch
        a contribution a background build or draft is mid-way through."""
        with self._lock:
            return {task.target for task in self._tasks.values()
                    if task.status == "running"}

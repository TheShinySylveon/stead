"""The cockpit's background task runner."""

from __future__ import annotations

import time
import unittest

from ctx.tasks import TaskRunner


def _settled(runner: TaskRunner, task_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = runner.get(task_id)
        if snap["status"] != "running":
            return snap
        time.sleep(0.01)
    return runner.get(task_id)


class TaskRunnerTest(unittest.TestCase):
    def test_task_runs_to_done_and_returns_result(self) -> None:
        runner = TaskRunner()
        task_id = runner.start("build", "contribution-x",
                               lambda progress: {"branch": "stead/1-x"})
        snap = _settled(runner, task_id)
        self.assertEqual(snap["kind"], "build")
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["branch"], "stead/1-x")

    def test_task_records_progress_lines(self) -> None:
        runner = TaskRunner()
        task_id = runner.start("build", "x",
                               lambda progress: progress("step 1") or {"ok": True})
        snap = _settled(runner, task_id)
        self.assertEqual(snap["status"], "done", snap)
        self.assertIn("step 1", snap["progress"])

    def test_task_failure_surfaces_the_error(self) -> None:
        runner = TaskRunner()

        def boom(_progress):
            raise RuntimeError("boom")

        task_id = runner.start("draft", "x", boom)
        snap = _settled(runner, task_id)
        self.assertEqual(snap["status"], "failed", snap)
        self.assertIn("boom", snap["error"])

    def test_unknown_task_is_none(self) -> None:
        self.assertIsNone(TaskRunner().get("nope"))


if __name__ == "__main__":
    unittest.main()

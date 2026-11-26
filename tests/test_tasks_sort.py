"""The `--sort` flag on `stead task list` orders by title, then status."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from ctx import cli, db
from tests.test_ctx import CtxTestCase


class TestTaskListSort(CtxTestCase):
    def setUp(self) -> None:
        super().setUp()
        db.init_db(self.root)
        # Two same-titled tasks, inserted done-then-blocked, plus one banana.
        cli.cmd_task_add(self.root, "apple", "project-demo", status="done")
        cli.cmd_task_add(self.root, "apple", "project-demo", status="blocked")
        cli.cmd_task_add(self.root, "banana", "project-demo")

    def _statuses(self, **kwargs) -> list[str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.cmd_task_list(self.root, **kwargs)
        # Row format: id  status  title. Status is the 2nd token.
        return [line.split()[1] for line in buf.getvalue().splitlines()
                if line.strip() and not line.startswith("(")]

    def test_sort_orders_by_status_within_same_title(self) -> None:
        # apple/blocked, apple/done (status ascending), then banana.
        self.assertEqual(self._statuses(sort=True),
                         ["blocked", "done", "to-do"])

    def test_without_sort_preserves_id_order(self) -> None:
        # Default ORDER BY id: apple (done, inserted first), apple-2 (blocked),
        # then banana.
        self.assertEqual(self._statuses(),
                         ["done", "blocked", "to-do"])

    def test_help_mentions_sort(self) -> None:
        parser = cli.build_parser()
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                parser.parse_args(["task", "list", "--help"])
            except SystemExit:
                pass
        self.assertIn("--sort", buf.getvalue())
        self.assertIn("sort tasks by title, then status", buf.getvalue())


if __name__ == "__main__":
    import unittest
    unittest.main()

"""Local cockpit: snapshot, writes through the CLI, loopback HTTP, shadow-only."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ctx import cli, db, frontmatter, ui


def make_root(base: Path) -> Path:
    root = base / "repo"
    for sub in ("context/projects", "context/tasks", "context/documents",
                "context/meetings", "context/repos", "context/contributions",
                "inbox", "factories/weekly-project-status/prompts",
                "factories/weekly-project-status/evals"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    meta = {"id": "project-demo", "type": "project", "title": "Demo Project",
            "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
    (root / "context/projects/demo.md").write_text(
        frontmatter.dumps(meta, "# Demo Project\n\nA test project.\n"), encoding="utf-8")
    (root / "factories/weekly-project-status/FACTORY.md").write_text(
        "# FACTORY: weekly-project-status\n", encoding="utf-8")
    (root / "factories/weekly-project-status/prompts/v1.md").write_text(
        "Draft a weekly status update from the bundle below.\n", encoding="utf-8")
    (root / "inbox/README.md").write_text("# Inbox\n", encoding="utf-8")
    return root


class UiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))
        db.init_db(self.root)
        cli.cmd_task_add(self.root, "Write the cockpit", "project-demo", "doing")


class TestSnapshot(UiTestCase):
    def test_snapshot_reads_markdown(self) -> None:
        snap = ui.snapshot(self.root)
        self.assertEqual(snap["counts"]["open_tasks"], 1)
        self.assertEqual(snap["tasks"][0]["title"], "Write the cockpit")
        self.assertEqual(snap["tasks"][0]["status"], "doing")
        self.assertEqual(snap["attention"][0]["tone"], "doing")
        self.assertIn("spec-kit", snap["choices"]["method"])

    def test_status_write_goes_through_the_file(self) -> None:
        ui.set_task_status(self.root, "task-write-the-cockpit", "blocked")
        found = __import__("ctx").objects.find(self.root, "task", "task-write-the-cockpit")
        self.assertEqual(found[1]["status"], "blocked")
        snap = ui.snapshot(self.root)
        self.assertEqual(snap["tasks"][0]["status"], "blocked")

    def test_capture_lands_in_inbox_and_rejects_empty(self) -> None:
        saved = ui.capture(self.root, "../secret notes", "remember this")
        self.assertTrue(saved["name"].endswith("-secret-notes.md"))
        self.assertFalse((self.root / "secret notes.md").exists())
        text = (self.root / saved["path"]).read_text(encoding="utf-8")
        self.assertIn("remember this", text)
        self.assertIn("Triage into context/", text)
        with self.assertRaises(ui.UiError):
            ui.capture(self.root, "  ", "nope")

    def test_detail_and_inbox_reject_traversal(self) -> None:
        with self.assertRaises(ui.UiError) as bad_type:
            ui.object_detail(self.root, "../ctx", "cli")
        self.assertEqual(bad_type.exception.status, 404)
        with self.assertRaises(ui.UiError):
            ui.read_inbox(self.root, "../context/projects/demo.md")
        with self.assertRaises(ui.UiError):
            ui.read_inbox(self.root, "README.md")

    def test_live_factory_run_is_rejected(self) -> None:
        with self.assertRaises(ui.UiError) as rejected:
            ui.shadow_run(self.root, {"factory": "weekly-project-status",
                                      "project": "project-demo", "live": True})
        self.assertIn("shadow", str(rejected.exception))
        conn = db.connect(self.root)
        try:
            count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_shadow_run_records_without_returning_the_prompt(self) -> None:
        result = ui.shadow_run(self.root, {"factory": "weekly-project-status",
                                            "project": "project-demo"})
        self.assertEqual(result["mode"], "shadow")
        self.assertNotIn("assembled_prompt", result)
        self.assertTrue((self.root / result["run_dir"] / "prompt.md").is_file())


class TestHttp(UiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.httpd = ui.make_server(self.root, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def _stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _request(self, path: str, payload: dict | None = None, token: str | None = None,
                 host: str | None = None) -> tuple[int, dict | str]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method="POST" if payload is not None else "GET")
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-Ctx-Token", token)
        if host is not None:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
                if "json" in resp.headers.get("Content-Type", ""):
                    return resp.status, json.loads(body)
                return resp.status, body.decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw.decode("utf-8")
            return exc.status, parsed

    def test_page_is_local_and_tokenized(self) -> None:
        status, page = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn(self.httpd.token, page)
        self.assertNotIn("__CTX_TOKEN__", page)
        self.assertNotIn("<script src=", page)
        self.assertNotIn("http://", page.replace(self.base, ""))

    def test_post_requires_token_and_loopback(self) -> None:
        status, body = self._request("/api/task/status",
                                     {"id": "task-write-the-cockpit", "status": "done"})
        self.assertEqual(status, 403)
        self.assertIn("token", body["error"])
        status, body = self._request("/api/snapshot", host="evil.example")
        self.assertEqual(status, 403)
        self.assertIn("loopback", body["error"])

    def test_token_can_change_a_task(self) -> None:
        status, body = self._request(
            "/api/task/status",
            {"id": "task-write-the-cockpit", "status": "done"},
            token=self.httpd.token)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        found = __import__("ctx").objects.find(self.root, "task", "task-write-the-cockpit")
        self.assertEqual(found[1]["status"], "done")

    def test_public_bind_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            ui.make_server(self.root, "0.0.0.0", 0)

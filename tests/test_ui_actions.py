"""Every local CLI action has a cockpit endpoint. Remote writes stay out."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ctx import accounts, db, frontmatter, ui


class CockpitActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("context/projects", "context/actors",
                       "factories/weekly-project-status/prompts",
                       "factories/weekly-project-status/evals"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "factories/weekly-project-status/FACTORY.md").write_text(
            "# F\n", encoding="utf-8")
        (self.root / "factories/weekly-project-status/prompts/v1.md").write_text(
            "Draft a status.\n", encoding="utf-8")
        (self.root / "factories/weekly-project-status/prompts/v2.md").write_text(
            "Draft a better status.\n", encoding="utf-8")
        (self.root / "factories/weekly-project-status/evals/eval-demo.json").write_text(
            json.dumps({"id": "eval-demo", "factory": "weekly-project-status",
                        "title": "Demo", "input": "x", "pass_criteria": "y"}),
            encoding="utf-8")
        project = {"id": "project-demo", "type": "project", "title": "Demo",
                   "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
        (self.root / "context/projects/demo.md").write_text(
            frontmatter.dumps(project, "# Demo\n"), encoding="utf-8")
        actor = {"id": "actor-ada", "type": "actor", "title": "Ada",
                 "created": "2026-11-21", "updated": "2026-11-21",
                 "status": "active", "kind": "human"}
        (self.root / "context/actors/ada.md").write_text(
            frontmatter.dumps(actor, "# Ada\n"), encoding="utf-8")
        db.init_db(self.root)
        conn = db.connect(self.root)
        try:
            cur = conn.execute(
                "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, "
                "output, verdict, created) VALUES "
                "('weekly-project-status', 'project-demo', 'project-demo', 'v2', "
                "'shadow', 'On track.', 'approved', '2026-11-21T00:00:00Z')")
            conn.commit()
            self.run_id = cur.lastrowid
        finally:
            conn.close()
        accounts.add(self.root, "ada", "actor-ada", password="long-enough-secret")
        self.httpd = ui.make_server(self.root, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.port = self.httpd.server_address[1]
        self.token = self.httpd.token

    def _stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Ctx-Token", self.token)
        return _read(req)

    def _upload(self, filename: str, data: bytes) -> tuple[int, dict]:
        boundary = "----steadtest"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/inbox/import", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("X-Ctx-Token", self.token)
        return _read(req)

    def test_index_hook_and_schedule(self) -> None:
        self.assertEqual(self._post("/api/init", {})[0], 200)
        status, body = self._post("/api/hook", {"create": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["token"])
        status, body = self._post("/api/schedule", {"project": "project-demo"})
        self.assertEqual(status, 200)
        self.assertIn("weekly-project-status --project project-demo", body["text"])

    def test_account_reset_prints_once(self) -> None:
        status, body = self._post("/api/account/reset", {"name": "ada"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(accounts.verify(self.root, "ada", body["password"]))

    def test_factory_new_eval_and_promote(self) -> None:
        status, body = self._post("/api/factory/new", {"name": "tidy-notes", "title": "Tidy"})
        self.assertEqual(status, 200, body)
        status, body = self._post("/api/eval/run", {"factory": "tidy-notes"})
        self.assertTrue(body["ok"])
        status, body = self._post("/api/prompt/promote", {"factory": "tidy-notes", "version": "v1"})
        self.assertEqual(status, 400)
        self.assertIn("eval-tidy-notes", body["error"])
        results = self.root / "factories/tidy-notes/evals/results"
        results.mkdir(parents=True)
        (results / "eval-tidy-notes.json").write_text(
            json.dumps({"verdict": "pass", "prompt_version": "v1"}), encoding="utf-8")
        status, body = self._post("/api/prompt/promote", {"factory": "tidy-notes", "version": "v1"})
        self.assertEqual(status, 200, body)
        status, body = self._post("/api/prompt/promote", {"factory": "weekly-project-status", "version": "v2"})
        self.assertEqual(status, 400)
        self.assertIn("eval-demo", body["error"])

    def test_file_run_and_watch(self) -> None:
        status, body = self._post("/api/run/file", {"id": self.run_id})
        self.assertEqual(status, 200, body)
        self.assertTrue((self.root / "context/documents").glob("*.md"))
        status, body = self._post("/api/run/file", {"id": self.run_id})
        self.assertEqual(status, 400)
        status, body = self._post("/api/factory/watch", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["ran"], [])

    def test_upload_landed_in_the_inbox(self) -> None:
        status, body = self._upload("note.eml", b"Subject: Ship notes\n\nReady.\n")
        self.assertEqual(status, 200, body)
        notes = list((self.root / "inbox").glob("*.md"))
        self.assertEqual(len(notes), 1)
        self.assertIn("Ready.", notes[0].read_text(encoding="utf-8"))

    def test_run_viewer_returns_the_draft(self) -> None:
        path = f"http://127.0.0.1:{self.port}/api/run?id={self.run_id}"
        req = urllib.request.Request(path)
        req.add_header("X-Ctx-Token", self.token)
        status, body = _read(req)
        self.assertEqual(status, 200)
        self.assertEqual(body["draft"], "On track.")
        self.assertEqual(body["factory"], "weekly-project-status")

    def test_attention_lists_an_object_once(self) -> None:
        contrib = {"id": "contribution-x", "title": "Add caching",
                   "review": "requested", "ci": "fail"}
        rows = ui._attention([], [contrib], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual([label for label, _tone in rows[0]["labels"]],
                         ["Review requested", "CI failing"])
        self.assertEqual(rows[0]["tone"], "fail")

    def test_snapshot_reports_the_served_port(self) -> None:
        view = ui._deployment_view(self.root, 8790)
        self.assertEqual(view["port"], 8790)

    def test_no_remote_write_endpoint_exists(self) -> None:
        for path in ("/api/factory/publish", "/api/factory/merge", "/api/git/push"):
            status, _body = self._post(path, {})
            self.assertEqual(status, 404, path)


def _read(req) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.status, json.loads(exc.read().decode("utf-8"))

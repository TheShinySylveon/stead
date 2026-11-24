"""Every local CLI action has a cockpit endpoint. Remote writes need confirmation."""

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

    def _get(self, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        req.add_header("X-Ctx-Token", self.token)
        return _read(req)

    def _poll_task(self, task_id: str) -> dict:
        import time
        for _ in range(200):
            status, body = self._get(f"/api/task?id={task_id}")
            self.assertEqual(status, 200, body)
            if body.get("status") != "running":
                return body
            time.sleep(0.02)
        return body

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

    def test_factory_new_and_delete_preserve_runs(self) -> None:
        status, body = self._post("/api/factory/new", {"name": "spec-notes", "title": "Spec notes"})
        self.assertEqual(status, 200, body)
        status, snap = self._get("/api/snapshot")
        self.assertEqual(status, 200)
        f = next(x for x in snap["factories"] if x["name"] == "spec-notes")
        self.assertEqual(f["needs"], "project")
        self.assertEqual(f["blurb"], "Spec notes")
        status, body = self._post("/api/factory/delete", {"name": "spec-notes"})
        self.assertEqual(status, 200, body)
        self.assertFalse((self.root / "factories/spec-notes").exists())
        # creating/deleting a factory must not wipe the existing run or reset prompts
        conn = db.connect(self.root)
        run = conn.execute("SELECT verdict FROM runs WHERE id=?", (self.run_id,)).fetchone()
        prod = conn.execute(
            "SELECT status FROM prompt_versions WHERE factory='weekly-project-status' AND version='v2'"
        ).fetchone()[0]
        conn.close()
        self.assertIsNotNone(run)
        self.assertEqual(run[0], "approved")
        self.assertEqual(prod, "production")
        status, body = self._post("/api/factory/delete", {"name": "weekly-project-status"})
        self.assertEqual(status, 400)
        self.assertIn("shipped", body["error"])

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

    def test_delete_refuses_a_linked_project_and_force_removes_it(self) -> None:
        task = {"id": "task-linked", "type": "task", "title": "Linked",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "to-do", "project": "project-demo"}
        (self.root / "context/tasks").mkdir(parents=True)
        (self.root / "context/tasks/linked.md").write_text(
            frontmatter.dumps(task, "# Linked\n"), encoding="utf-8")
        status, body = self._post("/api/object/delete",
                                  {"type": "project", "id": "project-demo"})
        self.assertEqual(status, 400)
        self.assertIn("linked object", body["error"])
        self.assertTrue((self.root / "context/projects/demo.md").is_file())
        status, body = self._post("/api/object/delete",
                                  {"type": "project", "id": "project-demo", "force": True})
        self.assertEqual(status, 200, body)
        self.assertFalse((self.root / "context/projects/demo.md").exists())

    def test_delete_removes_the_index_row(self) -> None:
        status, body = self._post("/api/object/delete",
                                  {"type": "task", "id": "task-linked"})
        self.assertEqual(status, 404)

    def test_delete_contribution_removes_it_and_its_draft(self) -> None:
        (self.root / "context/contributions").mkdir(parents=True)
        issue = {"id": "contribution-me-app-issue-9", "type": "contribution",
                 "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                 "repo": "repo-me-app", "kind": "issue", "number": 9, "role": "author",
                 "state": "open", "visibility": "public"}
        (self.root / "context/contributions/issue-9.md").write_text(
            frontmatter.dumps(issue, "# Flag\n"), encoding="utf-8")
        draft = {"id": "contribution-me-app-issue-9-spec", "type": "contribution",
                 "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                 "repo": "repo-me-app", "kind": "issue", "number": 9, "role": "author",
                 "state": "open", "visibility": "public", "tags": ["feature-spec"],
                 "drafted_from": "contribution-me-app-issue-9"}
        (self.root / "context/contributions/issue-9-spec.md").write_text(
            frontmatter.dumps(draft, "# Flag spec\n"), encoding="utf-8")
        status, body = self._post("/api/object/delete",
                                  {"type": "contribution", "id": "contribution-me-app-issue-9"})
        self.assertEqual(status, 200, body)
        self.assertFalse((self.root / "context/contributions/issue-9.md").exists())
        self.assertFalse((self.root / "context/contributions/issue-9-spec.md").exists())

    def test_delete_contribution_refuses_while_a_task_runs(self) -> None:
        import threading
        from ctx.tasks import TaskRunner
        (self.root / "context/contributions").mkdir(parents=True)
        issue = {"id": "contribution-me-app-issue-9", "type": "contribution",
                 "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                 "repo": "repo-me-app", "kind": "issue", "number": 9, "role": "author",
                 "state": "open", "visibility": "public"}
        (self.root / "context/contributions/issue-9.md").write_text(
            frontmatter.dumps(issue, "# Flag\n"), encoding="utf-8")
        runner = TaskRunner()
        release = threading.Event()
        runner.start("build", "contribution-me-app-issue-9", lambda _p: release.wait(5))
        try:
            with self.assertRaises(ui.UiError):
                ui.delete_object(self.root, "contribution", "contribution-me-app-issue-9",
                                 tasks=runner)
        finally:
            release.set()
        self.assertTrue((self.root / "context/contributions/issue-9.md").exists())

    def test_project_detail_has_a_rollup(self) -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/object?type=project&id=project-demo")
        req.add_header("X-Ctx-Token", self.token)
        status, body = _read(req)
        self.assertEqual(status, 200)
        self.assertEqual(body["rollup"]["counts"]["to-do"], 0)
        self.assertEqual(body["rollup"]["runs"][0]["factory"], "weekly-project-status")

    def test_wiki_endpoint_serves_home_and_page(self) -> None:
        repo = {"id": "repo-me-app", "type": "repo", "title": "My App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "project": "project-demo"}
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# My App\n"), encoding="utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/wiki?repo=repo-me-app")
        req.add_header("X-Ctx-Token", self.token)
        status, body = _read(req)
        self.assertEqual(status, 200)
        self.assertIn("overview", [node["slug"] for node in body["tree"]])
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/wiki?repo=repo-me-app&page=overview")
        req.add_header("X-Ctx-Token", self.token)
        status, body = _read(req)
        self.assertEqual(status, 200)
        self.assertIn("Autonomy ceiling", body["page"]["markdown"])

    def test_wiki_actions_pin_and_request(self) -> None:
        repo = {"id": "repo-me-app", "type": "repo", "title": "My App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "project": "project-demo"}
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# My App\n"), encoding="utf-8")
        status, body = self._post("/api/wiki/action", {
            "action": "pin", "repo": "repo-me-app", "path": "overview", "pinned": True})
        self.assertEqual(status, 200, body)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/wiki?repo=repo-me-app")
        req.add_header("X-Ctx-Token", self.token)
        _status, home = _read(req)
        self.assertIn("overview", home["pinned"])
        status, body = self._post("/api/wiki/action", {
            "action": "request", "repo": "repo-me-app", "page": "overview",
            "title": "Clarify the intro", "text": "Add one sentence about scope."})
        self.assertEqual(status, 200, body)
        request_id = body["id"]
        status, body = self._post("/api/wiki/action", {
            "action": "close_request", "id": request_id})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "done")

    def _seed_build_objects(self) -> None:
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "default_branch": "main",
                "reach": "shadow"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        contrib = {"id": "contribution-me-app-issue-5", "type": "contribution",
                   "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                   "repo": "repo-me-app", "kind": "issue", "number": 5,
                   "role": "assignee", "state": "open", "visibility": "public",
                   "tags": ["feature-spec"]}
        (self.root / "context/contributions/issue-5.md").write_text(
            frontmatter.dumps(contrib, "Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] works\n"),
            encoding="utf-8")

    def _make_shared(self) -> None:
        (self.root / "stead.json").write_text(json.dumps({
            "deployment": "multi", "bind": "0.0.0.0", "port": 8765,
            "access_token": "test-token",
        }), encoding="utf-8")

    def test_spec_approval_endpoint_binds_the_body(self) -> None:
        self._seed_build_objects()
        status, body = self._post("/api/spec/approve",
                                  {"contribution": "contribution-me-app-issue-5"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["sha"])

    def test_shared_server_locks_execution_fields(self) -> None:
        self._seed_build_objects()
        self._make_shared()
        status, body = self._post("/api/repo", {"id": "repo-me-app", "reach": "merge"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))
        status, body = self._post("/api/contribution",
                                  {"id": "contribution-me-app-issue-5", "role": "author"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))
        status, body = self._post("/api/contribution/add", {
            "title": "New spec", "repo": "repo-me-app", "kind": "issue", "number": 6,
            "criteria": "- [ ] something"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))
        status, body = self._post("/api/spec/approve",
                                  {"contribution": "contribution-me-app-issue-5"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))

    def test_shared_server_locks_the_model_endpoint_and_factory_defaults(self) -> None:
        self._make_shared()
        status, body = self._post("/api/model", {
            "provider": "custom", "name": "evil", "base_url": "https://attacker.example/v1"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))
        status, body = self._post("/api/factory/defaults", {
            "trigger": "watch", "reach": "pr"})
        self.assertEqual(status, 400)
        self.assertIn("read-only", body.get("error", ""))
        raw = json.loads((self.root / "stead.json").read_text(encoding="utf-8"))
        self.assertNotIn("attacker.example", json.dumps(raw))
        self.assertNotIn("factory", raw)

    def test_build_is_refused_on_a_shared_server(self) -> None:
        (self.root / "stead.json").write_text(json.dumps({
            "deployment": "multi", "bind": "0.0.0.0", "port": 8765,
            "access_token": "test-token",
        }), encoding="utf-8")
        status, body = self._post("/api/build", {"contribution": "missing"})
        self.assertEqual(status, 400)
        self.assertIn("shared server", body.get("error", ""))

    def test_watch_publish_requires_confirmation(self) -> None:
        import unittest.mock as mock
        from ctx import factory
        seen = {}

        def fake(root, **kw):
            seen.update(kw)
            return {"ran": [], "skipped": []}

        with mock.patch.object(factory, "watch_specs", fake):
            # a remote write is refused without confirmation
            status, body = self._post("/api/factory/watch", {
                "build": True, "publish": True})
            self.assertEqual(status, 400, body)
            self.assertIn("Confirm", body.get("error", ""))
            # with confirmation, publish and merge pass through
            status, body = self._post("/api/factory/watch", {
                "build": True, "publish": True, "merge": True, "confirm": True})
        self.assertEqual(status, 200, body)
        self.assertTrue(seen["build"])
        self.assertTrue(seen["publish"])
        self.assertTrue(seen["merge"])

    def test_watch_build_is_refused_on_a_shared_server(self) -> None:
        (self.root / "stead.json").write_text(json.dumps({
            "deployment": "multi", "bind": "0.0.0.0", "port": 8765,
            "access_token": "test-token",
        }), encoding="utf-8")
        status, body = self._post("/api/factory/watch", {"build": True})
        self.assertEqual(status, 400)
        self.assertIn("shared server", body.get("error", ""))

    def test_build_endpoint_runs_async_and_reports_progress(self) -> None:
        import unittest.mock as mock
        from ctx import agent
        seen = {}

        def fake(root, contribution, **kw):
            seen.update(kw)
            kw["progress"]("one line of progress")
            return {"ok": True, "files": ["app.py"], "branch": "stead/1-x",
                    "checks": ""}

        with mock.patch.object(agent, "build", fake):
            status, body = self._post("/api/build", {
                "contribution": "contribution-x", "max_minutes": 90,
                "max_tokens": 1000000, "max_cost": 2.5})
        self.assertEqual(status, 200, body)
        self.assertIn("task", body)
        snap = self._poll_task(body["task"])
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["branch"], "stead/1-x")
        self.assertEqual(snap["progress"], ["one line of progress"])
        self.assertEqual(seen["max_minutes"], 90)
        self.assertEqual(seen["max_tokens"], 1000000)
        self.assertEqual(seen["max_cost"], 2.5)

    def test_search_endpoint_returns_matches(self) -> None:
        status, body = self._get("/api/search?q=Demo")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)
        self.assertTrue(any("Demo" in (r.get("snippet") or "") for r in body), body)

    def test_eval_judge_uses_the_latest_draft(self) -> None:
        import unittest.mock as mock
        from ctx import models
        settings = {"provider": "openai", "name": "test", "base_url": "", "api_key": "k",
                    "key_env": "STEAD_MODEL_API_KEY", "key_from": "stead.json"}
        with mock.patch.object(models, "resolve", lambda root: settings), \
             mock.patch.object(models, "complete",
                               lambda *a, **k: "verdict: pass\nreason: fits the bundle"):
            status, body = self._post("/api/eval/judge", {
                "factory": "weekly-project-status", "case": "eval-demo", "version": "v2"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["verdict"], "pass")
        self.assertEqual(body["prompt_version"], "v2")

    def test_eval_status_lists_cases_without_a_result(self) -> None:
        status, body = self._post("/api/eval/status",
                                  {"factory": "weekly-project-status", "version": "v2"})
        self.assertEqual(status, 200)
        self.assertEqual(body["cases"][0]["id"], "eval-demo")
        self.assertFalse(body["cases"][0]["ok"])

    def test_snapshot_reports_the_version(self) -> None:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/snapshot")
        req.add_header("X-Ctx-Token", self.token)
        status, body = _read(req)
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], "0.1.0")

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

    def test_remote_writes_need_confirmation_and_no_arbitrary_endpoint(self) -> None:
        for path in ("/api/factory/publish", "/api/factory/merge"):
            status, body = self._post(path, {"contribution": "contribution-x"})
            self.assertEqual(status, 400, path)
            self.assertIn("Confirm", body.get("error", ""))
        status, _body = self._post("/api/git/push", {})
        self.assertEqual(status, 404)

    def test_spec_draft_endpoint_starts_a_task(self) -> None:
        import unittest.mock as mock
        from ctx import spec
        with mock.patch.object(spec, "draft_spec",
                               lambda root, contribution, **kw: {"id": "d-spec",
                                                                 "path": "d.md"}):
            status, body = self._post("/api/spec/draft",
                                      {"contribution": "contribution-x"})
        self.assertEqual(status, 200, body)
        snap = self._poll_task(body["task"])
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["id"], "d-spec")

    def test_doctor_endpoint_reports_problems(self) -> None:
        status, body = self._get("/api/doctor")
        self.assertEqual(status, 200)
        self.assertIn("errors", body)

    def test_factory_stop_and_start(self) -> None:
        status, body = self._post("/api/factory/stop", {})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["stopped"])
        status, body = self._post("/api/factory/start", {})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["stopped"])

    def test_publish_with_confirm_calls_publish(self) -> None:
        import unittest.mock as mock
        from ctx import publish
        with mock.patch.object(publish, "publish",
                               lambda root, contribution, **kw: {"url": "https://x",
                                                                 "branch": "b"}):
            status, body = self._post("/api/factory/publish", {
                "contribution": "contribution-x", "confirm": True})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["url"], "https://x")


def _read(req) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.status, json.loads(exc.read().decode("utf-8"))


class PipelineStageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context/contributions").mkdir(parents=True)
        (self.root / "context/documents").mkdir(parents=True)

    def _contrib(self, meta, stem, body):
        (self.root / "context/contributions" / f"{stem}.md").write_text(
            frontmatter.dumps(meta, body), encoding="utf-8")

    def _row(self):
        rows = ui._pipeline_contribs(self.root)
        return rows[0]

    def _source(self, tags=("stead-build",), state="open"):
        meta = {"id": "contribution-me-app-issue-9", "type": "contribution",
                "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": 9,
                "role": "author", "state": state, "visibility": "public",
                "tags": list(tags)}
        self._contrib(meta, "issue-9", "# Flag\n")
        return meta

    def _draft(self, body="# Flag spec\n", spec_sha=None, state="open"):
        meta = {"id": "contribution-me-app-issue-9-spec", "type": "contribution",
                "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": 9,
                "role": "author", "state": state, "visibility": "public",
                "tags": ["feature-spec"], "drafted_from": "contribution-me-app-issue-9"}
        if spec_sha is not None:
            meta["spec_sha"] = spec_sha
        self._contrib(meta, "issue-9-spec", body)
        return meta

    def _record(self, outcome, branch="stead/9-flag", spec_sha="", pr_url=None,
                commented=False):
        rec = {"id": "document-rec", "type": "document", "title": "rec",
               "created": "2026-11-21", "updated": "2026-11-21",
               "tags": ["build-record"],
               "contribution": "contribution-me-app-issue-9-spec",
               "branch": branch, "outcome": outcome, "spec_sha": spec_sha}
        if pr_url:
            rec["pr_url"] = pr_url
        if commented:
            rec["commented"] = "true"
        (self.root / "context/documents/rec.md").write_text(
            frontmatter.dumps(rec, "# rec\n"), encoding="utf-8")

    def test_ready_to_draft_when_no_spec_exists(self):
        self._source()
        row = self._row()
        self.assertEqual(row["stage"], "draft")
        self.assertEqual([a["key"] for a in row["actions"]], ["draft"])

    def test_drafted_needs_approval(self):
        self._source()
        self._draft()
        row = self._row()
        self.assertEqual(row["stage"], "drafted")
        self.assertEqual([a["key"] for a in row["actions"]], ["approve"])
        self.assertEqual(row["act_id"], "contribution-me-app-issue-9-spec")

    def test_approved_needs_build(self):
        from ctx import spec
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        row = self._row()
        self.assertEqual(row["stage"], "approved")
        self.assertEqual([a["key"] for a in row["actions"]], ["build"])

    def test_changed_body_needs_reapproval(self):
        from ctx import spec
        self._source()
        self._draft(body="# Flag spec\n", spec_sha=spec.body_hash("# Old body\n"))
        row = self._row()
        self.assertEqual(row["stage"], "drafted")
        self.assertEqual([a["key"] for a in row["actions"]], ["approve"])

    def test_authored_spec_needs_no_drafting(self):
        self._source(tags=("feature-spec",))
        row = self._row()
        self.assertEqual(row["stage"], "drafted")
        self.assertEqual([a["key"] for a in row["actions"]], ["approve"])
        self.assertEqual(row["act_id"], "contribution-me-app-issue-9")

    def test_failed_build_is_not_built(self):
        from ctx import spec
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("failed", spec_sha=spec.body_hash(body))
        row = self._row()
        self.assertEqual(row["stage"], "approved")
        self.assertEqual([a["key"] for a in row["actions"]], ["build"])

    def test_stale_record_for_an_old_hash_is_not_built(self):
        from ctx import spec
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("committed", spec_sha=spec.body_hash("# Old body\n"))
        row = self._row()
        self.assertEqual(row["stage"], "approved")

    def test_successful_build_offers_publish(self):
        from ctx import spec
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("committed", spec_sha=spec.body_hash(body))
        row = self._row()
        self.assertEqual(row["stage"], "built")
        self.assertEqual([a["key"] for a in row["actions"]], ["publish"])

    def _repo(self, reach="merge", allow_comment=True, kind="own"):
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        meta = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": kind, "default_branch": "main",
                "reach": reach}
        if allow_comment:
            meta["allow_comment"] = True
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(meta, "# App\n"), encoding="utf-8")

    def test_published_offers_merge_and_comment(self):
        from ctx import spec
        self._repo()
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("published", spec_sha=spec.body_hash(body),
                     pr_url="https://github.com/me/app/pull/7")
        row = self._row()
        self.assertEqual(row["stage"], "published")
        self.assertEqual([a["key"] for a in row["actions"]], ["merge", "comment", "address"])

    def test_published_without_comment_offers_merge_only(self):
        from ctx import spec
        self._repo(allow_comment=False)
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("published", spec_sha=spec.body_hash(body),
                     pr_url="https://github.com/me/app/pull/7")
        row = self._row()
        self.assertEqual(row["stage"], "published")
        self.assertEqual([a["key"] for a in row["actions"]], ["merge", "address"])

    def test_merged_build_shows_merged(self):
        from ctx import spec
        self._repo()
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("merged", spec_sha=spec.body_hash(body),
                     pr_url="https://github.com/me/app/pull/7")
        row = self._row()
        self.assertEqual(row["stage"], "merged")
        self.assertEqual(row["actions"], [])

    def test_closed_source_does_not_offer_build(self):
        from ctx import spec
        self._source(state="closed")
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        row = self._row()
        self.assertEqual(row["stage"], "closed")
        self.assertEqual(row["actions"], [])

    def test_merged_draft_wins_when_source_is_closed(self):
        from ctx import spec
        self._source(state="closed")
        self._draft(body="# Flag spec\n", spec_sha=spec.body_hash("# Flag spec\n"),
                    state="merged")
        row = self._row()
        self.assertEqual(row["stage"], "merged")
        self.assertEqual(row["actions"], [])

    def test_commented_record_skips_comment(self):
        from ctx import spec
        self._repo()
        self._source()
        body = "# Flag spec\n"
        self._draft(body=body, spec_sha=spec.body_hash(body))
        self._record("published", spec_sha=spec.body_hash(body),
                     pr_url="https://github.com/me/app/pull/7", commented=True)
        row = self._row()
        self.assertEqual(row["stage"], "published")
        self.assertEqual([a["key"] for a in row["actions"]], ["merge", "address"])

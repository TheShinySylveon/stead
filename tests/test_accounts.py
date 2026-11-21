"""Shared-server sign-in is a person. The password is a hash, not a shared token."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ctx import accounts, cli, config, db, frontmatter, ui
from ctx.accounts import AccountError


class AccountTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context" / "actors").mkdir(parents=True)
        actor = {"id": "actor-ada", "type": "actor", "title": "Ada",
                 "created": "2026-11-21", "updated": "2026-11-21",
                 "status": "active", "kind": "human"}
        (self.root / "context/actors/ada.md").write_text(
            frontmatter.dumps(actor, "# Ada\n"), encoding="utf-8")
        self.addCleanup(lambda: os.environ.pop(config.ENV_TOKEN, None))
        self.addCleanup(lambda: os.environ.pop(config.ENV_DEPLOYMENT, None))

    def test_password_is_hashed_and_not_listed(self) -> None:
        shown = accounts.add(self.root, "Ada", "actor-ada")
        text = (self.root / "private/accounts.json").read_text(encoding="utf-8")
        self.assertNotIn(shown, text)
        self.assertNotIn("password", text)
        listed = accounts.public_list(self.root)
        self.assertEqual(listed, [{"name": "ada", "actor": "actor-ada"}])
        self.assertIsNone(accounts.verify(self.root, "ada", "nope"))
        self.assertEqual(accounts.verify(self.root, "ada", shown)["actor"], "actor-ada")

    def test_missing_actor_is_refused(self) -> None:
        with self.assertRaises(AccountError):
            accounts.add(self.root, "ada", "actor-missing", password="long-enough-secret")

    def test_account_starts_multi_without_a_shared_token(self) -> None:
        accounts.add(self.root, "ada", "actor-ada", password="long-enough-secret")
        os.environ.pop(config.ENV_TOKEN, None)
        live = config.effective(self.root, deploy=True)
        self.assertEqual(live["deployment"], "multi")
        self.assertEqual(live["access_token"], "")
        httpd = ui.make_server(self.root, "127.0.0.1", 0, deploy=True)
        httpd.server_close()

    def test_signed_in_write_stamps_that_actor(self) -> None:
        password = accounts.add(self.root, "ada", "actor-ada", password="long-enough-secret")
        (self.root / "context/projects").mkdir()
        (self.root / "context/tasks").mkdir()
        project = {"id": "project-demo", "type": "project", "title": "Demo",
                   "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
        (self.root / "context/projects/demo.md").write_text(
            frontmatter.dumps(project, "# Demo\n"), encoding="utf-8")
        db.init_db(self.root)
        cli.cmd_task_add(self.root, "Write it", "demo")
        httpd = ui.make_server(self.root, "127.0.0.1", 0, deploy=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def _stop() -> None:
            httpd.shutdown()
            thread.join(timeout=2)
            httpd.server_close()

        self.addCleanup(_stop)
        host, port = httpd.server_address[:2]
        status, body, headers = _request(port, "POST", "/api/session", {
            "name": "ada", "password": "wrong",
        })
        self.assertEqual(status, 401)
        status, body, headers = _request(port, "POST", "/api/session", {
            "name": "ada", "password": password,
        })
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        self.assertIn("stead_session=", cookie)
        self.assertNotIn(password, cookie)
        status, page, _headers = _request(port, "GET", "/", cookie=cookie.split(";")[0])
        self.assertEqual(status, 200)
        token = page.split('name="ctx-token" content="', 1)[1].split('"', 1)[0]
        status, body, _headers = _request(
            port, "POST", "/api/task/status",
            {"id": "task-write-it", "status": "doing"},
            cookie=cookie.split(";")[0], token=token)
        self.assertEqual(status, 200, body)
        _path, meta, _body = __import__("ctx").objects.find(self.root, "task", "task-write-it")
        self.assertEqual(meta["actor"], "actor-ada")
        self.assertEqual(meta["status"], "doing")


def _request(port: int, method: str, path: str, payload: dict | None = None,
             cookie: str = "", token: str = "") -> tuple[int, str | dict, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    if token:
        req.add_header("X-Ctx-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            headers = dict(resp.headers)
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        headers = dict(exc.headers)
        status = exc.status
    text = raw.decode("utf-8")
    if text.startswith("{") or text.startswith("["):
        try:
            return status, json.loads(text), headers
        except json.JSONDecodeError:
            pass
    return status, text, headers

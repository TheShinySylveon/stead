"""Regression tests for security, containment, correctness, and tightened behaviors."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx import (
    agent,
    autonomy,
    comment,
    config,
    db,
    doctor,
    frontmatter,
    merge,
    metrics,
    models,
    onboard,
    review,
    safety,
    schedule,
    slop,
    spec,
    ui,
    wiki,
    wiki_store,
)


class AuditFixesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("projects", "tasks", "documents", "meetings",
                       "repos", "contributions", "actors"):
            (self.root / "context" / folder).mkdir(parents=True)
        (self.root / "inbox").mkdir()

    # --- frontmatter ---------------------------------------------------------

    def test_frontmatter_blocks_newline_injection_and_preserves_quotes_and_commas(self) -> None:
        meta = {
            "id": "repo-a",
            "type": "repo",
            "title": 'FIX: "quoted"',
            "notes": "safe\nchecks: evil\u2028reach: merge\u2029---",
            "tags": ["a,b", "owner's", "feature-spec"],
        }
        dumped = frontmatter.dumps(meta, "# Body\n")
        parsed, body = frontmatter.parse(dumped)
        self.assertNotIn("checks", parsed)
        self.assertNotIn("reach", parsed)
        self.assertEqual(parsed["title"], 'FIX: "quoted"')
        self.assertEqual(parsed["tags"], ["a,b", "owner's", "feature-spec"])
        self.assertEqual(body.strip(), "# Body")

    # --- safety --------------------------------------------------------------

    def test_safety_catches_root_secrets_root_tests_and_trailing_dots(self) -> None:
        for name in ("credentials.json", ".npmrc", ".pypirc", "id_rsa.", "sub/.env."):
            self.assertIsNotNone(safety.secret_by(name), name)
        self.assertTrue(safety.is_test_path("test_root.py"))
        self.assertTrue(safety.test_addition_allowed("test_root.py", {}))
        self.assertIsNotNone(safety.protected_by(".gitlab-ci.yml.", {}))
        self.assertFalse(safety.test_addition_allowed("tests/conftest.py.", {}))

    # --- shared-server UI locks ----------------------------------------------

    def test_shared_server_locks_all_execution_and_model_routes(self) -> None:
        token = ui._SERVER_DEPLOYMENT.set("multi")
        self.addCleanup(lambda: ui._SERVER_DEPLOYMENT.reset(token))
        self.assertTrue(ui.shared_server(self.root))

        for path, payload in [
            ("/api/model/add", {"profile": "evil", "provider": "custom", "name": "m",
                                "base_url": "https://evil.example/v1", "api_key_env": "GH_TOKEN"}),
            ("/api/model/remove", {"profile": "evil"}),
            ("/api/model/role", {"role": "build", "profile": "evil"}),
            ("/api/settings", {"deployment": "single"}),
            ("/api/welcome", {"title": "Hijack"}),
            ("/api/onboard", {"title": "Hijack"}),
            ("/api/schedule", {"install": True, "interval": "hourly", "watch": True}),
            ("/api/contribution/body", {"id": "contribution-x", "body": "## Acceptance criteria"}),
            ("/api/build/lock/remove", {"contribution": "contribution-x", "force": True}),
            ("/api/factory/stop", {}),
            ("/api/factory/start", {}),
            ("/api/improve/accept", {"name": "x.md"}),
            ("/api/prompt/promote", {"factory": "feature-builder", "version": "v2"}),
        ]:
            status, body, _ct = ui.dispatch(self.root, "POST", path, {}, payload, token_ok=True)
            self.assertEqual(status, 400, f"{path} should be refused on shared server: {body}")

    def test_shared_server_locks_extra_repo_fields(self) -> None:
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "oss",
            }, "# App\n"),
            encoding="utf-8",
        )
        token = ui._SERVER_DEPLOYMENT.set("multi")
        self.addCleanup(lambda: ui._SERVER_DEPLOYMENT.reset(token))
        for field, val in [("auto_publish", "true"), ("require_tests", "false"),
                           ("slop_gate", "false"), ("kind", "own")]:
            status, body, _ct = ui.dispatch(
                self.root, "POST", "/api/repo", {}, {"id": "repo-app", field: val}, token_ok=True)
            self.assertEqual(status, 400, f"{field} should be read-only: {body}")

    def test_comment_eligible_respects_false_string(self) -> None:
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "allow_comment": "false",
            }, "# App\n"),
            encoding="utf-8",
        )
        self.assertFalse(ui._comment_eligible(self.root, {"repo": "repo-app", "number": 1}))

    # --- agent & spec --------------------------------------------------------

    def test_safe_rel_rejects_trailing_dot_and_space(self) -> None:
        with self.assertRaises(agent.BuildError):
            agent._safe_rel("tests/conftest.py.")
        with self.assertRaises(agent.BuildError):
            agent._safe_rel("foo /bar.py")

    def test_draft_read_hides_secrets_and_slices_large_files(self) -> None:
        code = self.root / "code"
        code.mkdir()
        (code / "credentials.json").write_text('{"secret":"shh"}', encoding="utf-8")
        big = "\n".join(f"line {i}: " + ("x" * 100) for i in range(1, 300))
        (code / "big.py").write_text(big, encoding="utf-8")
        self.assertIn("refused", spec._draft_read(code, "credentials.json"))
        ranged = spec._draft_read(code, "big.py", start=1, end=5)
        self.assertIn("lines 1-5", ranged)
        self.assertIn("line 1:", ranged)
        # Search skips credentials.json and formats query properly.
        s = spec._draft_search(code, "shh")
        self.assertIn("no matches", s)
        s2 = spec._draft_search(code, "line 1:")
        self.assertTrue(s2.startswith("search 'line 1:':"))

    def test_plan_citation_warnings_rejects_traversal(self) -> None:
        code = self.root / "code"
        code.mkdir()
        (self.root / "outside.py").write_text("SECRET = 1\n", encoding="utf-8")
        plan = "## Data source\n- `SECRET = 1` (`../outside.py:1`)\n"
        warnings = spec.plan_citation_warnings(plan, code)
        self.assertTrue(any("not in the repo" in w for w in warnings), warnings)

    def test_draft_with_research_preserves_issue_context_on_later_turns(self) -> None:
        code = self.root / "code"
        code.mkdir()
        (code / "app.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        seen_prompts: list[str] = []

        def responder(prompt: str) -> str:
            seen_prompts.append(prompt)
            if len(seen_prompts) == 1:
                return json.dumps({"action": "read", "path": "app.py"})
            return json.dumps({
                "action": "finish",
                "spec": "Desc.\n\n## Acceptance criteria\n- [ ] works\n\n## Plan\n1. edit\n",
            })

        spec._draft_with_research(code, "app.py", "", "My Unique Issue", "Issue details", responder)
        self.assertEqual(len(seen_prompts), 2)
        self.assertIn("My Unique Issue", seen_prompts[1])
        self.assertIn("Issue details", seen_prompts[1])
        self.assertIn("def hello", seen_prompts[1])

    # --- db.init_db preservation & --reset -----------------------------------

    def test_init_db_preserves_runs_and_prompts_unless_reset(self) -> None:
        fdir = self.root / "factories" / "demo" / "prompts"
        fdir.mkdir(parents=True)
        (fdir / "v1.md").write_text("v1", encoding="utf-8")
        (fdir / "v2.md").write_text("v2", encoding="utf-8")
        db.init_db(self.root)
        conn = db.connect(self.root)
        try:
            conn.execute(
                "INSERT INTO runs (factory, task_ref, prompt_version, mode, verdict, created) "
                "VALUES ('demo', 't1', 'v2', 'shadow', 'approved', '2026-11-27T00:00:00Z')"
            )
            conn.execute("UPDATE prompt_versions SET status = 'retired' WHERE version = 'v2'")
            conn.execute("UPDATE prompt_versions SET status = 'production' WHERE version = 'v1'")
            conn.commit()
        finally:
            conn.close()

        # Default rebuild preserves runs and prompt promotion state.
        db.init_db(self.root)
        conn = db.connect(self.root)
        try:
            runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            prod = conn.execute(
                "SELECT version FROM prompt_versions WHERE factory = 'demo' AND status = 'production'"
            ).fetchone()["version"]
            self.assertEqual(runs, 1)
            self.assertEqual(prod, "v1")
        finally:
            conn.close()

        # Explicit reset drops runs and restores highest version as production.
        db.init_db(self.root, reset=True)
        conn = db.connect(self.root)
        try:
            runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            prod = conn.execute(
                "SELECT version FROM prompt_versions WHERE factory = 'demo' AND status = 'production'"
            ).fetchone()["version"]
            self.assertEqual(runs, 0)
            self.assertEqual(prod, "v2")
        finally:
            conn.close()

    # --- autonomy, config, wiki, doctor, comment, slop, metrics, onboard -----

    def test_autonomy_forbids_immutable_extra_fields(self) -> None:
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own",
            }, "# App\n"),
            encoding="utf-8",
        )
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_repo(self.root, "repo-app", extra={"id": "hacked"})
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_repo(self.root, "repo-app", extra={"reach": "bogus"})

    def test_config_save_preserves_actor_string(self) -> None:
        config.save_actor(self.root, "actor-ada")
        config.choose(self.root, "multi")
        self.assertEqual(config.read_raw(self.root).get("actor"), "actor-ada")

    def test_wiki_child_reordering_persists(self) -> None:
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own",
            }, "# App\n"),
            encoding="utf-8",
        )
        for num, slug in [(1, "a"), (2, "b")]:
            (self.root / f"context/contributions/app-issue-{num}.md").write_text(
                frontmatter.dumps({
                    "id": f"contribution-app-issue-{num}", "type": "contribution",
                    "title": f"Spec {slug}", "created": "2026-11-21",
                    "updated": "2026-11-21", "repo": "repo-app", "kind": "issue",
                    "number": num, "state": "open", "visibility": "public",
                }, "# Spec\n"),
                encoding="utf-8",
            )
        sibs = wiki.siblings(self.root, "repo-app", "specs/contribution-app-issue-2")
        wiki_store.move(self.root, "repo-app", sibs, "specs/contribution-app-issue-2", "up")
        sibs_after = wiki.siblings(self.root, "repo-app", "specs/contribution-app-issue-2")
        self.assertEqual(sibs_after[0], "specs/contribution-app-issue-2")

    def test_doctor_aligns_with_schema(self) -> None:
        (self.root / "context/projects/p.md").write_text(
            frontmatter.dumps({
                "id": "project-p", "type": "project", "title": "P",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "done",
            }, "# P\n"),
            encoding="utf-8",
        )
        (self.root / "context/documents/digest.md").write_text(
            frontmatter.dumps({
                "id": "document-digest", "type": "document", "title": "Digest",
                "created": "2026-11-21", "updated": "2026-11-21",
            }, "# Digest\n"),
            encoding="utf-8",
        )
        (self.root / "context/repos/r.md").write_text(
            frontmatter.dumps({
                "id": "repo-r", "type": "repo", "title": "R",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "active",
            }, "# R\n"),
            encoding="utf-8",
        )
        (self.root / "context/contributions/c.md").write_text(
            frontmatter.dumps({
                "id": "contribution-c", "type": "contribution", "title": "C",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-r", "kind": "issue", "number": 1, "state": "bogus",
            }, "# C\n"),
            encoding="utf-8",
        )
        report = doctor.run(self.root)
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("unusual state 'bogus'" in w["message"] for w in report["warnings"]))
        self.assertFalse(any("unusual status 'done'" in w["message"] for w in report["warnings"]))

    def test_comment_url_and_slurp_pagination(self) -> None:
        self.assertTrue(comment._pr_in_repo("https://github.com/Owner/Repo/pull/5", "owner/repo"))
        self.assertFalse(comment._pr_in_repo("https://evil.com/github.com/owner/repo/pull/5", "owner/repo"))
        paged = json.dumps([
            [{"id": 1, "body": "hello", "user": {"login": "alice"}}],
            [{"id": 2, "body": f"{comment.COMMENT_MARKER}\nhi", "user": {"login": "alice"}}],
        ])
        cid = comment._find_marked_comment(lambda argv, cwd: paged, "o/r", 1, self.root, "alice")
        self.assertEqual(cid, 2)

    def test_slop_does_not_false_positive_across_blank_lines_or_markdown(self) -> None:
        py_text = "# a = 1\n\n# b = 2\n\n# c = 3\n# TODO: one\n"
        self.assertEqual(slop.hard_flags("app.py", py_text), [])
        self.assertEqual(slop.slop_flags("app.py", py_text), [])
        md_text = "# Title = 1\n# Two = 2\n# Three = 3\n"
        self.assertEqual(slop.hard_flags("README.md", md_text), [])

    def test_metrics_filters_reviews_by_repo_and_since(self) -> None:
        for idx, (repo_tag, day) in enumerate([("repo-a", "2026-11-01"), ("repo-b", "2026-11-20")], 1):
            (self.root / f"context/documents/rev-{idx}.md").write_text(
                frontmatter.dumps({
                    "id": f"document-rev-{idx}", "type": "document", "title": f"Rev {idx}",
                    "created": day, "updated": day,
                    "tags": ["review-record", f"repo:{repo_tag}"], "verdict": "approve",
                }, "# Rev\n"),
                encoding="utf-8",
            )
        rep = metrics.collect(self.root, repo="repo-b", since="2026-11-10")
        self.assertEqual(rep["reviews"]["approve"], 1)

    def test_onboard_saves_code_path_on_repo(self) -> None:
        db.init_db(self.root)
        code_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(code_tmp.cleanup)
        code = Path(code_tmp.name)
        res = onboard.onboard(self.root, "My App", code_path=str(code), run_specify_init=False)
        found = __import__("ctx").objects.find(self.root, "repo", res["repo"])
        self.assertIsNotNone(found)
        self.assertEqual(found[1].get("code_path"), str(code.resolve()))

    def test_schedule_rejects_leading_hyphen_and_uses_posix_cron(self) -> None:
        with self.assertRaises(schedule.ScheduleError):
            schedule.weekly_command(self.root, project="--evil")
        shown = schedule.show(self.root)
        cron_part = shown.split("cron:\n", 1)[1]
        self.assertNotIn("cd /d", cron_part)

    def test_models_scrubs_key_validates_usage_and_blocks_eval_traversal(self) -> None:
        self.assertEqual(models._scrub("bad key sk-secret-123 here", "sk-secret-123"),
                         "bad key [redacted] here")
        usage: dict = {}
        models._add_usage(usage, {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}, "abcd", "efgh")
        self.assertTrue(usage.get("estimated"))
        usage2: dict = {}
        models._add_usage(usage2, {"usage": {"prompt_tokens": math.nan, "completion_tokens": 5}}, "abcd", "efgh")
        self.assertTrue(usage2.get("estimated"))
        res = models.check_eval_files(self.root, "../outside")
        self.assertFalse(res["ok"])

    def test_review_parse_fails_closed_on_ambiguous_verdict(self) -> None:
        verdict, _reason = review._parse("verdict: approve\nactually wait\nverdict: reject\nreason: missing test")
        self.assertEqual(verdict, "reject")

    def test_improvement_proposals_work_end_to_end(self) -> None:
        from ctx import writeback
        for field in ("improvement_type", "rationale", "change"):
            self.assertIn(field, agent._ACTION_FIELDS)
            self.assertIn(field, agent._ACTION_RESPONSE_FORMAT["json_schema"]["schema"]["properties"])
        # Multi-heading prompt change is not truncated at ## headings.
        body = "# Fix\n\n## Rationale\n\nBecause.\n\n## Change\n\nIntro\n\n## Rules\n\nKeep tests.\n"
        self.assertIn("## Rules", writeback._improvement_section(body, "change"))
        # Code improvement sourced from a contribution resolves repo -> project without state.db.
        (self.root / "context/projects/p.md").write_text(
            frontmatter.dumps({
                "id": "project-p", "type": "project", "title": "P",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "active",
            }, "# P\n"),
            encoding="utf-8",
        )
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "project": "project-p",
            }, "# App\n"),
            encoding="utf-8",
        )
        (self.root / "context/contributions/app-issue-1.md").write_text(
            frontmatter.dumps({
                "id": "contribution-app-issue-1", "type": "contribution", "title": "Spec",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-app", "kind": "issue", "number": 1, "state": "open",
            }, "# Spec\n"),
            encoding="utf-8",
        )
        prop = writeback.propose_improvement(
            self.root, "code", "Add guard", "Missing check", "Check input",
            source="contribution-app-issue-1")
        accepted = writeback.accept_improvement(self.root, Path(prop["path"]).name)
        self.assertTrue((self.root / accepted["path"]).is_file())

    def test_writeback_lookup_handles_slug_and_ignores_failed_retry(self) -> None:
        from ctx import writeback
        (self.root / "context/contributions/app-issue-9.md").write_text(
            frontmatter.dumps({
                "id": "contribution-app-issue-9", "type": "contribution", "title": "S",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-app", "kind": "issue", "number": 9, "state": "open",
            }, "# S\n"),
            encoding="utf-8",
        )
        (self.root / "context/documents/build-app-9-20261121T100000Z.md").write_text(
            frontmatter.dumps({
                "id": "document-build-app-9-20261121t100000z", "type": "document",
                "title": "Delivered", "created": "2026-11-21", "updated": "2026-11-21",
                "tags": ["build-record"], "contribution": "contribution-app-issue-9",
                "outcome": "published", "pr_url": "https://github.com/o/r/pull/99",
            }, "# Delivered\n"),
            encoding="utf-8",
        )
        (self.root / "context/documents/build-app-9-20261121T120000Z.md").write_text(
            frontmatter.dumps({
                "id": "document-build-app-9-20261121t120000z", "type": "document",
                "title": "Failed retry", "created": "2026-11-21", "updated": "2026-11-21",
                "tags": ["build-record"], "contribution": "contribution-app-issue-9",
                "outcome": "failed",
            }, "# Failed\n"),
            encoding="utf-8",
        )
        # Lookup via slug finds the delivered record's PR URL, not the failed retry.
        self.assertEqual(writeback.contribution_pr_url(self.root, "app-issue-9"),
                         "https://github.com/o/r/pull/99")

    def test_actors_canonicalize_slug_and_tasks_preserve_context(self) -> None:
        from ctx import actors, tasks
        (self.root / "context/actors/ada.md").write_text(
            frontmatter.dumps({
                "id": "actor-ada", "type": "actor", "title": "Ada",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "active",
            }, "# Ada\n"),
            encoding="utf-8",
        )
        self.assertEqual(actors.use(self.root, "ada"), "actor-ada")
        runner = tasks.TaskRunner()
        tok = actors.bind("actor-ada")
        try:
            tid = runner.start("test", "t1", lambda _p: {"actor": actors.current(self.root)})
        finally:
            actors.unbind(tok)
        import time as _time
        for _ in range(50):
            snap = runner.get(tid)
            if snap and snap["status"] != "running":
                break
            _time.sleep(0.02)
        self.assertEqual(snap["result"]["actor"], "actor-ada")

    def test_inbox_import_wraps_ui_error_as_inbox_import_error(self) -> None:
        from ctx import inbox_import
        huge = ("x" * 25_000).encode("utf-8")
        with self.assertRaises(inbox_import.InboxImportError):
            inbox_import.import_bytes(self.root, "note.txt", huge)

    def test_ui_check_evals_and_cli_key_env_preservation(self) -> None:
        from ctx import cli
        res = ui.check_evals(self.root, "")
        self.assertTrue(res["ok"], res)
        self.assertIn("spec_gates", res)
        # CLI `model set` / `model add` preserve a custom --key-env when omitted.
        cli.main(["--root", str(self.root), "model", "set", "--provider", "openai",
                  "--name", "gpt-4o", "--key-env", "MY_CUSTOM_KEY"])
        cli.main(["--root", str(self.root), "model", "set", "--provider", "openai",
                  "--name", "gpt-4o-mini"])
        self.assertEqual(models.public_model(self.root)["key_env"], "MY_CUSTOM_KEY")
        cli.main(["--root", str(self.root), "model", "add", "fast", "--provider", "openai",
                  "--name", "gpt-4o", "--key-env", "FAST_KEY"])
        cli.main(["--root", str(self.root), "model", "add", "fast", "--provider", "openai",
                  "--name", "gpt-4o-mini"])
        self.assertEqual(models.profiles_view(self.root)["profiles"]["fast"]["key_env"], "FAST_KEY")


if __name__ == "__main__":
    unittest.main()

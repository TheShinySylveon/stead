"""Unit tests: repo/contribution CRUD, mocked gh sync (offline, deterministic),
--offline reindex, and weekly-contribution-digest assembly.

All tests run against a temporary root — never the real repo state. The gh
subprocess is fully mocked; no test touches the network.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx import cli, db, factory, frontmatter, objects, sync
from tests.test_ctx import make_root


def add_digest_factory(root: Path) -> Path:
    """Extend the minimal skeleton with the weekly-contribution-digest factory."""
    fdir = root / "factories" / "weekly-contribution-digest"
    (fdir / "prompts").mkdir(parents=True, exist_ok=True)
    (fdir / "evals").mkdir(parents=True, exist_ok=True)
    (fdir / "FACTORY.md").write_text("# FACTORY: weekly-contribution-digest\n", encoding="utf-8")
    (fdir / "prompts" / "v1.md").write_text(
        "Draft a weekly contribution digest from the bundle below.\n", encoding="utf-8")
    return root


class GithubTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = add_digest_factory(make_root(Path(self._tmp.name)))
        db.init_db(self.root)


# --- repo / contribution CRUD -------------------------------------------------

class TestRepoContributionCrud(GithubTestCase):
    def test_repo_add_list(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="own", default_branch="main")
        path = self.root / "context/repos/testuser-my-app.md"
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "repo-testuser-my-app")
        self.assertEqual(meta["kind"], "own")
        self.assertEqual(meta["default_branch"], "main")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT kind, url FROM repos").fetchone()
            self.assertEqual((row["kind"], row["url"]),
                             ("own", "https://github.com/testuser/my-app"))
        finally:
            conn.close()
        self.assertEqual(cli.cmd_repo_list(self.root), 0)
        self.assertEqual(cli.cmd_repo_list(self.root, kind="oss"), 0)

    def test_repo_add_rejects_bad_kind(self) -> None:
        with self.assertRaises(SystemExit):
            cli.cmd_repo_add(self.root, "Bad", kind="fork")

    def test_contribution_add_list_set(self) -> None:
        cli.cmd_repo_add(self.root, "Cool Lib", url="https://github.com/oss-org/cool-lib")
        cli.cmd_contribution_add(self.root, "Add feature", "repo-oss-org-cool-lib",
                                 "pr", 7, ci="pass", review="requested")
        path = self.root / "context/contributions/oss-org-cool-lib-pr-7.md"
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "contribution-oss-org-cool-lib-pr-7")
        self.assertEqual(meta["repo"], "repo-oss-org-cool-lib")
        self.assertEqual(meta["visibility"], "public")
        self.assertEqual(meta["url"], "https://github.com/oss-org/cool-lib/pull/7")
        self.assertEqual(meta["number"], "7")  # flat frontmatter: strings
        # set updates file AND index
        cli.cmd_contribution_set(self.root, "contribution-oss-org-cool-lib-pr-7",
                                 state="merged", ci="pass")
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["state"], "merged")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT state, ci, number FROM contributions").fetchone()
            self.assertEqual((row["state"], row["ci"], row["number"]), ("merged", "pass", 7))
        finally:
            conn.close()
        self.assertEqual(cli.cmd_contribution_list(self.root, kind="pr", state="merged"), 0)
        self.assertEqual(cli.cmd_contribution_list(self.root, role="reviewer"), 0)

    def test_contribution_validation(self) -> None:
        with self.assertRaises(SystemExit):  # unknown repo
            cli.cmd_contribution_add(self.root, "Orphan", "repo-nope", "pr", 1)
        cli.cmd_repo_add(self.root, "R", url="https://github.com/o/r")
        with self.assertRaises(SystemExit):  # bad kind
            cli.cmd_contribution_add(self.root, "Bad", "repo-o-r", "discussion", 1)
        cli.cmd_contribution_add(self.root, "Dup", "repo-o-r", "issue", 1)
        with self.assertRaises(SystemExit):  # duplicate natural key
            cli.cmd_contribution_add(self.root, "Dup", "repo-o-r", "issue", 1)
        with self.assertRaises(SystemExit):  # set with no fields
            cli.cmd_contribution_set(self.root, "contribution-o-r-issue-1")
        with self.assertRaises(SystemExit):  # set invalid value
            cli.cmd_contribution_set(self.root, "contribution-o-r-issue-1", state="wat")

    def test_init_reindexes_handwritten_files(self) -> None:
        rmeta = {"id": "repo-o-r", "type": "repo", "title": "o/r",
                 "created": "2026-11-21", "updated": "2026-11-21",
                 "status": "active", "kind": "oss", "url": "https://github.com/o/r"}
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        (self.root / "context/repos/o-r.md").write_text(
            frontmatter.dumps(rmeta, "# o/r\n"), encoding="utf-8")
        cmeta = {"id": "contribution-o-r-pr-5", "type": "contribution", "title": "T",
                 "created": "2026-11-21", "updated": "2026-11-21", "repo": "repo-o-r",
                 "kind": "pr", "number": "5", "role": "author", "state": "open",
                 "ci": "fail", "review": "changes", "visibility": "public"}
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        (self.root / "context/contributions/o-r-pr-5.md").write_text(
            frontmatter.dumps(cmeta, "# T\n"), encoding="utf-8")
        counts = db.init_db(self.root)  # rebuild from files alone
        self.assertEqual((counts["repos"], counts["contributions"]), (1, 1))
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT ci, review, number FROM contributions").fetchone()
            self.assertEqual((row["ci"], row["review"], row["number"]), ("fail", "changes", 5))
        finally:
            conn.close()

    def test_frontmatter_roundtrip_new_fields(self) -> None:
        meta = {"id": "contribution-x-pr-1", "type": "contribution",
                "title": "X: a title", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-x", "kind": "pr", "number": "1",
                "url": "https://github.com/x/y/pull/1", "role": "author",
                "state": "open", "ci": "pending", "review": "requested",
                "visibility": "public", "tags": ["example"]}
        parsed, _ = frontmatter.parse(frontmatter.dumps(meta, "# X\n"))
        self.assertEqual(parsed, meta)


# --- sync github (mocked gh subprocess) ----------------------------------------

def _gh_item(number, title, url, repo_full, state="open"):
    return {"number": number, "title": title, "url": url, "state": state,
            "repository": {"nameWithOwner": repo_full},
            "createdAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-20T00:00:00Z"}


FAKE_AUTHOR_PRS = [_gh_item(7, "Add feature", "https://github.com/testuser/my-app/pull/7",
                            "testuser/my-app")]
FAKE_REVIEW_PRS = [_gh_item(42, "Fix bug", "https://github.com/oss-org/cool-lib/pull/42",
                            "oss-org/cool-lib")]
FAKE_ISSUES = [_gh_item(9, "Improve docs", "https://github.com/oss-org/cool-lib/issues/9",
                        "oss-org/cool-lib")]
FAKE_LABELED_ISSUES = []
FAKE_ROLLUPS = {
    "https://github.com/testuser/my-app/pull/7": {
        "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
        "reviewDecision": "REVIEW_REQUIRED"},
    "https://github.com/oss-org/cool-lib/pull/42": {
        "statusCheckRollup": [{"status": "IN_PROGRESS", "conclusion": ""}],
        "reviewDecision": None},
}


def fake_gh_run(args, **kwargs):
    """Deterministic stand-in for subprocess.run(['gh', ...]) — read-only queries."""
    assert args[0] == "gh"
    rest = args[1:]
    stdout = ""
    if rest[:2] == ["api", "user"]:
        stdout = "testuser\n"
    elif rest[:2] == ["search", "prs"] and "--author" in rest:
        stdout = json.dumps(FAKE_AUTHOR_PRS)
    elif rest[:2] == ["search", "prs"] and "--review-requested" in rest:
        stdout = json.dumps(FAKE_REVIEW_PRS)
    elif rest[:2] == ["search", "issues"] and "--assignee" in rest:
        stdout = json.dumps(FAKE_ISSUES)
    elif rest[:2] == ["search", "issues"] and "--label" in rest:
        stdout = json.dumps(FAKE_LABELED_ISSUES)
    elif rest[:2] == ["pr", "view"]:
        stdout = json.dumps(FAKE_ROLLUPS.get(rest[2], {}))
    else:
        raise AssertionError(f"unexpected gh call (must be read-only): {args}")
    return mock.Mock(returncode=0, stdout=stdout, stderr="")


class TestSyncGithubMocked(GithubTestCase):
    def test_sync_writes_markdown_and_index(self) -> None:
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(sync.subprocess, "run", side_effect=fake_gh_run):
            result = sync.sync_github(self.root, author="@me", limit=10)
        self.assertEqual(result["fetched"], 3)
        self.assertEqual((result["new"], result["repos"], result["contributions"]), (3, 2, 3))
        # repo auto-created with own/oss split based on the gh login
        own, _ = frontmatter.parse(
            (self.root / "context/repos/testuser-my-app.md").read_text(encoding="utf-8"))
        oss, _ = frontmatter.parse(
            (self.root / "context/repos/oss-org-cool-lib.md").read_text(encoding="utf-8"))
        self.assertEqual((own["kind"], oss["kind"]), ("own", "oss"))
        # contribution files: flat frontmatter, public, CI/review enriched
        pr7, _ = frontmatter.parse(
            (self.root / "context/contributions/testuser-my-app-pr-7.md").read_text(encoding="utf-8"))
        self.assertEqual(pr7["role"], "author")
        self.assertEqual(pr7["ci"], "pass")
        self.assertEqual(pr7["review"], "requested")
        self.assertEqual(pr7["visibility"], "public")
        pr42, _ = frontmatter.parse(
            (self.root / "context/contributions/oss-org-cool-lib-pr-42.md").read_text(encoding="utf-8"))
        self.assertEqual((pr42["role"], pr42["ci"], pr42["review"]),
                         ("reviewer", "pending", "requested"))
        issue9, _ = frontmatter.parse(
            (self.root / "context/contributions/oss-org-cool-lib-issue-9.md").read_text(encoding="utf-8"))
        self.assertEqual((issue9["kind"], issue9["role"], issue9["ci"]), ("issue", "assignee", "none"))
        conn = db.connect(self.root)
        try:
            n = conn.execute("SELECT COUNT(*) c FROM contributions").fetchone()["c"]
            self.assertEqual(n, 3)
        finally:
            conn.close()

    def test_sync_idempotent_and_preserves_user_edits(self) -> None:
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(sync.subprocess, "run", side_effect=fake_gh_run):
            sync.sync_github(self.root)
            path = self.root / "context/contributions/testuser-my-app-pr-7.md"
            meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
            meta["tags"] = ["example"]
            path.write_text(frontmatter.dumps(meta, body + "\nMy private-ish note on public data.\n"),
                            encoding="utf-8")
            created = meta["created"]
            result = sync.sync_github(self.root)
        self.assertEqual((result["new"], result["updated"], result["contributions"]), (0, 3, 3))
        meta2, body2 = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta2["created"], created)
        self.assertEqual(meta2["tags"], ["example"])
        self.assertIn("My private-ish note", body2)
        files = list((self.root / "context/contributions").glob("*.md"))
        self.assertEqual(len(files), 3)  # no duplicates

    def test_sync_offline_never_calls_subprocess(self) -> None:
        cli.cmd_repo_add(self.root, "R", url="https://github.com/o/r")
        cli.cmd_contribution_add(self.root, "T", "repo-o-r", "pr", 5)
        with mock.patch.object(sync.subprocess, "run",
                               side_effect=AssertionError("network used in --offline")):
            result = sync.sync_github(self.root, offline=True)
        self.assertTrue(result["offline"])
        self.assertEqual((result["repos"], result["contributions"]), (1, 1))
        self.assertEqual(cli.cmd_sync_github(self.root, offline=True), 0)

    def test_sync_records_the_stead_build_label(self) -> None:
        # A repo you own; the label query must be scoped to it.
        cli.cmd_repo_add(self.root, "Cool Lib", url="https://github.com/oss-org/cool-lib",
                         kind="own")
        labeled = [_gh_item(11, "Add export", "https://github.com/oss-org/cool-lib/issues/11",
                            "oss-org/cool-lib")]

        def run(args, **kwargs):
            assert args[0] == "gh"
            if args[1:3] == ["api", "user"]:
                return mock.Mock(returncode=0, stdout="oss-org\n", stderr="")
            if args[1:3] == ["search", "issues"] and "--label" in args:
                self.assertIn("--repo", args)
                self.assertIn("oss-org/cool-lib", args)
                return mock.Mock(returncode=0, stdout=json.dumps(labeled), stderr="")
            if args[1:3] == ["issue", "view"]:
                return mock.Mock(returncode=0, stdout="The real issue body.\n", stderr="")
            if args[1:3] == ["search", "prs"]:
                return mock.Mock(returncode=0, stdout=json.dumps([]), stderr="")
            if args[1:3] == ["search", "issues"]:
                return mock.Mock(returncode=0, stdout=json.dumps([]), stderr="")
            if args[1:3] == ["pr", "view"]:
                return mock.Mock(returncode=0, stdout="{}", stderr="")
            raise AssertionError(args)

        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(sync.subprocess, "run", side_effect=run):
            sync.sync_github(self.root)
        meta, body = frontmatter.parse(
            (self.root / "context/contributions/oss-org-cool-lib-issue-11.md").read_text(encoding="utf-8"))
        self.assertIn("stead-build", meta["tags"])
        self.assertEqual(meta["kind"], "issue")
        self.assertEqual(body.strip(), "The real issue body.")
        self.assertIn("body_sha", meta)
        self.assertIn("upstream_body_sha", meta)
        self.assertEqual(meta["body_sha"], meta["upstream_body_sha"])

    def test_sync_gh_missing_message(self) -> None:
        with mock.patch.object(sync.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                sync.sync_github(self.root)
        self.assertIn("--offline", str(ctx.exception))

    def test_sync_not_authenticated_message(self) -> None:
        def unauth(args, **kwargs):
            return mock.Mock(returncode=1, stdout="", stderr="Try gh auth login")
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"), \
             mock.patch.object(sync.subprocess, "run", side_effect=unauth):
            with self.assertRaises(SystemExit) as ctx:
                sync.sync_github(self.root)
        self.assertIn("gh auth login", str(ctx.exception))

    def test_ci_rollup_mapping(self) -> None:
        self.assertEqual(sync._ci_from_rollup([]), "none")
        self.assertEqual(sync._ci_from_rollup(
            [{"status": "COMPLETED", "conclusion": "SUCCESS"}]), "pass")
        self.assertEqual(sync._ci_from_rollup(
            [{"status": "COMPLETED", "conclusion": "FAILURE"}]), "fail")
        self.assertEqual(sync._ci_from_rollup(
            [{"status": "COMPLETED", "conclusion": "SUCCESS"},
             {"status": "IN_PROGRESS", "conclusion": ""}]), "pending")
        self.assertEqual(sync._ci_from_rollup(
            [{"status": "COMPLETED", "conclusion": "SUCCESS"},
             {"status": "COMPLETED", "conclusion": "TIMED_OUT"}]), "fail")
        self.assertEqual(sync._ci_from_rollup([{"state": "PENDING"}]), "pending")


# --- digest assembly ------------------------------------------------------------

class TestDigestAssembly(GithubTestCase):
    def _seed(self) -> None:
        cli.cmd_repo_add(self.root, "EXAMPLE example-org/example-repo",
                         url="https://github.com/example-org/example-repo", kind="oss")
        cli.cmd_contribution_add(self.root, "EXAMPLE: Add caching", "repo-example-org-example-repo",
                                 "pr", 101, role="author", ci="pass", review="requested")
        cli.cmd_contribution_add(self.root, "EXAMPLE: Fix pagination", "repo-example-org-example-repo",
                                 "pr", 102, role="reviewer", ci="pending", review="requested")
        cli.cmd_contribution_add(self.root, "EXAMPLE: Docs", "repo-example-org-example-repo",
                                 "issue", 103, role="assignee")

    def test_digest_does_not_include_private_notes(self) -> None:
        self._seed()
        (self.root / "context/documents").mkdir(parents=True, exist_ok=True)
        private = {"id": "document-private-plan", "type": "document",
                   "title": "Private plan", "created": "2026-11-21",
                   "updated": "2026-11-21", "project": "project-example"}
        (self.root / "context/documents/private-plan.md").write_text(
            frontmatter.dumps(private,
                              "# Private plan\n\nSECRET-STRATEGY-MARKER\n"),
            encoding="utf-8")
        info = factory.assemble_digest(self.root)
        run_dir = self.root / info["run_dir"]
        text = ((run_dir / "bundle.md").read_text(encoding="utf-8")
                + (run_dir / "prompt.md").read_text(encoding="utf-8"))
        self.assertNotIn("SECRET-STRATEGY-MARKER", text)
        self.assertNotIn("Private plan", text)

    def test_digest_bundle_artifacts_and_ledger(self) -> None:
        self._seed()
        info = factory.assemble_digest(self.root)
        self.assertEqual(info["factory"], "weekly-contribution-digest")
        self.assertEqual(info["mode"], "shadow")
        self.assertEqual(info["counts"], {"contributions": 3, "repos": 1,
                                          "prs_in_flight": 1, "reviews_awaiting": 1,
                                          "claimed_issues": 1, "ci_flags": 1})
        run_dir = self.root / info["run_dir"]
        for name in ("bundle.md", "prompt.md", "run.json"):
            self.assertTrue((run_dir / name).exists(), name)
        bundle = (run_dir / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("## Repo: EXAMPLE example-org/example-repo", bundle)
        self.assertIn("[kind: oss]", bundle)
        self.assertIn("[pr #101]", bundle)
        self.assertIn("[issue #103]", bundle)
        # deterministic order: kind then number (issue sorts before pr)
        self.assertLess(bundle.find("[issue #103]"), bundle.find("[pr #101]"))
        self.assertLess(bundle.find("[pr #101]"), bundle.find("[pr #102]"))
        prompt = (run_dir / "prompt.md").read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith("Draft a weekly contribution digest"))
        self.assertIn("Contribution digest bundle", prompt)
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT factory, task_ref, project, mode, verdict "
                               "FROM runs").fetchone()
            self.assertEqual((row["factory"], row["task_ref"], row["project"],
                              row["mode"], row["verdict"]),
                             ("weekly-contribution-digest", "contributions", None,
                              "shadow", "pending"))
        finally:
            conn.close()

    def test_digest_via_cli_paths(self) -> None:
        self._seed()
        self.assertEqual(cli.cmd_factory_run(self.root, "weekly-contribution-digest", None), 0)
        self.assertEqual(cli.cmd_digest(self.root), 0)
        conn = db.connect(self.root)
        try:
            n = conn.execute("SELECT COUNT(*) c FROM runs "
                             "WHERE factory='weekly-contribution-digest'").fetchone()["c"]
            self.assertEqual(n, 2)
        finally:
            conn.close()

    def test_digest_empty_cache(self) -> None:
        info = factory.assemble_digest(self.root)
        self.assertEqual(info["counts"]["contributions"], 0)
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("No contributions cached", bundle)

    def test_digest_requires_production_prompt(self) -> None:
        conn = db.connect(self.root)
        try:
            conn.execute("DELETE FROM prompt_versions "
                         "WHERE factory='weekly-contribution-digest'")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SystemExit):
            factory.assemble_digest(self.root)


class TestSyncRepoScope(GithubTestCase):
    """`sync github --repo OWNER/NAME` and a saved scope keep other repos out
    of the store (a dogfood store holds one project, not every PR you have)."""

    def _sync(self, **kwargs):
        calls: list[list[str]] = []

        def run(args, **kw):
            calls.append(list(args))
            return fake_gh_run(args, **kw)

        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"),              mock.patch.object(sync.subprocess, "run", side_effect=run):
            result = sync.sync_github(self.root, **kwargs)
        return result, calls

    def _repo_files(self) -> list[str]:
        return sorted(p.name for p in (self.root / "context/repos").glob("*.md"))

    def test_repo_scope_filters_every_search_and_its_results(self) -> None:
        result, calls = self._sync(repos=["testuser/my-app"])
        searches = [c for c in calls if c[1:2] == ["search"]]
        self.assertTrue(searches)
        for call in searches:
            self.assertIn("--repo", call)
            self.assertIn("testuser/my-app", call)
        # gh returned an out-of-scope PR and issue anyway; neither is written.
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["repos_scope"], ["testuser/my-app"])
        self.assertEqual(self._repo_files(), ["testuser-my-app.md"])

    def test_a_saved_scope_applies_to_a_plain_sync(self) -> None:
        from ctx import config
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"),              mock.patch.object(sync.subprocess, "run", side_effect=fake_gh_run):
            self.assertEqual(cli.cmd_sync_github(self.root, repos=["testuser/my-app"],
                                                 remember=True), 0)
        self.assertEqual(config.sync_repos(self.root), ["testuser/my-app"])
        for path in (self.root / "context/contributions").glob("*.md"):
            path.unlink()
        result, _calls = self._sync()
        self.assertEqual(result["fetched"], 1)
        # --all-repos ignores the saved scope for one run without clearing it.
        result, _calls = self._sync(repos=[])
        self.assertEqual(result["fetched"], 3)
        self.assertEqual(config.sync_repos(self.root), ["testuser/my-app"])

    def test_remember_with_all_repos_clears_the_scope(self) -> None:
        from ctx import config
        config.save_sync_repos(self.root, ["testuser/my-app"])
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/gh"),              mock.patch.object(sync.subprocess, "run", side_effect=fake_gh_run):
            cli.cmd_sync_github(self.root, all_repos=True, remember=True)
        self.assertEqual(config.sync_repos(self.root), [])
        with self.assertRaises(SystemExit):
            cli.cmd_sync_github(self.root, remember=True)

    def test_label_intake_skips_owned_repos_outside_the_scope(self) -> None:
        cli.cmd_repo_add(self.root, "Cool Lib", url="https://github.com/oss-org/cool-lib",
                         kind="own")
        _result, calls = self._sync(repos=["testuser/my-app"])
        labeled = [c for c in calls if "--label" in c]
        self.assertEqual(labeled, [])

    def test_bad_repo_names_are_refused_and_urls_accepted(self) -> None:
        from ctx import config
        with self.assertRaises(SystemExit):
            cli.cmd_sync_github(self.root, repos=["not a repo"])
        self.assertEqual(config.check_repos(["https://github.com/Me/App/", "me/app"]),
                         ["Me/App"])

    def test_saving_other_settings_keeps_the_scope(self) -> None:
        from ctx import config
        config.save_sync_repos(self.root, ["testuser/my-app"])
        config.save(self.root, {"deployment": "single"})
        self.assertEqual(config.sync_repos(self.root), ["testuser/my-app"])


if __name__ == "__main__":
    unittest.main()

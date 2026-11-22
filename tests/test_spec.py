"""Spec approval is bound to the body hash, not to a tag."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import agent, db, frontmatter, spec


class SpecApprovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context/contributions").mkdir(parents=True)
        self.body = ("The greeting script should accept a name option so callers can "
                     "address a person without editing the source. Keep the default "
                     "output stable and cover the new path with a small test.\n\n"
                     "## Acceptance criteria\n\n- [ ] flag works\n")
        self.meta = {"id": "contribution-me-app-issue-1", "type": "contribution",
                     "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                     "repo": "repo-me-app", "kind": "issue", "number": 1,
                     "role": "author", "state": "open", "visibility": "public",
                     "tags": ["feature-spec"]}
        self.path = self.root / "context/contributions/issue-1.md"
        self.path.write_text(frontmatter.dumps(self.meta, self.body), encoding="utf-8")
        db.init_db(self.root)

    def test_approve_stores_a_hash_and_build_accepts_it(self) -> None:
        result = spec.approve(self.root, "contribution-me-app-issue-1")
        self.assertEqual(result["sha"], spec.body_hash(self.body))
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.assertTrue(spec.is_approved(meta, body))
        spec.require_approval(meta, body)

    def test_a_changed_body_needs_reapproval(self) -> None:
        spec.approve(self.root, "contribution-me-app-issue-1")
        meta, _body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.path.write_text(frontmatter.dumps(meta, self.body + "\nExtra text.\n"),
                             encoding="utf-8")
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.assertFalse(spec.is_approved(meta, body))
        with self.assertRaises(spec.SpecError) as caught:
            spec.require_approval(meta, body)
        self.assertIn("changed", str(caught.exception))

    def test_an_unapproved_spec_cannot_build(self) -> None:
        code = self.root / "code"
        code.mkdir()
        (self.root / "context/repos").mkdir(parents=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "default_branch": "main",
                "code_path": str(code), "reach": "draft-pr"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-1",
                        responder=lambda _p: "{}")
        self.assertIn("not approved", str(caught.exception))

    def test_only_issues_can_be_approved(self) -> None:
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        meta["kind"] = "pr"
        self.path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        with self.assertRaises(spec.SpecError):
            spec.approve(self.root, "contribution-me-app-issue-1")

    def test_draft_spec_creates_a_linked_draft_and_keeps_the_source(self) -> None:
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        source_before = self.path.read_text(encoding="utf-8")
        drafted_body = ("Draft the spec here.\n\n## Acceptance criteria\n\n"
                        "- [ ] the flag works\n\n## Plan\n\nEdit app.py.\n")

        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: drafted_body)
        self.assertEqual(result["drafted_from"], "contribution-me-app-issue-1")
        draft_path = self.root / result["path"]
        meta, body = frontmatter.parse(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "issue")
        self.assertEqual(meta["role"], "author")
        self.assertIn("feature-spec", meta["tags"])
        self.assertEqual(meta["related"], ["contribution-me-app-issue-1"])
        self.assertEqual(body.strip(), drafted_body.strip())
        # The source issue body is untouched.
        self.assertEqual(self.path.read_text(encoding="utf-8"), source_before)

    def _seed_repo(self) -> None:
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")

    DRAFT = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n"
             "- [ ] the flag works\n\n## Plan\n\nEdit app.py.\n")

    def test_draft_refuses_the_sync_cache_stub(self) -> None:
        self._seed_repo()
        meta, _ = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.path.write_text(frontmatter.dumps(
            meta, "ISSUE #1 in me/app — https://github.com/me/app/issues/1\n\n"
                  "Cached read-only from GitHub by `stead sync github` on 2026-11-21.\n"),
            encoding="utf-8")
        with self.assertRaises(spec.SpecError) as caught:
            spec.draft_spec(self.root, "contribution-me-app-issue-1",
                            responder=lambda _p: self.DRAFT)
        self.assertIn("cache stub", str(caught.exception))

    def test_draft_refuses_a_second_draft_and_redraft_replaces(self) -> None:
        self._seed_repo()
        spec.draft_spec(self.root, "contribution-me-app-issue-1",
                        responder=lambda _p: self.DRAFT)
        with self.assertRaises(spec.SpecError) as caught:
            spec.draft_spec(self.root, "contribution-me-app-issue-1",
                            responder=lambda _p: self.DRAFT)
        self.assertIn("already exists", str(caught.exception))
        # --redraft replaces the body in place and clears approval
        replacement = self.DRAFT.replace("Edit app.py.", "Edit ctx/cli.py.")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: replacement, redraft=True)
        meta, body = frontmatter.parse(
            (self.root / result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(body.strip(), replacement.strip())
        self.assertNotIn("spec_sha", meta)

    def test_draft_requires_criteria_and_plan(self) -> None:
        self._seed_repo()
        with self.assertRaises(spec.SpecError):
            spec.draft_spec(self.root, "contribution-me-app-issue-1",
                            responder=lambda _p: "No criteria or plan.\n")

    def test_cannot_draft_from_a_draft(self) -> None:
        self._seed_repo()
        first = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                responder=lambda _p: self.DRAFT)
        with self.assertRaises(spec.SpecError) as caught:
            spec.draft_spec(self.root, first["id"], responder=lambda _p: self.DRAFT)
        self.assertIn("draft", str(caught.exception))


    def _seed_repo_with_code(self) -> Path:
        code = self.root / "code"
        for rel in ("ctx/cli.py", "ctx/metrics.py", "stead/__init__.py",
                    "tests/test_cli.py"):
            (code / rel).parent.mkdir(parents=True, exist_ok=True)
            (code / rel).write_text("# file\n", encoding="utf-8")
        (self.root / "context/repos").mkdir(parents=True, exist_ok=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "code_path": str(code)}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        return code

    def test_the_drafter_sees_the_repository_tree(self) -> None:
        self._seed_repo_with_code()
        prompts: list[str] = []

        def respond(prompt: str) -> str:
            prompts.append(prompt)
            return self.DRAFT

        spec.draft_spec(self.root, "contribution-me-app-issue-1", responder=respond)
        self.assertIn("Repository tree (depth 2)", prompts[0])
        self.assertIn("ctx/cli.py", prompts[0])
        self.assertIn("Do not invent folders", prompts[0])

    def test_without_a_checkout_the_prompt_has_no_tree(self) -> None:
        self._seed_repo()
        prompts: list[str] = []
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda p: prompts.append(p) or self.DRAFT)
        self.assertNotIn("Repository tree", prompts[0])
        self.assertEqual(result["warnings"], [])

    def test_made_up_plan_paths_are_flagged(self) -> None:
        self._seed_repo_with_code()
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] it works\n\n## Plan\n\n"
                 "- Add `stead/context/search.py`.\n- Register it in `stead/cli.py`.\n"
                 "- Test in `tests/test_search.py`; run `python -m unittest`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        self.assertEqual(len(result["warnings"]), 2)
        self.assertIn("stead/context/ is not in the repo", result["warnings"][0])
        self.assertIn("did you mean ctx/cli.py", result["warnings"][1])

    def test_real_and_new_paths_in_real_folders_pass(self) -> None:
        self._seed_repo_with_code()
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] it works\n\n## Plan\n\n"
                 "- New `ctx/search.py`, edit `ctx/cli.py`, test in "
                 "`tests/test_context_search.py`. See `https://example.com/a/b`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        self.assertEqual(result["warnings"], [])


    LONG = ("Add a small command-line flag so a caller can change the greeting "
            "without editing the source; the default output stays the same when "
            "the flag is absent, and a test covers it.")

    def _set_body(self, body: str) -> None:
        meta, _old = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")

    def test_approve_refuses_a_spec_with_too_many_criteria(self) -> None:
        criteria = "".join(f"- [ ] case {n} works\n" for n in range(1, 11))
        self._set_body(f"{self.LONG}\n\n## Acceptance criteria\n\n{criteria}")
        with self.assertRaises(spec.SpecError) as caught:
            spec.approve(self.root, "contribution-me-app-issue-1")
        self.assertIn("10 acceptance criteria", str(caught.exception))
        self.assertIn("at most 8", str(caught.exception))
        meta, _body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("spec_sha", meta)

    def test_approve_refuses_a_vague_spec(self) -> None:
        self._set_body("Add a flag.\n\n## Acceptance criteria\n\n- [ ] it works\n")
        with self.assertRaises(spec.SpecError) as caught:
            spec.approve(self.root, "contribution-me-app-issue-1")
        self.assertIn("at least 25", str(caught.exception))

    def test_draft_warns_when_a_build_would_refuse_it(self) -> None:
        self._seed_repo()
        criteria = "".join(f"- [ ] case {n} works\n" for n in range(1, 11))
        draft = f"{self.LONG}\n\n## Acceptance criteria\n\n{criteria}\n## Plan\n\nEdit app.py.\n"
        prompts: list[str] = []
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda p: prompts.append(p) or draft)
        self.assertIn("At most 8 criteria", prompts[0])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("a build would refuse this draft", result["warnings"][0])
        self.assertIn("10 acceptance criteria", result["warnings"][0])

    def _add_stead_build_issue(self, number, state="open"):
        meta = {"id": f"contribution-me-app-issue-{number}", "type": "contribution",
                "title": "Name flag", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": number,
                "role": "author", "state": state, "visibility": "public",
                "tags": ["stead-build"]}
        (self.root / "context/contributions" / f"issue-{number}.md").write_text(
            frontmatter.dumps(meta, "Add a name flag so callers can address a person.\n"),
            encoding="utf-8")

    def test_auto_draft_drafts_open_stead_build_issues_and_never_approves(self) -> None:
        self._seed_repo()
        self._add_stead_build_issue(2)
        self._add_stead_build_issue(3, state="closed")

        report = spec.auto_draft(self.root, responder=lambda _p: self.DRAFT)

        self.assertEqual(report["drafted"], ["contribution-me-app-issue-2-spec"])
        draft_path = self.root / "context/contributions/me-app-issue-2-spec.md"
        meta, _body = frontmatter.parse(draft_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["drafted_from"], "contribution-me-app-issue-2")
        self.assertNotIn("spec_sha", meta)  # never approved

    def test_auto_draft_skips_issues_with_existing_drafts(self) -> None:
        self._seed_repo()
        self._add_stead_build_issue(2)
        spec.draft_spec(self.root, "contribution-me-app-issue-2",
                        responder=lambda _p: self.DRAFT)
        report = spec.auto_draft(self.root, responder=lambda _p: self.DRAFT)
        self.assertEqual(report["drafted"], [])
        self.assertTrue(any("draft already exists" in s["reason"]
                            for s in report["skipped"]))

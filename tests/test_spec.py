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

    def test_the_drafter_sees_the_symbol_map(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/cli.py").write_text("def cmd_list():\n    pass\n", encoding="utf-8")
        (code / "ctx/metrics.py").write_text("def collect():\n    pass\n", encoding="utf-8")
        prompts: list[str] = []

        def respond(prompt: str) -> str:
            prompts.append(prompt)
            return self.DRAFT

        spec.draft_spec(self.root, "contribution-me-app-issue-1", responder=respond)
        self.assertIn("functions and classes actually defined", prompts[0])
        self.assertIn("ctx/cli.py: cmd_list", prompts[0])
        self.assertIn("ctx/metrics.py: collect", prompts[0])

    def test_invented_symbols_are_flagged(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/cli.py").write_text("def cmd_list():\n    pass\n", encoding="utf-8")
        (code / "ctx/metrics.py").write_text("def collect():\n    pass\n", encoding="utf-8")
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] it works\n\n## Plan\n\n"
                 "- Edit `ctx/cli.py` and call `cmd_list()` and `made_up_helper()`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        messages = "\n".join(result["warnings"])
        self.assertIn("made_up_helper", messages)
        self.assertNotIn("cmd_list", messages)  # a real symbol is not flagged

    def test_bare_json_keys_are_not_flagged_as_symbols(self) -> None:
        # `build_failures`/`infra_failures` are JSON keys the plan adds, not
        # functions; a bare (non-call) name must not be flagged as invented.
        code = self._seed_repo_with_code()
        (code / "ctx/metrics.py").write_text("def collect():\n    pass\n", encoding="utf-8")
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n"
                 "## Acceptance criteria\n\n- [ ] it works\n\n"
                 "## Plan\n\nEdit `ctx/metrics.py` to emit top-level "
                 "`build_failures` and `infra_failures` keys from `collect()`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        self.assertEqual(result["warnings"], [])

    def test_wrong_module_member_is_flagged(self) -> None:
        # `collect` is defined in ctx/metrics.py, not ctx/cli.py; naming it as
        # cli.collect must flag even though `collect` exists elsewhere.
        code = self._seed_repo_with_code()
        (code / "ctx/cli.py").write_text("def cmd_list():\n    pass\n", encoding="utf-8")
        (code / "ctx/metrics.py").write_text("def collect():\n    pass\n", encoding="utf-8")
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] it works\n\n## Plan\n\n"
                 "- Edit `ctx/cli.py` and call `cli.collect`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        messages = "\n".join(result["warnings"])
        self.assertIn("not defined in `cli`", messages)

    def test_data_model_facts_derive_from_schema(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/schema.sql").write_text(
            "CREATE TABLE repos (\n    id TEXT PRIMARY KEY,\n    title TEXT,\n"
            "    kind TEXT NOT NULL CHECK (kind IN ('own','oss'))\n);\n",
            encoding="utf-8")
        facts = spec.data_model_facts(self.root, {"id": "repo-me-app"}, "", code)
        self.assertIn("repos(id, title, kind)", facts)
        self.assertNotIn("CHECK", facts)  # constraint keywords are not columns

    def test_schema_derives_from_any_sql_file_not_just_ctx(self) -> None:
        # A non-Stead repo's schema (db/schema.sql) must still be derived.
        code = self._seed_repo_with_code()
        (code / "db").mkdir(parents=True, exist_ok=True)
        (code / "db/schema.sql").write_text(
            "CREATE TABLE users (\n    id TEXT,\n    email TEXT\n);\n",
            encoding="utf-8")
        facts = spec.data_model_facts(self.root, {"id": "repo-me-app"}, "", code)
        self.assertIn("users(id, email)", facts)
        self.assertNotIn("Markdown object types", facts)  # no Stead TYPE_DIRS leak

    def test_declared_data_model_is_included(self) -> None:
        code = self._seed_repo_with_code()
        repo_meta = {"id": "repo-me-app",
                     "notes": "repos come from the `repos` table, not config."}
        body = "## Data model\n\nusers live in the `users` table.\n"
        facts = spec.data_model_facts(self.root, repo_meta, body, code)
        self.assertIn("repos come from", facts)
        self.assertIn("users live in", facts)

    def test_no_schema_no_declared_is_empty(self) -> None:
        code = self._seed_repo_with_code()
        facts = spec.data_model_facts(self.root, {"id": "repo-me-app"}, "", code)
        self.assertEqual(facts, "")

    def test_spec_gate_corpus_passes_on_non_stead_fixtures(self) -> None:
        # The committed non-Stead fixture corpus (Prisma, SQLAlchemy, declared-only)
        # must pass the deterministic gates — this is what keeps the per-repo data
        # model working for any repo, not just Stead.
        repo = Path(__file__).parent.parent
        result = spec.check_gate_cases(repo / "tests" / "fixtures" / "spec-gates.json",
                                       repo / "tests" / "fixtures" / "repos")
        self.assertTrue(result["ok"], "\n".join(result["problems"]))
        self.assertEqual(result["passed"], 5)

    def test_fabricated_sql_table_is_flagged(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/schema.sql").write_text(
            "CREATE TABLE repos (id TEXT, title TEXT);\n"
            "CREATE TABLE tasks (id TEXT, title TEXT);\n", encoding="utf-8")
        plan = "query the `build_records` table and `INSERT INTO build_records`.\n"
        messages = "\n".join(spec.plan_data_warnings(plan, code))
        self.assertIn("build_records", messages)
        self.assertIn("no such table", messages)

    def test_config_claim_for_data_is_flagged(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/schema.sql").write_text(
            "CREATE TABLE repos (id TEXT);\n", encoding="utf-8")
        plan = "read the repos from `config.load()[\"repos\"]`.\n"
        messages = "\n".join(spec.plan_data_warnings(plan, code))
        self.assertIn("repos", messages)
        self.assertIn("not a config key", messages)

    def test_real_table_and_plain_config_key_are_not_flagged(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/schema.sql").write_text(
            "CREATE TABLE repos (id TEXT);\n", encoding="utf-8")
        plan = "query the `repos` table and read `config.timeout`.\n"
        self.assertEqual(spec.plan_data_warnings(plan, code), [])

    def test_draft_spec_records_data_model_warnings(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/schema.sql").write_text(
            "CREATE TABLE repos (id TEXT);\n", encoding="utf-8")
        (code / "ctx/config.py").write_text("def load():\n    pass\n", encoding="utf-8")
        draft = ("Add a small flag.\n\n## Acceptance criteria\n\n- [ ] it works\n\n"
                 "## Plan\n\nRead the repos from `config.load()[\"repos\"]`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        self.assertIn("not a config key", "\n".join(result["warnings"]))

    def test_stdlib_and_test_data_are_not_flagged(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/cli.py").write_text("def cmd_list():\n    pass\n", encoding="utf-8")
        draft = ("Add a small command-line flag so a caller can change the greeting without editing the source; the default output stays the same when the flag is absent, and a test covers it.\n\n## Acceptance criteria\n\n- [ ] it works\n\n## Plan\n\n"
                 "- Edit `ctx/cli.py`: call `json.dumps`, `re.match`, and "
                 "`os.path.join`; use `ctx.cli.cmd_list`; seed data named "
                 "`alpha` and `beta`.\n")
        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=lambda _p: draft)
        self.assertEqual(result["warnings"], [])

    def test_drafter_can_read_and_search_before_finishing(self) -> None:
        code = self._seed_repo_with_code()
        (code / "ctx/cli.py").write_text(
            "def cmd_repo_list(root, kind=None):\n"
            "    query = 'SELECT id, kind, status, title FROM repos'\n",
            encoding="utf-8")
        import json as _json
        replies = [
            # First turn: read the command the issue names.
            _json.dumps({"action": "read", "path": "ctx/cli.py"}),
            # Second turn: trace the data source.
            _json.dumps({"action": "search", "query": "FROM repos"}),
            # Third turn: finish with a spec.
            _json.dumps({"action": "finish", "spec": self.DRAFT}),
        ]
        prompts: list[str] = []

        def respond(prompt: str) -> str:
            prompts.append(prompt)
            return replies.pop(0)

        result = spec.draft_spec(self.root, "contribution-me-app-issue-1",
                                 responder=respond)
        self.assertEqual(result["path"].endswith("-spec.md"), True)
        # The model saw the real file content it read.
        self.assertTrue(any("SELECT id, kind, status, title FROM repos" in p
                            for p in prompts))
        self.assertTrue(any("cmd_repo_list" in p for p in prompts))


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
        self.assertIn("8 is the hard maximum", prompts[0])
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

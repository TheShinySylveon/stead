"""Unit tests: feature-builder factory (issue -> PR build, shadow/draft-PR).

Covers deterministic spec parsing + quality flags, bundle assembly (spec +
acceptance criteria + repo conventions + related docs + duplicate-sweep
input), run artifacts/ledger, prompt seeding, CLI --contribution routing, and
proof that shadow assembly performs NO subprocess/network/remote writes.

All tests run against a temporary root — never the real repo state. No test
touches the network; any subprocess call during assembly fails the test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx import cli, db, factory, frontmatter
from tests.test_ctx import make_root

SPEC_BODY = (
    "# Add --json output to the list command\n\n"
    "The CLI `list` command prints a human-readable table only. Add an opt-in "
    "`--json` flag that emits a single JSON array on stdout, one object per "
    "item, with stable field names. The default output must stay unchanged "
    "when the flag is absent. Errors keep going to stderr with a non-zero "
    "exit code. Follow CONTRIBUTING for test layout and commit style.\n\n"
    "## Acceptance criteria\n\n"
    "- [ ] `list --json` prints a valid JSON array to stdout\n"
    "- [ ] Each object contains id, title, and status fields\n"
    "- [ ] Without the flag, output is unchanged and existing tests pass\n"
)
CRITERIA_TEXTS = (
    "`list --json` prints a valid JSON array to stdout",
    "Each object contains id, title, and status fields",
    "Without the flag, output is unchanged and existing tests pass",
)
SPEC_ID = "contribution-testuser-my-app-issue-201"


def add_feature_builder_factory(root: Path) -> Path:
    """Extend the minimal skeleton with the feature-builder factory."""
    fdir = root / "factories" / "feature-builder"
    (fdir / "prompts").mkdir(parents=True, exist_ok=True)
    (fdir / "evals").mkdir(parents=True, exist_ok=True)
    (fdir / "FACTORY.md").write_text("# FACTORY: feature-builder\n", encoding="utf-8")
    (fdir / "prompts" / "v1.md").write_text(
        "Build the feature spec in the bundle below.\n", encoding="utf-8")
    return root


class FeatureBuilderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = add_feature_builder_factory(make_root(Path(self._tmp.name)))
        db.init_db(self.root)

    def seed_repo(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="own", default_branch="main",
                         contributing="https://github.com/testuser/my-app/blob/main/CONTRIBUTING.md",
                         notes="Run pytest and ruff before pushing.")

    def seed_spec(self, body: str = SPEC_BODY, kind: str = "issue", role: str = "author",
                  number: int = 201, related: list | None = None) -> str:
        self.seed_repo()
        cli.cmd_contribution_add(self.root, "Add --json output", "repo-testuser-my-app",
                                 kind, number, role=role)
        stem = f"testuser-my-app-{kind}-{number}"
        path = self.root / "context" / "contributions" / f"{stem}.md"
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["tags"] = ["feature-spec"]
        if related is not None:
            meta["related"] = related
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        db.init_db(self.root)  # re-index from files (idempotent)
        return f"contribution-{stem}"

    def add_document(self, doc_id: str, title: str, body: str) -> None:
        meta = {"id": doc_id, "type": "document", "title": title,
                "created": "2026-11-21", "updated": "2026-11-21",
                "project": "project-demo"}
        stem = doc_id.removeprefix("document-")
        (self.root / "context" / "documents" / f"{stem}.md").write_text(
            frontmatter.dumps(meta, body), encoding="utf-8")


# --- spec parsing + deterministic quality flags --------------------------------

class TestSpecParsing(unittest.TestCase):
    def test_split_spec_extracts_criteria(self) -> None:
        description, criteria = factory.split_spec(SPEC_BODY)
        self.assertIn("opt-in", description)
        self.assertNotIn("Acceptance criteria", description)
        self.assertEqual([text for _done, text in criteria], list(CRITERIA_TEXTS))
        self.assertEqual([done for done, _text in criteria], [False, False, False])

    def test_split_spec_done_items_and_section_boundary(self) -> None:
        body = ("Description words here.\n\n## Acceptance criteria\n\n"
                "- [x] already done\n- [ ] still open\n\n## Out of scope\n\n"
                "- [ ] not a criterion\n")
        _description, criteria = factory.split_spec(body)
        self.assertEqual(criteria, [(True, "already done"), (False, "still open")])

    def test_split_spec_missing_section(self) -> None:
        description, criteria = factory.split_spec("Just a wish.\n")
        self.assertEqual(criteria, [])
        self.assertEqual(description, "Just a wish.")

    def test_flags_clear_spec(self) -> None:
        description, criteria = factory.split_spec(SPEC_BODY)
        self.assertEqual(factory.spec_flags(description, criteria), [])

    def test_flags_vague_and_missing(self) -> None:
        flags = factory.spec_flags("Make it better.", [])
        self.assertIn("missing-acceptance-criteria", flags)
        self.assertIn("vague-spec", flags)

    def test_flags_large_spec(self) -> None:
        criteria = [(False, f"criterion number {i} with words") for i in range(9)]
        self.assertIn("large-spec", factory.spec_flags("word " * 30, criteria))
        self.assertIn("large-spec", factory.spec_flags("word " * 401, [(False, "one")]))


# --- assembly -------------------------------------------------------------------

class TestFeatureBuilderAssembly(FeatureBuilderTestCase):
    def test_init_seeds_feature_builder_prompt_v1(self) -> None:
        counts = db.init_db(self.root)
        self.assertEqual(counts["prompt_versions"], 2)  # status + feature-builder
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT version, status, path FROM prompt_versions "
                               "WHERE factory='feature-builder'").fetchone()
            self.assertEqual((row["version"], row["status"]), ("v1", "production"))
            self.assertEqual(row["path"], "factories/feature-builder/prompts/v1.md")
        finally:
            conn.close()

    def test_bundle_artifacts_and_ledger(self) -> None:
        self.seed_spec()
        info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertEqual(info["factory"], "feature-builder")
        self.assertEqual(info["mode"], "shadow")
        self.assertEqual(info["contribution"], SPEC_ID)
        self.assertEqual(info["repo"], "repo-testuser-my-app")
        self.assertEqual(info["flags"], [])
        self.assertFalse(info["needs_decomposition"])
        self.assertEqual(info["counts"], {"acceptance_criteria": 3, "related_documents": 0,
                                          "related_contributions": 0, "spec_flags": 0})
        run_dir = self.root / info["run_dir"]
        for name in ("bundle.md", "prompt.md", "run.json"):
            self.assertTrue((run_dir / name).exists(), name)
        bundle = (run_dir / "bundle.md").read_text(encoding="utf-8")
        # spec + every acceptance criterion
        self.assertIn("Add --json output", bundle)
        self.assertIn("## Acceptance criteria", bundle)
        for text in CRITERIA_TEXTS:
            self.assertIn(text, bundle)
        # repo conventions
        self.assertIn("https://github.com/testuser/my-app", bundle)
        self.assertIn("default_branch: main", bundle)
        self.assertIn("CONTRIBUTING.md", bundle)
        self.assertIn("Run pytest and ruff before pushing.", bundle)
        self.assertIn("[kind: own]", bundle)
        # shadow safety block
        self.assertIn("SHADOW", bundle)
        self.assertIn("NO remote writes", bundle)
        self.assertIn("never push to main/the default branch", bundle)
        self.assertIn("spec looks buildable", bundle)
        prompt = (run_dir / "prompt.md").read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith("Build the feature spec"))
        self.assertIn("Feature build bundle", prompt)
        run_json = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run_json["counts"], info["counts"])
        self.assertEqual(run_json["mode"], "shadow")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT factory, task_ref, project, mode, verdict "
                               "FROM runs").fetchone()
            self.assertEqual((row["factory"], row["task_ref"], row["project"],
                              row["mode"], row["verdict"]),
                             ("feature-builder", SPEC_ID, None, "shadow", "pending"))
        finally:
            conn.close()

    def test_related_documents_included_and_missing_noted(self) -> None:
        self.add_document("document-cli-design", "CLI design notes",
                          "# CLI design notes\n\nJSON output must be a single array.\n")
        self.seed_spec(related=["document-cli-design", "document-ghost"])
        info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertEqual(info["counts"]["related_documents"], 1)
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("## Related documents (1)", bundle)
        self.assertIn("CLI design notes", bundle)
        self.assertIn("JSON output must be a single array.", bundle)
        self.assertIn("Related refs not found: document-ghost", bundle)

    def test_duplicate_sweep_lists_sibling_contributions(self) -> None:
        self.seed_spec()
        cli.cmd_contribution_add(self.root, "WIP json output", "repo-testuser-my-app",
                                 "pr", 7, role="author", state="open")
        cli.cmd_contribution_add(self.root, "Prior attempt", "repo-testuser-my-app",
                                 "issue", 5, role="author", state="closed")
        info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertEqual(info["counts"]["related_contributions"], 2)
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("## Related work in local cache (2)", bundle)
        self.assertIn("[pr #7]", bundle)
        self.assertIn("[issue #5]", bundle)
        # deterministic order: kind then number; the spec itself is not a sibling
        sweep = bundle.split("## Related work in local cache")[1]
        self.assertLess(sweep.find("[issue #5]"), sweep.find("[pr #7]"))
        self.assertNotIn("[issue #201]", sweep)

    def test_shadow_assembly_no_subprocess_no_network(self) -> None:
        self.seed_spec()
        boom = AssertionError("subprocess/network used during feature-builder assembly")
        with mock.patch("subprocess.run", side_effect=boom), \
             mock.patch("subprocess.Popen", side_effect=boom), \
             mock.patch("socket.create_connection", side_effect=boom), \
             mock.patch("socket.getaddrinfo", side_effect=boom), \
             mock.patch("urllib.request.urlopen", side_effect=boom):
            self.assertEqual(cli.cmd_factory_run(self.root, "feature-builder", None,
                                                 contribution=SPEC_ID), 0)
            info = factory.assemble_feature_build(self.root, SPEC_ID, mode="live")
        self.assertEqual(info["mode"], "live")  # assembly stays local in BOTH modes

    def test_vague_spec_flagged_needs_decomposition(self) -> None:
        self.seed_spec(body="# Make it better\n\nMake the list command better somehow.\n")
        info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertTrue(info["needs_decomposition"])
        self.assertIn("missing-acceptance-criteria", info["flags"])
        self.assertIn("vague-spec", info["flags"])
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("NEEDS DECOMPOSITION", bundle)
        self.assertIn("decomposition/clarification plan instead of code", bundle)
        self.assertEqual(cli.cmd_factory_run(self.root, "feature-builder", None,
                                             contribution=SPEC_ID), 0)

    def test_large_spec_flagged(self) -> None:
        criteria = "\n".join(f"- [ ] criterion {i} with enough words" for i in range(9))
        self.seed_spec(body=SPEC_BODY.split("## Acceptance criteria")[0]
                       + "## Acceptance criteria\n\n" + criteria + "\n")
        info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertIn("large-spec", info["flags"])
        self.assertTrue(info["needs_decomposition"])

    def test_live_mode_bundle_encodes_draft_pr_rules(self) -> None:
        self.seed_spec()
        repo = self.root / "context" / "repos" / "testuser-my-app.md"
        meta, body = frontmatter.parse(repo.read_text(encoding="utf-8"))
        meta["reach"] = "draft-pr"
        repo.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        info = factory.assemble_feature_build(self.root, SPEC_ID, mode="live")
        self.assertEqual(info["reach"], "draft-pr")
        self.assertEqual(info["remote"], "not-implemented")
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("DRAFT-PR", bundle)
        self.assertIn("gh pr create --draft", bundle)
        self.assertIn("HUMAN reviews", bundle)
        self.assertIn("did not push", bundle)
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT mode FROM runs").fetchone()
            self.assertEqual(row["mode"], "live")
        finally:
            conn.close()

    def test_rejects_pr_target_and_non_enabled_spec(self) -> None:
        self.seed_spec(kind="pr", number=7)
        with self.assertRaises(SystemExit):
            factory.assemble_feature_build(self.root, "contribution-testuser-my-app-pr-7")
        self.seed_spec(kind="issue", number=9)
        # Strip the feature-spec tag: the issue is no longer an enabled target
        # (the `author` role alone is not a gate).
        path = self.root / "context" / "contributions" / "testuser-my-app-issue-9.md"
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["tags"] = []
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        with self.assertRaises(SystemExit):
            factory.assemble_feature_build(self.root, "contribution-testuser-my-app-issue-9")

    def test_missing_contribution_and_cli_routing_errors(self) -> None:
        with self.assertRaises(SystemExit):
            factory.assemble_feature_build(self.root, "contribution-ghost")
        with self.assertRaises(SystemExit):  # --contribution required
            cli.cmd_factory_run(self.root, "feature-builder", None)
        with self.assertRaises(SystemExit):  # --contribution only for feature-builder
            cli.cmd_factory_run(self.root, "weekly-contribution-digest", None,
                                contribution=SPEC_ID)

    def test_cli_parser_accepts_contribution(self) -> None:
        args = cli.build_parser().parse_args(
            ["factory", "run", "--factory", "feature-builder",
             "--contribution", SPEC_ID, "--shadow"])
        self.assertEqual(args.contribution, SPEC_ID)
        self.assertTrue(args.shadow)

    def test_requires_production_prompt(self) -> None:
        self.seed_spec()
        conn = db.connect(self.root)
        try:
            conn.execute("DELETE FROM prompt_versions WHERE factory='feature-builder'")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SystemExit):
            factory.assemble_feature_build(self.root, SPEC_ID)


# --- shipped factory artifacts (read-only checks against the real repo) ---------

class TestShippedFactoryArtifacts(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_factory_md_defines_autonomy_ladder_and_safety(self) -> None:
        text = (self.ROOT / "factories/feature-builder/FACTORY.md").read_text(encoding="utf-8")
        for needle in ("SHADOW", "DRAFT-PR", "TRUSTED", "never the default",
                       "Never push to main", "Never auto-merge",
                       "Human review gate", "decomposition"):
            self.assertIn(needle, text, needle)

    def test_prompt_v1_encodes_issue_to_pr_discipline(self) -> None:
        text = (self.ROOT / "factories/feature-builder/prompts/v1.md").read_text(encoding="utf-8")
        for needle in ("ALL comments", "duplicate", "Validate the premise",
                       "EACH acceptance criterion", "TDD red-green", "isolated",
                       "Sabotage-test", "quality gates", "gh pr create --draft",
                       "Closes #", "gh pr checks", "NEVER push to main",
                       "NEVER auto-merge", "decomposition"):
            self.assertIn(needle, text, needle)

    def test_evals_present_and_valid(self) -> None:
        evals = sorted((self.ROOT / "factories/feature-builder/evals").glob("*.json"))
        self.assertEqual(len(evals), 6)
        ids = set()
        for path in evals:
            case = json.loads(path.read_text(encoding="utf-8"))
            for key in ("id", "title", "input", "pass_criteria"):
                self.assertIn(key, case)
            self.assertEqual(case["factory"], "feature-builder")
            ids.add(case["id"])
        self.assertEqual(ids, {"eval-feature-clear-spec", "eval-feature-vague-spec",
                               "eval-feature-duplicate-work",
                               "eval-feature-spec-kit-method",
                               "eval-feature-builtin-method",
                               "eval-feature-spec-kit-vague"})

    def test_example_spec_seed_is_buildable(self) -> None:
        path = self.ROOT / "examples/context/contributions/example-org-example-repo-issue-201.md"
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "issue")
        self.assertEqual(meta["role"], "author")
        self.assertEqual(meta["repo"], "repo-example-org-example-repo")
        self.assertIn("feature-spec", meta["tags"])
        self.assertIn("example", meta["tags"])
        self.assertIn("EXAMPLE", meta["title"])
        description, criteria = factory.split_spec(body)
        self.assertGreaterEqual(len(criteria), 3)
        self.assertEqual(factory.spec_flags(description, criteria), [])


if __name__ == "__main__":
    unittest.main()
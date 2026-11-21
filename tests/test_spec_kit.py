"""Unit tests: Spec Kit (Spec-Driven Development) integration in feature-builder.

Covers the `method` contribution field (spec-kit | builtin, DEFAULT spec-kit),
method-aware bundle assembly (## Method + run.json), the always-on planning-first
v2 prompt (seeding + promotion), SDD eval cases, and proof that assembly stays
subprocess/network-free for BOTH methods and BOTH modes.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx import cli, db, factory, frontmatter, objects
from tests.test_ctx import make_root
from tests.test_feature_builder import SPEC_BODY, add_feature_builder_factory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
V2_STUB = ("# Prompt v2 — feature-builder (spec-driven, planning-first)\n\n"
           "PLANNING-FIRST-MARKER: never write code before spec/plan/tasks.\n")


def _net_guards():
    return (mock.patch("subprocess.run", side_effect=AssertionError("subprocess.run called")),
            mock.patch("subprocess.Popen", side_effect=AssertionError("subprocess.Popen called")),
            mock.patch("socket.socket", side_effect=AssertionError("socket.socket called")),
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("urlopen called")))


class SpecKitTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = add_feature_builder_factory(make_root(Path(self._tmp.name)))
        (self.root / "factories" / "feature-builder" / "prompts" / "v2.md").write_text(
            V2_STUB, encoding="utf-8")
        db.init_db(self.root)

    def seed_repo(self):
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="own", default_branch="main",
                         contributing="https://github.com/testuser/my-app/blob/main/CONTRIBUTING.md",
                         notes="Run pytest and ruff before pushing.")

    def seed_spec(self, method=None, number=201):
        self.seed_repo()
        kwargs = {"method": method} if method is not None else {}
        cli.cmd_contribution_add(self.root, "Add --json output", "repo-testuser-my-app",
                                 "issue", number, role="author", **kwargs)
        stem = f"testuser-my-app-issue-{number}"
        path = self.root / "context" / "contributions" / f"{stem}.md"
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["tags"] = ["feature-spec"]
        path.write_text(frontmatter.dumps(meta, SPEC_BODY), encoding="utf-8")
        db.init_db(self.root)
        return f"contribution-{stem}"


class TestMethodField(SpecKitTestCase):
    def test_default_is_spec_kit(self):
        ref = self.seed_spec()
        _, meta, _ = objects.find(self.root, "contribution", ref)
        self.assertEqual(meta["method"], "spec-kit")

    def test_add_builtin(self):
        ref = self.seed_spec(method="builtin")
        _, meta, _ = objects.find(self.root, "contribution", ref)
        self.assertEqual(meta["method"], "builtin")

    def test_add_spec_kit(self):
        ref = self.seed_spec(method="spec-kit")
        _, meta, _ = objects.find(self.root, "contribution", ref)
        self.assertEqual(meta["method"], "spec-kit")

    def test_set_method(self):
        ref = self.seed_spec(method="builtin")
        cli.cmd_contribution_set(self.root, ref, method="spec-kit")
        _, meta, _ = objects.find(self.root, "contribution", ref)
        self.assertEqual(meta["method"], "spec-kit")

    def test_invalid_method_rejected(self):
        with self.assertRaises(SystemExit):
            cli.cmd_contribution_add(self.root, "X", "repo-testuser-my-app",
                                     "issue", 999, method="nope")


class TestMethodAssembly(SpecKitTestCase):
    def test_builtin_assembly(self):
        ref = self.seed_spec(method="builtin")
        info = factory.assemble_feature_build(self.root, ref, mode="shadow")
        self.assertEqual(info["method"], "builtin")
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("## Method\nbuiltin", bundle)
        run = json.loads((self.root / info["run_dir"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["method"], "builtin")

    def test_spec_kit_assembly(self):
        ref = self.seed_spec(method="spec-kit")
        info = factory.assemble_feature_build(self.root, ref, mode="shadow")
        self.assertEqual(info["method"], "spec-kit")
        bundle = (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("## Method\nspec-kit", bundle)
        run = json.loads((self.root / info["run_dir"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["method"], "spec-kit")

    def test_default_assembly_is_spec_kit(self):
        ref = self.seed_spec()
        info = factory.assemble_feature_build(self.root, ref, mode="shadow")
        self.assertEqual(info["method"], "spec-kit")


class TestPromptV2(SpecKitTestCase):
    def test_shipped_v2_is_planning_first(self):
        p = PROJECT_ROOT / "factories" / "feature-builder" / "prompts" / "v2.md"
        text = p.read_text(encoding="utf-8")
        for marker in ("spec-driven", "planning-first", "/speckit-constitution",
                       "/speckit-specify", "/speckit-plan", "/speckit-tasks",
                       "/speckit-implement", "/speckit-converge",
                       "context/tasks", "context/documents"):
            self.assertIn(marker, text)

    def test_v2_is_production_by_default(self):
        conn = db.connect(self.root)
        try:
            rows = conn.execute(
                "SELECT version, status FROM prompt_versions WHERE factory='feature-builder'"
            ).fetchall()
        finally:
            conn.close()
        status = {r[0]: r[1] for r in rows}
        self.assertEqual(status["v2"], "production")
        self.assertNotEqual(status.get("v1"), "production")

    def test_assembly_uses_v2_naturally(self):
        ref = self.seed_spec()   # re-seeds; v2 stays production (highest version)
        info = factory.assemble_feature_build(self.root, ref, mode="shadow")
        self.assertEqual(info["prompt_version"], "v2")
        self.assertIn("PLANNING-FIRST-MARKER", info["assembled_prompt"])

    def test_promote_v1_rollback(self):
        cli.cmd_prompt_promote(self.root, "feature-builder", "v1")
        conn = db.connect(self.root)
        try:
            rows = conn.execute(
                "SELECT version, status FROM prompt_versions WHERE factory='feature-builder'"
            ).fetchall()
        finally:
            conn.close()
        status = {r[0]: r[1] for r in rows}
        self.assertEqual(status["v1"], "production")
        self.assertNotEqual(status.get("v2"), "production")


class TestNetworkFree(SpecKitTestCase):
    def test_both_methods_both_modes_network_free(self):
        self.seed_repo()
        refs = {}
        for i, method in enumerate(["builtin", "spec-kit"]):
            num = 201 + i
            cli.cmd_contribution_add(self.root, f"Spec {method}", "repo-testuser-my-app",
                                     "issue", num, role="author", method=method)
            stem = f"testuser-my-app-issue-{num}"
            path = self.root / "context" / "contributions" / f"{stem}.md"
            meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
            meta["tags"] = ["feature-spec"]
            path.write_text(frontmatter.dumps(meta, SPEC_BODY), encoding="utf-8")
            refs[method] = f"contribution-{stem}"
        db.init_db(self.root)

        g1, g2, g3, g4 = _net_guards()
        with g1, g2, g3, g4:
            for method, ref in refs.items():
                for mode in ("shadow", "live"):
                    info = factory.assemble_feature_build(self.root, ref, mode=mode)
                    self.assertEqual(info["method"], method)
                    self.assertEqual(info["mode"], mode)


class TestEvals(SpecKitTestCase):
    def test_spec_kit_evals_present_and_valid(self):
        evals_dir = PROJECT_ROOT / "factories" / "feature-builder" / "evals"
        ids = set()
        files = list(evals_dir.glob("eval-feature-spec-kit*.json")) + list(evals_dir.glob("eval-feature-builtin-method.json"))
        for f in files:
            case = json.loads(f.read_text(encoding="utf-8"))
            for key in ("id", "title", "input", "pass_criteria"):
                self.assertIn(key, case)
            ids.add(case["id"])
        self.assertIn("eval-feature-spec-kit-method", ids)
        self.assertIn("eval-feature-builtin-method", ids)

    def test_evals_load_into_db(self):
        evals_dir = self.root / "factories" / "feature-builder" / "evals"
        evals_dir.mkdir(exist_ok=True)
        (evals_dir / "eval-feature-spec-kit-method.json").write_text(
            json.dumps({"id": "eval-feature-spec-kit-method", "title": "t",
                        "input": "i", "pass_criteria": "p"}), encoding="utf-8")
        db.init_db(self.root)
        conn = db.connect(self.root)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM evals WHERE factory='feature-builder'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

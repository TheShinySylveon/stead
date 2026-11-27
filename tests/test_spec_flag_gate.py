"""Deterministic tests for the CLI flag-existence draft gate."""

import tempfile
import unittest
from pathlib import Path

from ctx import spec

CLI_FIXTURE = '''
import argparse


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="Print a count")
    parser.add_argument("--json", action="store_true", help="JSON output")
    return parser
'''


class SpecFlagGateTests(unittest.TestCase):
    def _make_code(self, text: str = CLI_FIXTURE) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        code = Path(tmp.name)
        (code / "cli.py").write_text(text, encoding="utf-8")
        return code

    def test_fabricated_existing_flag_is_flagged(self) -> None:
        code = self._make_code()
        plan = "Reuse the existing `--limit` flag to cap the list.\n"
        warnings = spec.plan_flag_warnings(plan, code)
        self.assertEqual(len(warnings), 1)
        self.assertIn("--limit", warnings[0])

    def test_real_flag_is_clean(self) -> None:
        code = self._make_code()
        plan = "Use the `--count` flag to print totals.\n"
        self.assertEqual(spec.plan_flag_warnings(plan, code), [])

    def test_proposed_new_flag_is_clean(self) -> None:
        code = self._make_code()
        plan = "Add a new `--limit` flag to cap the list.\n"
        self.assertEqual(spec.plan_flag_warnings(plan, code), [])

    def test_no_cli_definitions_is_noop(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        code = Path(tmp.name)
        (code / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        plan = "Reuse the existing `--limit` flag.\n"
        self.assertEqual(spec.plan_flag_warnings(plan, code), [])

    def test_flags_are_derived_from_checkout_not_hardcoded(self) -> None:
        custom = ('import argparse\n'
                  'parser = argparse.ArgumentParser()\n'
                  'parser.add_argument("--foo", action="store_true")\n')
        code = self._make_code(custom)
        self.assertEqual(spec.plan_flag_warnings("Use the `--foo` flag.\n", code), [])
        warnings = spec.plan_flag_warnings("Reuse the existing `--bar` flag.\n", code)
        self.assertEqual(len(warnings), 1)
        self.assertIn("--bar", warnings[0])

    def test_spec_gate_corpus_includes_flag_cases(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        result = spec.check_gate_cases(
            fixtures / "spec-gates.json", fixtures / "repos", include_flag=True)
        self.assertTrue(result["ok"], "\n".join(result["problems"]))
        self.assertEqual(result["passed"], 9)


if __name__ == "__main__":
    unittest.main()

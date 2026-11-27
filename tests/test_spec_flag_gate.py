"""Deterministic tests for the CLI flag-existence draft gate."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ctx import cli, spec

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

    def test_missing_existing_flag_in_backticks_is_flagged(self) -> None:
        code = self._make_code()
        warnings = spec.plan_flag_warnings("Use the `--limit` flag.", code)
        self.assertEqual(len(warnings), 1)
        self.assertIn("--limit", warnings[0])

    def test_other_tasks_do_not_hide_existing_flags(self) -> None:
        code = self._make_code()
        for plan in (
            "Reuse the existing `--limit` flag. Add a regression test.",
            "Reuse the existing `--limit` flag and add a new `--jsonl` flag.",
            "Add regression coverage for the existing `--limit` flag.",
            "Mention `--limit`. Reuse the existing `--limit` flag.",
        ):
            with self.subTest(plan=plan):
                warnings = spec.plan_flag_warnings(plan, code)
                self.assertEqual(len(warnings), 1)
                self.assertIn("--limit", warnings[0])

    def test_examples_in_python_strings_and_keywords_are_not_definitions(self) -> None:
        code = self._make_code(CLI_FIXTURE + '''
example = 'parser.add_argument("--fake")'
parser.add_argument("query", help="Example: --fake-help")
''')
        for flag in ("--fake", "--fake-help"):
            with self.subTest(flag=flag):
                warnings = spec.plan_flag_warnings(f"Reuse the existing `{flag}` flag.", code)
                self.assertEqual(len(warnings), 1)
                self.assertIn(flag, warnings[0])

    def test_real_flag_is_clean(self) -> None:
        code = self._make_code()
        plan = "Use the `--count` flag to print totals.\n"
        self.assertEqual(spec.plan_flag_warnings(plan, code), [])

    def test_proposed_new_flag_is_clean(self) -> None:
        code = self._make_code()
        for plan in (
            "Add a new `--limit` flag to cap the list.",
            "Add support for the `--limit` flag.",
            "Wire up the new `--limit` option.",
        ):
            with self.subTest(plan=plan):
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

    def test_normal_cli_eval_runs_flag_cases(self) -> None:
        with tempfile.TemporaryDirectory() as root, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["--root", root, "eval", "run"]), 0)
        self.assertIn("spec gates 9/9", out.getvalue())


if __name__ == "__main__":
    unittest.main()

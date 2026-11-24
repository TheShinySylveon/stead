"""Anti-slop rules: deterministic, language-agnostic, no parser or network."""

from __future__ import annotations

import unittest

from ctx import slop


class SlopTest(unittest.TestCase):
    def test_python_hard_rules(self) -> None:
        self.assertTrue(slop.hard_flags("a.py", "try:\n    x = 1\nexcept:\n    pass\n"))
        self.assertTrue(slop.hard_flags("a.py", 'name = "%s" % user\n'))
        self.assertTrue(slop.hard_flags("a.py", "if False:\n    do_thing()\n"))

    def test_python_advisory_debug_print(self) -> None:
        findings = slop.slop_flags("a.py", "print('hi')\n")
        self.assertFalse(slop.hard_flags("a.py", "print('hi')\n"))
        self.assertTrue(any(f["rule"] == "debug-print" for f in findings))

    def test_c_gets_is_hard(self) -> None:
        self.assertTrue(slop.hard_flags("a.c", "gets(buf);\n"))
        self.assertTrue(slop.hard_flags("a.h", "gets(buf);\n"))

    def test_js_any_is_advisory(self) -> None:
        findings = slop.slop_flags("a.ts", "let x: any = 1;\n")
        self.assertTrue(any(f["rule"] == "any-type" for f in findings))
        self.assertFalse(any(f["hard"] for f in findings))

    def test_clean_file_has_no_findings(self) -> None:
        self.assertEqual(slop.slop_flags("a.py", "def f():\n    return 1\n"), [])

    def test_commented_out_code_is_hard(self) -> None:
        self.assertTrue(slop.hard_flags("a.py", "# x = 1\n# y = 2;\n# z = {}\n"))

    def test_unknown_extension_still_gets_universal_rules(self) -> None:
        # No .xyz rules, but the universal commented-out rule still applies.
        self.assertTrue(slop.hard_flags("a.xyz", "// a = 1;\n// b = 2;\n// c = 3;\n"))

    def test_comment_mentioning_word_does_not_fire(self) -> None:
        # A comment that says "gets" is not a call.
        self.assertEqual(slop.slop_flags("a.c", "// remember to replace gets later\n"), [])


if __name__ == "__main__":
    unittest.main()

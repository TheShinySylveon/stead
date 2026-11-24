"""Deterministic anti-slop rules for model-written code.

Language-agnostic by construction: a universal set of textual checks plus a
per-extension registry. stdlib regex/text only — no parser, no network, no
SaaS. This is Stead's own thin layer on top of the repo's linter (which
``checks:`` already runs), not a replacement for it: the language's real
toolchain (clang-tidy, ruff, eslint) stays the authoritative gate.

Every rule is either *hard* or *advisory*:

- **Hard** — a pattern that is almost never correct (a bare ``except:`` that
  swallows an error, ``gets(`` in C, ``%``-format in Python 3). A *new* file
  the model authored whole that still carries a hard finding fails the build
  after the repair rounds, mirroring the fail-before gate.
- **Advisory** — a pattern that is usually slop but can be legitimate (a debug
  ``print`` in a CLI entrypoint). Fed back to the model as a nudge only.

The split exists because false positives are cheap to tolerate as advice and
expensive as a refused build. The shapes here come from the public
"anti-slop" and "show-me" ideas: reject low-evidence patterns, and name the
specific language shape rather than a vibe.
"""

from __future__ import annotations

import re
from pathlib import Path

# A rule is (name, compiled pattern, message, hard). Patterns are matched
# against the whole file text. Anchored to the start of a line where the
# pattern is a single-line statement, so a comment mentioning the word does
# not fire.
_Rule = tuple[str, re.Pattern, str, bool]


def _line(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.MULTILINE)


# --- universal (every language) -------------------------------------------

_UNIVERSAL: list[_Rule] = [
    # A run of three or more consecutive full-line comments that look like
    # code (they end in a punctuation or assignment) is dead code left behind.
    ("commented-out-code",
     _line(r"(?:^\s*(?:#|//|;).*[=;:{}\[\]()][^\n]*$\n?){3,}"),
     "a block of commented-out code; delete it instead of leaving it", True),
    # More than five TODO/FIXME/HACK markers in one file is debt accumulation.
    ("todo-accumulation",
     re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b"),
     "many TODO/FIXME markers; resolve or track them instead of accumulating",
     False),
    ("dead-branch",
     _line(r"^\s*if\s+(?:False|false|FALSE)\s*:\s*$|^\s*if\s*\(\s*false\s*\)"),
     "a branch that can never run (condition is always false)", True),
]


# --- per-language registry ------------------------------------------------

_LANG: dict[str, list[_Rule]] = {
    ".py": [
        ("bare-except",
         _line(r"^\s*except\s*:\s*$"),
         "a bare `except:` swallows every error; catch the specific exception",
         True),
        ("except-pass",
         _line(r"^\s*except[^:]*:\s*\n\s*pass\b"),
         "an `except` that silently passes; handle it or narrow the catch", True),
        ("percent-format",
         _line(r'"[^"\n]*%[sd]\b[^"\n]*"\s*%'),
         "`%`-style string formatting; use an f-string", True),
        ("debug-print",
         _line(r"^\s*print\("),
         "a debug `print(`; remove it or use the project's logger", False),
    ],
    ".c": [
        ("gets",
         re.compile(r"\bgets\s*\("),
         "`gets` is unsafe (unbounded read); use `fgets`", True),
        ("debug-printf",
         re.compile(r"\bprintf\s*\(|fprintf\s*\(\s*stderr"),
         "a debug `printf`/`fprintf(stderr`; remove it", False),
    ],
    ".h": [
        ("gets",
         re.compile(r"\bgets\s*\("),
         "`gets` is unsafe (unbounded read); use `fgets`", True),
    ],
    ".js": [
        ("console-log",
         re.compile(r"\bconsole\.(?:log|debug|info)\s*\("),
         "a debug `console.log`; remove it", False),
        ("any-type",
         re.compile(r":\s*any\b|<any>"),
         "an explicit `any` defeats the type checker; use a narrower type",
         False),
    ],
    ".ts": [
        ("console-log",
         re.compile(r"\bconsole\.(?:log|debug|info)\s*\("),
         "a debug `console.log`; remove it", False),
        ("any-type",
         re.compile(r":\s*any\b|<any>"),
         "an explicit `any` defeats the type checker; use a narrower type",
         False),
    ],
    ".go": [
        ("debug-print",
         re.compile(r"\b(?:fmt\.Println|fmt\.Print|println)\s*\("),
         "a debug print; remove it", False),
    ],
    ".rs": [
        ("debug-print",
         re.compile(r"\b(?:println!|dbg!)\s*\("),
         "a debug print; remove it", False),
    ],
}


def known_extensions() -> frozenset[str]:
    """The file extensions this module has rules for."""
    return frozenset(_LANG)


def _find(text: str, rules: list[_Rule]) -> list[dict]:
    findings: list[dict] = []
    for name, pattern, message, hard in rules:
        count = len(pattern.findall(text))
        if count:
            findings.append({"rule": name, "message": message,
                             "count": count, "hard": hard})
    return findings


def slop_flags(rel_path: str, text: str) -> list[dict]:
    """Deterministic anti-slop findings for one file. Empty when clean.

    ``rel_path`` selects the language rules by extension; the universal rules
    always run. Returns a list of ``{rule, message, count, hard}`` dicts.
    """
    ext = Path(rel_path).suffix.lower()
    rules = list(_UNIVERSAL) + _LANG.get(ext, [])
    return _find(text, rules)


def hard_flags(rel_path: str, text: str) -> list[dict]:
    """Only the hard findings — the ones that can refuse a new file."""
    return [f for f in slop_flags(rel_path, text) if f["hard"]]

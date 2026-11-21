"""Every documented `python -m stead ...` command must exist."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ctx.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
_MD = list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md")) + \
      list((ROOT / "factories").glob("*/FACTORY.md"))
_CMD = re.compile(r"python -m stead ([a-z]+)(?: ([a-z]+))?")


def _tops() -> dict:
    parser = build_parser()
    return parser._subparsers._group_actions[0].choices


class DocCommandTest(unittest.TestCase):
    def test_every_documented_command_exists(self) -> None:
        tops = _tops()
        for path in _MD:
            text = path.read_text(encoding="utf-8")
            for match in _CMD.finditer(text):
                command = match.group(1)
                self.assertIn(command, tops, f"{path.name}: python -m stead {command}")
                sub = match.group(2)
                if not sub:
                    continue
                subs = tops[command]._subparsers
                if subs is None:
                    continue
                self.assertIn(sub, subs._group_actions[0].choices,
                              f"{path.name}: python -m stead {command} {sub}")

    def test_factory_names_exist(self) -> None:
        names = {p.name for p in (ROOT / "factories").iterdir() if p.is_dir()}
        for path in _MD:
            text = path.read_text(encoding="utf-8")
            for name in re.findall(r"--factory ([a-z0-9-]+)", text):
                self.assertIn(name, names, f"{path.name}: {name}")

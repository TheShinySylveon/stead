"""Scaffold a factory folder. Local files only. Does not call a model."""

from __future__ import annotations

import json
import re
from pathlib import Path

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


class ScaffoldError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def scaffold(root: Path, name: str, title: str) -> Path:
    """Create factories/<name>/ with a definition, v1 prompt, and one eval."""
    name = (name or "").strip()
    title = (title or "").strip()
    if not _NAME.match(name):
        raise ScaffoldError("name must be lowercase letters, numbers, and hyphens")
    if not title or len(title) > 80:
        raise ScaffoldError("title is required and must be at most 80 characters")
    folder = root / "factories" / name
    if folder.exists():
        raise ScaffoldError(f"factory already exists: {name}")
    (folder / "prompts").mkdir(parents=True)
    (folder / "evals").mkdir()
    (folder / "FACTORY.md").write_text(
        f"# FACTORY: {name}\n\n{title}\n\n"
        "Assembly drafts locally. It does not post, push, or merge.\n\n"
        "## Trigger\n\n"
        f"`python -m stead factory run --factory {name} --shadow`\n\n"
        "## Must not\n\n"
        "- Invent facts that are not in the bundle.\n"
        "- Write to GitHub.\n",
        encoding="utf-8",
    )
    (folder / "prompts" / "v1.md").write_text(
        f"# Prompt v1 — {name}\n\n"
        f"Draft from the bundle below the separator. The job is: {title}.\n"
        "Do not invent facts. Do not post, push, or merge.\n",
        encoding="utf-8",
    )
    (folder / "evals" / f"eval-{name}.json").write_text(
        json.dumps({
            "id": f"eval-{name}",
            "factory": name,
            "title": title,
            "input": "A bundle for this factory.",
            "pass_criteria": (
                "The draft stays inside the bundle. It does not invent facts. "
                "It does not post, push, or merge."
            ),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return folder

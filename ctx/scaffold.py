"""Scaffold a factory folder. Local files only. Does not call a model."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ctx import frontmatter

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")

# What a factory's shadow assemble asks for. Persisted in FACTORY.md frontmatter.
INPUTS = ("project", "contribution", "none")


class ScaffoldError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def scaffold(root: Path, name: str, title: str, input_kind: str = "project") -> Path:
    """Create factories/<name>/ with a definition, v1 prompt, and one eval.

    ``input_kind`` (project / contribution / none) is persisted in FACTORY.md
    frontmatter so the cockpit knows what the factory's assemble form asks for."""
    name = (name or "").strip()
    title = (title or "").strip()
    input_kind = (input_kind or "project").strip()
    if not _NAME.match(name):
        raise ScaffoldError("name must be lowercase letters, numbers, and hyphens")
    if not title or len(title) > 80:
        raise ScaffoldError("title is required and must be at most 80 characters")
    if input_kind not in INPUTS:
        raise ScaffoldError(f"input must be one of {', '.join(INPUTS)}")
    folder = root / "factories" / name
    if folder.exists():
        raise ScaffoldError(f"factory already exists: {name}")
    (folder / "prompts").mkdir(parents=True)
    (folder / "evals").mkdir()
    definition = (
        f"# FACTORY: {name}\n\n{title}\n\n"
        "Assembly drafts locally. It does not post, push, or merge.\n\n"
        "## Trigger\n\n"
        f"`python -m stead factory run --factory {name} --shadow`\n\n"
        "## Must not\n\n"
        "- Invent facts that are not in the bundle.\n"
        "- Write to GitHub.\n"
    )
    (folder / "FACTORY.md").write_text(
        frontmatter.dumps({"input": input_kind, "title": title}, definition),
        encoding="utf-8")
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


def factory_meta(root: Path, name: str) -> dict:
    """The frontmatter a factory declares in FACTORY.md (input, title), or {}."""
    path = root / "factories" / name / "FACTORY.md"
    if not path.is_file():
        return {}
    try:
        meta, _body = frontmatter.parse(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return meta


def _shipped_factories() -> set[str]:
    from ctx import factory
    return {factory.DIGEST_FACTORY, factory.MAINTENANCE_FACTORY,
            factory.FEATURE_BUILDER_FACTORY, "weekly-project-status"}


def delete_factory(root: Path, name: str, force: bool = False) -> dict:
    """Remove factories/<name>/. Refuses the four shipped factories and any
    factory with run logs (the audit trail) unless ``force`` is set."""
    name = (name or "").strip()
    if not _NAME.match(name):
        raise ScaffoldError("name must be lowercase letters, numbers, and hyphens")
    folder = root / "factories" / name
    if not folder.is_dir():
        raise ScaffoldError(f"factory not found: {name}")
    if name in _shipped_factories() and not force:
        raise ScaffoldError(
            f"{name} is a shipped factory; pass --force to delete it")
    runs = folder / "runs"
    if runs.is_dir() and any(runs.iterdir()) and not force:
        raise ScaffoldError(
            f"{name} has run logs (the audit trail); pass --force to delete them too")
    shutil.rmtree(folder)
    return {"name": name}

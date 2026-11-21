"""Onboard a project: context project, repo record, and the initial constitution.

Spec Kit (`specify`) is an external tool, like `gh`. This module may run
`specify init` when it is on PATH and a code directory was given. It never
imports specify, and onboarding still succeeds without it (the constitution
is written here either way). No network, no push, no pull request.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from ctx import factory

INTEGRATIONS = ("claude", "copilot", "gemini", "codex", "generic")
DEFAULT_INTEGRATION = "claude"


class OnboardError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def _alloc(root: Path, otype: str, title: str) -> tuple[str, Path]:
    from ctx import objects
    slug = _slugify(title)
    folder = root / "context" / objects.TYPE_DIRS[otype]
    folder.mkdir(parents=True, exist_ok=True)
    object_id, n = f"{otype}-{slug}", 2
    while (folder / f"{object_id.removeprefix(otype + '-')}.md").exists():
        object_id, n = f"{otype}-{slug}-{n}", n + 1
    return object_id, folder / f"{object_id.removeprefix(otype + '-')}.md"


def _https_or_empty(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    if not (url.startswith("https://") or url.startswith("http://localhost")):
        raise OnboardError("url must be an https URL")
    return url


def code_directory(root: Path, raw: str | None) -> Path | None:
    """A project's own directory. Not this context repo, and not a parent of it."""
    if not (raw or "").strip():
        return None
    target = Path(raw).expanduser().resolve()
    if not target.is_dir():
        raise OnboardError(f"code path is not a directory: {target}")
    context = root.resolve()
    if target == context or context in target.parents or target in context.parents:
        raise OnboardError(
            "code path must be the project's own directory, not the context "
            "repo and not a parent of it")
    return target


def specify_argv(integration: str, script: str) -> list[str]:
    return [
        "specify", "init", "--here", "--force", "--non-interactive",
        "--ignore-agent-tools", "--integration", integration, "--script", script,
    ]


def _script_type() -> str:
    return "ps" if sys.platform == "win32" else "sh"


def run_specify(target: Path, integration: str) -> dict:
    """Run specify init in target. Missing binary is a skip, not a failure."""
    command = specify_argv(integration, _script_type())
    exe = shutil.which("specify")
    if exe is None:
        return {"status": "skipped", "command": " ".join(command),
                "detail": "specify is not on PATH. The constitution is in context/. "
                          "Install specify-cli and rerun, or keep method builtin."}
    try:
        proc = subprocess.run(
            [exe, *command[1:]], cwd=target, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "command": " ".join(command),
                "detail": "specify init timed out after 180s. Context objects were still written."}
    detail = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return {"status": "failed", "command": " ".join(command),
                "detail": detail or f"specify init exited {proc.returncode}"}
    return {"status": "ran", "command": " ".join(command),
            "detail": "scaffolded .specify/ in the code directory. No push."}


def _constitution(title: str, kind: str, method: str, today: str, project_id: str,
                  repo_id: str) -> str:
    place = ("This is your repo. Commit `.specify/` if you want the Spec Kit "
             "trail visible in git." if kind == "own" else
             "This is an upstream repo. Keep `.specify/` in the local clone. "
             "Do not commit or push it unless the maintainers ask.")
    return f"""# Constitution — {title}

Planning baseline for this repo. Written by `ctx onboard` on {today}.
Later feature-builder runs check plans against this document before any code.
`method` is `{method}`. Planning-before-code does not depend on that choice.

Project: `{project_id}`. Repo: `{repo_id}`.

## Principles

- Code quality: match the repo's existing style. No drive-by rewrites.
- Testing: a behavior change gets a failing test first, then the fix.
- Maintainability: small diffs, clear names, no unused abstraction.
- Dependencies: the repo's existing tools. Record a reason here before adding one.
- Safety: never push to the default branch. Never auto-merge. A human reviews before anything consequential.

## Where Spec Kit lives

{place}

The first feature still needs its own spec: an issue you author, tagged `feature-spec`, with a `## Acceptance criteria` checklist. Then:

    python3 -m ctx factory run --factory feature-builder --contribution ID --shadow
"""


def _write(path: Path, meta: dict, body: str) -> None:
    from ctx import frontmatter
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body if body.endswith("\n") else body + "\n"
    path.write_text(frontmatter.dumps(meta, text), encoding="utf-8")


def needs_welcome(root: Path) -> bool:
    """True when this checkout has no projects yet. That is a first run."""
    folder = root / "context" / "projects"
    return not folder.is_dir() or not any(folder.glob("*.md"))


def welcome(root: Path, title: str, url: str | None = None) -> dict:
    """First-run setup: one project and its repo record. No Spec Kit, no push."""
    return onboard(root, title, kind="own", url=url, method="builtin",
                   run_specify_init=False)


def onboard(root: Path, title: str, *, kind: str = "own", url: str | None = None,
            code_path: str | None = None, method: str = "spec-kit",
            integration: str = DEFAULT_INTEGRATION, run_specify_init: bool = True,
            specify_runner=None) -> dict:
    """Create the project, the repo record, and the initial constitution.

    Returns a result dict. Raises OnboardError for bad input. A missing or
    failing `specify` does not undo the context objects.
    """
    from ctx import cli, db

    title = (title or "").strip()
    if not title or len(title) > 200:
        raise OnboardError("needs a title of at most 200 characters")
    if kind not in cli.REPO_KINDS:
        raise OnboardError(f"invalid kind {kind!r}")
    if method not in factory.CONTRIB_METHODS:
        raise OnboardError(f"invalid method {method!r}")
    if integration not in INTEGRATIONS:
        raise OnboardError(f"invalid integration {integration!r}; choose from {INTEGRATIONS}")
    url = _https_or_empty(url)
    target = code_directory(root, code_path)
    db.require_db(root)

    today = date.today().isoformat()
    project_id, project_path = _alloc(root, "project", title)
    doc_id, doc_path = _alloc(root, "document", f"{title} constitution")

    slug = cli._repo_slug(title, url)
    n = 2
    while (root / "context" / "repos" / f"{slug}.md").exists():
        slug, n = f"{cli._repo_slug(title, url)}-{n}", n + 1
    repo_id = f"repo-{slug}"
    repo_path = root / "context" / "repos" / f"{slug}.md"

    specify_result = {"status": "builtin", "command": "", "detail":
                      "method is builtin. Constitution is markdown only. specify was not run."}
    if method == "spec-kit":
        if target is None:
            command = " ".join(specify_argv(integration, _script_type()))
            specify_result = {
                "status": "skipped",
                "command": command,
                "detail": "No code path given, so specify init was not run. "
                          "Pass --path when the project directory exists.",
            }
        elif not run_specify_init:
            specify_result = {
                "status": "skipped",
                "command": " ".join(specify_argv(integration, _script_type())),
                "detail": "specify init was skipped by request.",
            }
        else:
            runner = specify_runner or run_specify
            specify_result = runner(target, integration)

    if method == "builtin" and target is not None:
        dest = target / "constitution.md"
        if not dest.exists():
            dest.write_text(_constitution(title, kind, method, today, project_id, repo_id),
                            encoding="utf-8")
            specify_result["detail"] += f" Wrote {dest.name} in the code directory."

    if method == "spec-kit" and target is not None and specify_result["status"] != "ran":
        dest = target / "constitution.md"
        if not dest.exists():
            dest.write_text(_constitution(title, kind, method, today, project_id, repo_id),
                            encoding="utf-8")
            specify_result["detail"] += " Wrote constitution.md in the code directory as a fallback."

    place = ("Own repo: `.specify/` may be committed." if kind == "own" else
             "OSS repo: keep `.specify/` local. Do not push it upstream uninvited.")
    project_body = (
        f"# {title}\n\n"
        f"Onboarded {today}.\n\n"
        f"- Repo: `{repo_id}`\n"
        f"- Constitution: `{doc_id}`\n"
        f"- Method: `{method}`\n"
        f"- Code path: `{target or 'not set'}`\n"
        f"- Spec Kit: {specify_result['status']}. {specify_result['detail']}\n\n"
        f"{place}\n"
    )
    _write(project_path, {
        "id": project_id, "type": "project", "title": title,
        "created": today, "updated": today, "status": "active",
    }, project_body)
    _write(doc_path, {
        "id": doc_id, "type": "document", "title": f"Constitution — {title}",
        "created": today, "updated": today, "project": project_id,
        "tags": ["constitution", method],
        "related": [repo_id],
    }, _constitution(title, kind, method, today, project_id, repo_id))

    notes = (f"Onboarded {today}. Project {project_id}. Constitution {doc_id}. "
             f"Method {method}. {place}")
    repo_meta = {
        "id": repo_id, "type": "repo", "title": title,
        "created": today, "updated": today, "status": "active", "kind": kind,
        "project": project_id, "notes": notes,
    }
    if url:
        repo_meta["url"] = url
    _write(repo_path, repo_meta, f"# {title}\n")
    conn = db.connect(root)
    try:
        db.index_repo(conn, root, repo_path, repo_meta, today)
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "project": project_id,
        "repo": repo_id,
        "constitution": doc_id,
        "method": method,
        "kind": kind,
        "code_path": str(target) if target else None,
        "specify": specify_result["status"],
        "specify_command": specify_result.get("command") or "",
        "specify_detail": specify_result.get("detail") or "",
    }

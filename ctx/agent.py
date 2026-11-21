"""Model-driven build: plan, edit files, run checks, commit, optionally publish.

The model is the only writer of code, through a small JSON protocol. It can
only touch files inside the repo's ``code_path``. It cannot choose a shell
command: the repo's ``checks:`` field is the command Stead runs. Nothing is
pushed unless the caller asks for publish and the repo ceiling allows it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ctx import factory, objects
from ctx.autonomy import AutonomyError, effective, permit

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
               ".specify", "dist", "build", ".next", "target"}
MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 40_000
MAX_STEPS = 24
MAX_TOTAL_EDITS = 1_000_000


class BuildError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def build(root: Path, contribution_ref: str, *, responder=None, runner=None,
          publish: bool = False, merge: bool = False, max_steps: int = MAX_STEPS) -> dict:
    """Plan and implement one authored feature spec. Raises BuildError."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise BuildError(f"contribution not found: {contribution_ref}")
    _path, spec, body = found
    if spec.get("kind") != "issue" or spec.get("role") != "author":
        raise BuildError("build runs from an issue you authored")
    description, criteria = factory.split_spec(body)
    flags = factory.spec_flags(description, criteria)
    if flags:
        raise BuildError("spec is not buildable yet: " + ", ".join(flags))
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise BuildError(f"repo not found: {spec.get('repo')!r}")
    _repo_path, repo_meta, _repo_body = repo
    code = Path(repo_meta.get("code_path") or "")
    if not repo_meta.get("code_path") or not code.is_dir():
        raise BuildError("set the repo code_path to a local checkout before building")
    code = code.resolve()
    policy = effective(root, repo_meta)
    try:
        permit(policy, None)
    except AutonomyError as exc:
        raise BuildError(str(exc)) from exc
    default = (repo_meta.get("default_branch") or "main").strip()
    run = runner or _git_run
    if _git(run, code, ["status", "--porcelain"]).strip():
        raise BuildError("the checkout has uncommitted changes. Commit or stash them first.")
    current = _git(run, code, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if current != default:
        raise BuildError(f"check out {default} before building (now on {current}).")
    branch = _branch_name(spec)
    existing = _git(run, code, ["branch", "--list", branch]).strip()
    if existing:
        raise BuildError(f"branch {branch} already exists. Delete it or pick another spec.")
    if responder is None:
        from ctx import models
        settings = models.resolve(root)
        responder = lambda prompt: models.complete(prompt, settings, timeout=300)
    tree = _tree(code)
    prompt = _system_prompt(spec, criteria, tree)
    transcript: list[str] = []
    plan = ""
    files: dict[str, str] = {}
    actions: list[dict] = []
    edits = 0
    for _step in range(max_steps):
        reply = responder(prompt + "\n\n" + "\n\n".join(transcript))
        action = _parse(reply)
        if action is None:
            transcript.append("Your last reply was not one JSON object. Reply with JSON only.")
            continue
        kind = action.get("action")
        if kind == "list":
            rel = _safe_rel(action.get("path") or ".")
            target = code / rel
            if not target.is_dir():
                transcript.append(f"list: not a directory: {rel}")
                continue
            names = sorted(p.name + ("/" if p.is_dir() else "")
                           for p in target.iterdir() if p.name not in IGNORE_DIRS)
            transcript.append(f"list {rel}:\n" + "\n".join(names[:200]))
            actions.append({"action": "list", "path": rel})
            continue
        if kind == "read":
            rel = _safe_rel(action.get("path") or "")
            target = code / rel
            if not target.is_file() or _ignored(target, code):
                transcript.append(f"read: no readable file at {rel}")
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
            actions.append({"action": "read", "path": rel})
            transcript.append(f"read {rel}:\n{text[:MAX_READ_CHARS]}")
            continue
        if kind == "plan":
            plan = str(action.get("summary") or "").strip()
            if not plan:
                transcript.append("plan: summary is required")
                continue
            actions.append({"action": "plan"})
            transcript.append("Plan recorded. You may now write files.")
            continue
        if kind == "write":
            if not plan:
                raise BuildError("the model tried to write before a plan. Planning comes first.")
            rel = _safe_rel(action.get("path") or "")
            text = action.get("content")
            if not isinstance(text, str):
                transcript.append("write: content must be a string")
                continue
            data = text.encode("utf-8")
            if len(data) > MAX_FILE_BYTES:
                transcript.append(f"write: {rel} is over {MAX_FILE_BYTES} bytes")
                continue
            edits += len(data)
            if edits > MAX_TOTAL_EDITS:
                raise BuildError("the model tried to write too much in one build")
            target = code / rel
            if _ignored(target, code):
                raise BuildError(f"refusing to write an ignored path: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            files[rel] = text
            actions.append({"action": "write", "path": rel})
            transcript.append(f"wrote {rel} ({len(data)} bytes)")
            continue
        if kind == "finish":
            summary = str(action.get("summary") or "").strip()
            if not plan:
                raise BuildError("the model finished without a plan")
            if not files:
                raise BuildError("the model finished without changing a file")
            checks = (repo_meta.get("checks") or "").strip()
            if checks:
                _run_checks(run, code, checks)
            _git(run, code, ["checkout", "-b", branch])
            _git(run, code, ["add", "-A"])
            message = f"{spec.get('title') or spec.get('id')}"
            if spec.get("number"):
                message += f" (#{spec['number']})"
            _git(run, code, ["commit", "-m", message])
            result = {
                "ok": True,
                "branch": branch,
                "files": sorted(files),
                "plan": plan,
                "summary": summary,
                "checks": checks,
                "commit": _git(run, code, ["rev-parse", "HEAD"]).strip(),
                "steps": len(actions),
                "published": False,
                "merged": False,
            }
            if publish:
                from ctx.publish import PublishError, publish as publish_pr
                try:
                    opened = publish_pr(root, contribution_ref)
                except PublishError as exc:
                    raise BuildError(f"committed on {branch}, but publish failed: {exc}") from exc
                result["published"] = True
                result["pr_url"] = opened["url"]
                if merge:
                    from ctx.merge import MergeError, merge as merge_pr
                    try:
                        merged = merge_pr(root, contribution_ref)
                    except MergeError as exc:
                        raise BuildError(
                            f"opened {opened['url']}, but merge failed: {exc}") from exc
                    result["merged"] = bool(merged.get("merged"))
                    result["merged_url"] = merged.get("url") or opened["url"]
            elif merge:
                raise BuildError("--merge needs --publish; nothing was pushed")
            return result
        transcript.append('action must be plan, list, read, write, or finish.')
    raise BuildError(f"the model did not finish within {max_steps} steps")


def _system_prompt(spec: dict, criteria: list[str], tree: str) -> str:
    return (
        "You are implementing one feature spec in a local git checkout.\n"
        "Reply with exactly one JSON object per turn. No prose, no code fences.\n"
        'Actions: {"action":"plan","summary":"..."}, '
        '{"action":"list","path":"."}, {"action":"read","path":"a.py"}, '
        '{"action":"write","path":"a.py","content":"full file text"}, '
        '{"action":"finish","summary":"..."}.\n'
        "First action must be a plan. Do not write before the plan.\n"
        "write replaces the whole file. Read a file before changing it.\n"
        "Stay inside the repository. Do not touch .git.\n"
        "Match the repo's existing style and tests. Finish when the spec is met.\n\n"
        f"Feature: {spec.get('title')}\n"
        "Acceptance criteria:\n" + "\n".join(f"- {item}" for item in criteria) + "\n\n"
        "Repository tree (depth 2):\n" + tree
    )


def _parse(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _safe_rel(raw: str) -> str:
    rel = str(raw or "").strip().replace("\\", "/")
    if not rel or rel in {".", "./"}:
        return "."
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise BuildError(f"absolute paths are not allowed: {raw}")
    parts = [part for part in rel.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise BuildError(f"paths may not leave the repository: {raw}")
    if parts and parts[0] == ".git":
        raise BuildError("the model may not touch .git")
    return "/".join(parts)


def _ignored(path: Path, code: Path) -> bool:
    try:
        relative = path.resolve().relative_to(code)
    except ValueError:
        raise BuildError(f"path leaves the repository: {path}")
    return any(part in IGNORE_DIRS for part in relative.parts)


def _tree(code: Path) -> str:
    lines = []
    for path in sorted(code.rglob("*")):
        if len(lines) >= 200:
            lines.append("... more files ...")
            break
        try:
            relative = path.relative_to(code)
        except ValueError:
            continue
        if any(part in IGNORE_DIRS for part in relative.parts):
            continue
        depth = len(relative.parts)
        if depth > 2:
            continue
        lines.append(relative.as_posix() + ("/" if path.is_dir() else ""))
    return "\n".join(lines)


def branch_for(spec: dict) -> str:
    """The isolated branch a build for this spec uses."""
    return _branch_name(spec)


def _branch_name(spec: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (spec.get("title") or "build").lower()).strip("-")
    slug = slug[:40] or "build"
    number = spec.get("number")
    return f"stead/{number}-{slug}" if number else f"stead/{slug}"


def _run_checks(run, code: Path, checks: str) -> None:
    completed = run(["checks", checks], code, capture=True)
    if completed is not None and completed != 0:
        raise BuildError(f"repo checks failed:\n{completed}")


def _git(run, code: Path, args: list[str]) -> str:
    return run(["git", *args], code)


def _git_run(argv: list[str], cwd: Path, capture: bool = False):
    if argv[:1] == ["checks"]:
        command = argv[1]
        try:
            done = subprocess.run(command, cwd=cwd, shell=True, capture_output=True,
                                  text=True, timeout=900)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BuildError(f"could not run checks: {exc}") from exc
        output = (done.stdout or "") + (done.stderr or "")
        if done.returncode != 0:
            return (output.strip() or f"exit {done.returncode}")[-4000:]
        return 0
    try:
        done = subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BuildError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise BuildError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""

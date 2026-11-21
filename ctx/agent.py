"""Model-driven build: plan, edit, check, commit, optionally publish.

The model is the only writer of code, through a small JSON protocol. It can
only touch files inside the repo's ``code_path``. It cannot choose a shell
command: the repo's ``checks:`` field is the command Stead runs. Failed checks
are fed back so the model can repair them. Nothing is pushed unless the caller
asks for publish and the repo ceiling allows it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from ctx import factory, objects
from ctx.autonomy import AutonomyError, effective, permit

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
               ".specify", "dist", "build", ".next", "target"}
MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 40_000
MAX_STEPS = 30
MAX_TOTAL_EDITS = 1_000_000
LOCK_NAME = ".stead-build.lock"


class BuildError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def build(root: Path, contribution_ref: str, *, responder=None, runner=None,
          publish: bool = False, merge: bool = False, resume: bool = False,
          wait: bool = False, wait_minutes: int = 30,
          repair_rounds: int = 2, max_steps: int = MAX_STEPS) -> dict:
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
    checks = (repo_meta.get("checks") or "").strip()
    default = (repo_meta.get("default_branch") or "main").strip()
    run = runner or _git_run
    branch = branch_for(spec)
    lock = _lock(code)
    try:
        current = _git(run, code, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        if resume:
            if current != branch:
                raise BuildError(f"--resume needs the build branch checked out ({branch}), now on {current}.")
        else:
            if _git(run, code, ["status", "--porcelain"]).strip():
                raise BuildError("the checkout has uncommitted changes. Commit, stash, or use --resume.")
            if current != default:
                raise BuildError(f"check out {default} before building (now on {current}).")
            if _git(run, code, ["branch", "--list", branch]).strip():
                raise BuildError(f"branch {branch} already exists. Use --resume or remove it.")
            _git(run, code, ["checkout", "-b", branch])
        if responder is None:
            from ctx import models
            settings = models.resolve(root)
            responder = lambda prompt: models.complete(prompt, settings, timeout=300)
        tree = _tree(code)
        prompt = _system_prompt(spec, criteria, tree, bool(checks))
        transcript: list[str] = []
        plan = ""
        files: dict[str, str] = {}
        deleted: list[str] = []
        actions: list[dict] = []
        edits = 0
        failures = 0
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
            if kind == "search":
                query = str(action.get("query") or "").strip()
                if len(query) < 2:
                    transcript.append("search: query must be at least two characters")
                    continue
                hits = _search(code, query)
                actions.append({"action": "search", "query": query})
                transcript.append(f"search {query!r}:\n" + ("\n".join(hits) or "no matches"))
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
            if kind == "delete":
                if not plan:
                    raise BuildError("the model tried to delete before a plan.")
                rel = _safe_rel(action.get("path") or "")
                target = code / rel
                if _ignored(target, code) or not target.is_file():
                    transcript.append(f"delete: no file at {rel}")
                    continue
                target.unlink()
                files.pop(rel, None)
                deleted.append(rel)
                actions.append({"action": "delete", "path": rel})
                transcript.append(f"deleted {rel}")
                continue
            if kind == "check":
                if not checks:
                    transcript.append("check: no checks command is configured on this repo")
                    continue
                ok, output = _checks(code, checks)
                actions.append({"action": "check", "ok": ok})
                transcript.append(("checks passed" if ok else "checks failed") + ":\n" +
                                  (output[-4000:] or "(no output)"))
                continue
            if kind == "finish":
                summary = str(action.get("summary") or "").strip()
                if not plan:
                    raise BuildError("the model finished without a plan")
                dirty = _git(run, code, ["status", "--porcelain"]).strip()
                if not files and not deleted and not (resume and dirty):
                    raise BuildError("the model finished without changing a file")
                if checks:
                    ok, output = _checks(code, checks)
                    if not ok:
                        failures += 1
                        if failures > repair_rounds:
                            raise BuildError("checks kept failing after repair attempts:\n" +
                                             (output[-4000:] or "(no output)"))
                        actions.append({"action": "finish", "checks": "fail"})
                        transcript.append(
                            "checks failed. Read the failure, fix it, and finish again:\n" +
                            (output[-4000:] or "(no output)"))
                        continue
                _git(run, code, ["add", "-A"])
                message = f"{spec.get('title') or spec.get('id')}"
                if spec.get("number"):
                    message += f" (#{spec['number']})"
                _git(run, code, ["commit", "-m", message])
                commit = _git(run, code, ["rev-parse", "HEAD"]).strip()
                result = {
                    "ok": True,
                    "branch": branch,
                    "files": sorted(files),
                    "deleted": sorted(deleted),
                    "plan": plan,
                    "summary": summary,
                    "checks": checks,
                    "commit": commit,
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
                    if wait:
                        _wait_for_checks(code, spec.get("number"), wait_minutes)
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
                _record_run(root, spec, result, mode="live" if publish else "shadow")
                return result
            transcript.append(
                'action must be plan, list, read, search, write, delete, check, or finish.')
        raise BuildError(f"the model did not finish within {max_steps} steps")
    finally:
        _unlock(lock)


def _lock(code: Path) -> Path:
    import hashlib
    digest = hashlib.sha1(str(code).encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"stead-build-{digest}.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BuildError(
            f"another build holds the lock for this checkout ({path}). "
            "Remove it if no build is running.") from exc
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return path


def _unlock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _checks(code: Path, command: str) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, cwd=code, shell=True, capture_output=True,
                              text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run checks: {exc}"
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output


def _search(code: Path, query: str) -> list[str]:
    needle = query.lower()
    hits: list[str] = []
    scanned = 0
    for path in sorted(code.rglob("*")):
        if scanned >= 2000 or len(hits) >= 50:
            break
        if not path.is_file() or _ignored(path, code):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{path.relative_to(code).as_posix()}:{number}: {line[:200]}")
                if len(hits) >= 50:
                    break
    return hits


def _wait_for_checks(code: Path, number, minutes: int) -> None:
    if not number:
        return
    deadline = time.time() + max(1, minutes) * 60
    while True:
        try:
            done = subprocess.run(["gh", "pr", "checks", str(number)], cwd=code,
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BuildError(f"could not read PR checks: {exc}") from exc
        if done.returncode == 0:
            return
        if done.returncode not in (8,):
            detail = ((done.stdout or "") + (done.stderr or "")).strip()
            raise BuildError("PR checks are not green:\n" + detail[-4000:])
        if time.time() > deadline:
            raise BuildError("timed out waiting for PR checks")
        time.sleep(15)


def _record_run(root: Path, spec: dict, result: dict, *, mode: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-", (spec.get("title") or "build").lower()).strip("-") or "build"
    folder = root / "factories/feature-builder/runs" / f"{stamp}-build-{slug[:40]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.md").write_text(result.get("plan", "") + "\n", encoding="utf-8")
    (folder / "summary.md").write_text(result.get("summary", "") + "\n", encoding="utf-8")
    (folder / "build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    from ctx import db
    if not db.db_path(root).exists():
        return
    conn = db.connect(root)
    try:
        conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, "
            "bundle_path, output, verdict, created) VALUES "
            "('feature-builder', ?, NULL, 'build', ?, ?, ?, 'pending', ?)",
            (spec.get("id"), mode, folder.relative_to(root).as_posix(),
             result.get("summary") or "", db.utcnow()))
        conn.commit()
    finally:
        conn.close()


def _system_prompt(spec: dict, criteria: list[str], tree: str, has_checks: bool) -> str:
    check_line = ("You may call check at any time to run the repo checks. "
                  if has_checks else "This repo has no checks command. ")
    return (
        "You are implementing one feature spec in a local git checkout.\n"
        "Reply with exactly one JSON object per turn. No prose, no code fences.\n"
        'Actions: {"action":"plan","summary":"..."}, '
        '{"action":"list","path":"."}, {"action":"read","path":"a.py"}, '
        '{"action":"search","query":"name"}, '
        '{"action":"write","path":"a.py","content":"full file text"}, '
        '{"action":"delete","path":"old.py"}, {"action":"check"}, '
        '{"action":"finish","summary":"..."}.\n'
        "First action must be a plan. Do not write before the plan. "
        + check_line +
        "write replaces the whole file. Read a file before changing it. "
        "Stay inside the repository. Do not touch .git. "
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
    return any(part in IGNORE_DIRS or part == LOCK_NAME for part in relative.parts)


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
        if any(part in IGNORE_DIRS or part == LOCK_NAME for part in relative.parts):
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


def _git(run, code: Path, args: list[str]) -> str:
    return run(["git", *args], code)


def _git_run(argv: list[str], cwd: Path, capture: bool = False):
    try:
        done = subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BuildError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise BuildError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""

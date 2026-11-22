"""Model-driven build: plan, edit, check, commit, optionally publish.

The model is the only writer of code, through a small JSON protocol. It can
only touch files inside the repo's ``code_path``. It cannot choose a shell
command: the repo's ``checks:`` field is the command Stead runs, with a
scrubbed environment and optionally inside a container. Failed checks are fed
back so the model can repair them. Nothing is pushed unless the caller asks
for publish and the repo ceiling allows it.

Bounds: a wall-clock deadline (``max_minutes``), a step cap, a total edit cap,
and a stop file checked between steps.

A repo at ``reach: ghost`` gets a plan, spec/doc (markdown) changes, and a
full proposed diff for human approval: zero code applied, no checks run,
no publish or merge. The diff is verified read-only with ``git apply --check``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from ctx import factory, objects, safety
from ctx.autonomy import AutonomyError, effective, permit

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
               ".specify", "dist", "build", ".next", "target"}
MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 40_000
MAX_STEPS = 30
MAX_TOTAL_EDITS = 1_000_000
MAX_MINUTES = 30
STALE_LOCK_SECONDS = 6 * 3600
LOCK_NAME = ".stead-build.lock"


class BuildError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def build(root: Path, contribution_ref: str, *, responder=None, runner=None,
          publish: bool = False, merge: bool = False, resume: bool = False,
          wait: bool = False, wait_minutes: int = 30,
          repair_rounds: int = 2, max_steps: int = MAX_STEPS,
          max_minutes: int = MAX_MINUTES) -> dict:
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
    if safety.stopped(root):
        raise BuildError("Stead is stopped. Remove .stead-stop or run "
                         "`python -m stead factory start`.")
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
        reach = permit(policy, None)
    except AutonomyError as exc:
        raise BuildError(str(exc)) from exc
    ghost = reach == "ghost"
    if ghost and (publish or merge):
        raise BuildError("ghost writes the plan and spec/doc changes only, for "
                         "approval. Publish and merge need a higher reach on the repo.")
    checks = (repo_meta.get("checks") or "").strip()
    default = (repo_meta.get("default_branch") or "main").strip()
    run = runner or _git_run
    branch = branch_for(spec)
    started = time.monotonic()
    deadline = started + max(1, max_minutes) * 60
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
        prompt = _system_prompt(spec, criteria, tree, bool(checks), repo_meta, ghost=ghost)
        transcript: list[str] = []
        plan = ""
        proposed = ""
        diff_applies = False
        diff_note = ""
        files: dict[str, str] = {}
        deleted: list[str] = []
        actions: list[dict] = []
        edits = 0
        failures = 0
        checks_mode = "none" if ghost or not checks else "host"
        for _step in range(max_steps):
            _remain_running(root, deadline)
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
                if safety.secret_by(rel):
                    transcript.append(f"read: {rel} looks like a secret; refused")
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
                transcript.append(
                    "Plan recorded. You may now write spec/doc markdown for approval, and you "
                    "must propose the full diff of the code changes. No code is applied."
                    if ghost else "Plan recorded. You may now write files.")
                continue
            if kind == "diff":
                if not ghost:
                    transcript.append("diff: only ghost mode proposes a diff. Edit the files directly.")
                    continue
                if not plan:
                    raise BuildError("the model proposed a diff before a plan. Planning comes first.")
                text = action.get("content")
                if not isinstance(text, str) or not text.strip():
                    transcript.append("diff: content must be a non-empty unified diff string")
                    continue
                if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                    transcript.append(f"diff: over {MAX_FILE_BYTES} bytes. Split the spec.")
                    continue
                proposed = text if text.endswith("\n") else text + "\n"
                diff_applies, diff_note = _check_diff(run, code, proposed)
                actions.append({"action": "diff", "applies": diff_applies})
                transcript.append("Proposed diff recorded for human review. " + diff_note)
                continue
            if kind == "write":
                if not plan:
                    raise BuildError("the model tried to write before a plan. Planning comes first.")
                rel = _safe_rel(action.get("path") or "")
                if ghost and not _is_doc_path(rel):
                    raise BuildError(
                        f"ghost writes the plan and spec/doc changes only: refusing {rel}. "
                        "Zero code. Only markdown (.md, .markdown, .mdx) may change.")
                text = action.get("content")
                if not isinstance(text, str):
                    transcript.append("write: content must be a string")
                    continue
                protected = safety.protected_by(rel, repo_meta)
                if protected:
                    raise BuildError(
                        f"refusing to write protected path {rel} ({protected}). "
                        "The repo can allow it with allow_test_edits, "
                        "allow_ci_edits, or protected_paths.")
                if safety.secret_by(rel):
                    raise BuildError(f"refusing to write {rel}: it looks like a secret file")
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
                if ghost and not _is_doc_path(rel):
                    raise BuildError(
                        f"ghost writes the plan and spec/doc changes only: refusing to delete {rel}. "
                        "Zero code. Only markdown (.md, .markdown, .mdx) may change.")
                target = code / rel
                if _ignored(target, code) or not target.is_file():
                    transcript.append(f"delete: no file at {rel}")
                    continue
                reason = safety.protected_by(rel, repo_meta)
                if reason:
                    raise BuildError(
                        f"refusing to delete protected path {rel} ({reason}). "
                        "The repo can allow it with allow_test_edits, "
                        "allow_ci_edits, or protected_paths.")
                if safety.secret_by(rel):
                    raise BuildError(f"refusing to delete {rel}: it looks like a secret file")
                target.unlink()
                files.pop(rel, None)
                deleted.append(rel)
                actions.append({"action": "delete", "path": rel})
                transcript.append(f"deleted {rel}")
                continue
            if kind == "check":
                if ghost:
                    transcript.append("check: ghost runs no checks. Propose the diff for review instead.")
                    continue
                if not checks:
                    transcript.append("check: no checks command is configured on this repo")
                    continue
                ok, output, checks_mode = _run_checks(code, checks, repo_meta, deadline)
                actions.append({"action": "check", "ok": ok})
                transcript.append(("checks passed" if ok else "checks failed") + ":\n" +
                                  (output[-4000:] or "(no output)"))
                continue
            if kind == "finish":
                summary = str(action.get("summary") or "").strip()
                if not plan:
                    raise BuildError("the model finished without a plan")
                dirty = _git(run, code, ["status", "--porcelain"]).strip()
                changed = bool(files or deleted or (resume and dirty))
                if not changed and not ghost:
                    raise BuildError("the model finished without changing a file")
                if ghost:
                    if not proposed:
                        raise BuildError(
                            "ghost finished without a proposed diff. Produce the full diff "
                            "of the code changes for review before finishing.")
                    if not diff_applies:
                        failures += 1
                        if failures > repair_rounds:
                            raise BuildError("the proposed diff never applied cleanly:\n" +
                                             diff_note[-4000:])
                        actions.append({"action": "finish", "diff": "fail"})
                        transcript.append(
                            "The proposed diff does not apply cleanly to the checkout. "
                            "Fix it and finish again:\n" + diff_note[-4000:])
                        continue
                if checks and not ghost:
                    ok, output, checks_mode = _run_checks(code, checks, repo_meta, deadline)
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
                commit = ""
                if changed:
                    _git(run, code, ["add", "-A"])
                    message = f"{spec.get('title') or spec.get('id')}"
                    if spec.get("number"):
                        message += f" (#{spec['number']})"
                    _git(run, code, ["commit", "-m", message])
                    commit = _git(run, code, ["rev-parse", "HEAD"]).strip()
                touched = sorted(files) + sorted(deleted)
                result = {
                    "ok": True,
                    "reach": reach,
                    "branch": branch,
                    "files": sorted(files),
                    "deleted": sorted(deleted),
                    "plan": plan,
                    "summary": summary,
                    "diff": proposed,
                    "diff_applies": diff_applies,
                    "checks": checks,
                    "checks_mode": checks_mode,
                    "tests_touched": [path for path in touched if safety.is_test_path(path)],
                    "ci_touched": [path for path in touched if safety.is_ci_path(path)],
                    "commit": commit,
                    "steps": len(actions),
                    "elapsed_seconds": round(time.monotonic() - started, 1),
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
                'action must be plan, list, read, search, diff, write, delete, check, or finish.')
        raise BuildError(f"the model did not finish within {max_steps} steps")
    finally:
        _unlock(lock)


def lock_path(code: Path) -> Path:
    digest = hashlib.sha1(str(code).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"stead-build-{digest}.lock"


def _lock(code: Path) -> Path:
    """Take the per-checkout lock. Reclaims it when the owner is gone."""
    path = lock_path(code)
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            if attempt == 0 and _reclaimable(path):
                _unlock(path)
                continue
            raise BuildError(
                f"another build holds the lock for this checkout ({path}). "
                "Remove it if no build is running.") from exc
        os.write(fd, json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": datetime.now(timezone.utc).isoformat(),
        }).encode("utf-8"))
        os.close(fd)
        return path
    raise BuildError(f"could not take the build lock ({path})")


def _reclaimable(path: Path) -> bool:
    """A lock is stale when its process is gone, or it is hours old."""
    try:
        age = time.time() - path.stat().st_mtime
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return True
    if age > STALE_LOCK_SECONDS:
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            pid = int(raw)
        except ValueError:
            return True
        data = {"pid": pid, "host": socket.gethostname()}
    if not isinstance(data, dict):
        return True
    if str(data.get("host") or "") != socket.gethostname():
        return False
    try:
        pid = int(data.get("pid"))
    except (TypeError, ValueError):
        return True
    return not _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _unlock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _remain_running(root: Path, deadline: float) -> None:
    if safety.stopped(root):
        raise BuildError("stopped by .stead-stop. Remove it, or run "
                         "`python -m stead factory start`.")
    if time.monotonic() > deadline:
        raise BuildError("the build hit its time budget. Raise --max-minutes, "
                         "or split the spec.")


def _run_checks(code: Path, command: str, repo_meta: dict,
                deadline: float) -> tuple[bool, str, str]:
    remaining = int(max(30, deadline - time.monotonic()))
    try:
        return safety.run_checks(code, command, repo_meta, timeout=remaining)
    except safety.SafetyError as exc:
        raise BuildError(str(exc)) from exc


def _check_diff(run, code: Path, diff_text: str) -> tuple[bool, str]:
    """Read-only validation of a ghost proposal: git apply --check never edits."""
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(diff_text)
        patch = Path(handle.name)
    try:
        run(["git", "apply", "--check", "--recount", str(patch)], code)
        return True, "It applies cleanly to the checkout (verified with git apply --check)."
    except BuildError as exc:
        return False, f"git apply --check refused it:\n{exc}"
    finally:
        patch.unlink(missing_ok=True)


def _search(code: Path, query: str) -> list[str]:
    needle = query.lower()
    hits: list[str] = []
    scanned = 0
    for path in sorted(code.rglob("*")):
        if scanned >= 2000 or len(hits) >= 50:
            break
        if not path.is_file() or _ignored(path, code):
            continue
        if safety.secret_by(path.relative_to(code).as_posix()):
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
    if result.get("diff"):
        (folder / "proposed.diff").write_text(result["diff"], encoding="utf-8")
    result["run_dir"] = folder.relative_to(root).as_posix()
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


def _system_prompt(spec: dict, criteria: list[str], tree: str, has_checks: bool,
                   repo_meta: dict, *, ghost: bool = False) -> str:
    if ghost:
        check_line = "No checks run in ghost mode. "
    else:
        check_line = ("You may call check at any time to run the repo checks. "
                      if has_checks else "This repo has no checks command. ")
        if str(repo_meta.get("checks_isolation") or "").strip().lower() == "docker":
            check_line += "Checks run in a container with no network. "
        else:
            check_line += "Checks run on the host with a scrubbed environment. "
    intro = (
        "You are planning one feature spec in a local git checkout.\n"
        "Mode GHOST (binding): deliver the plan, spec/doc changes, and a FULL\n"
        "proposed diff for human review. ZERO code is applied: you may write or\n"
        "delete markdown files (.md, .markdown, .mdx) only; every code change\n"
        "goes in the diff action instead. Code snippets in the plan are fine.\n"
        "Nothing is pushed. A human approves the diff before any code lands\n"
        "or a pull request is opened.\n"
        if ghost else
        "You are implementing one feature spec in a local git checkout.\n"
    )
    diff_action = ('{"action":"diff","content":"unified diff of ALL proposed code changes"}, '
                   if ghost else "")
    diff_rule = (
        "The diff must be a complete unified diff that applies cleanly to this "
        "checkout (it is verified with git apply --check). Include every code "
        "change the spec needs; do not include markdown you wrote directly. "
        if ghost else ""
    )
    return (
        intro +
        "Reply with exactly one JSON object per turn. No prose, no code fences.\n"
        'Actions: {"action":"plan","summary":"..."}, '
        '{"action":"list","path":"."}, {"action":"read","path":"a.py"}, '
        '{"action":"search","query":"name"}, '
        + diff_action +
        '{"action":"write","path":"a.py","content":"full file text"}, '
        '{"action":"delete","path":"old.py"}, {"action":"check"}, '
        '{"action":"finish","summary":"..."}.\n'
        "First action must be a plan. Do not write before the plan. "
        + check_line + diff_rule +
        "write replaces the whole file. Read a file before changing it. "
        "Stay inside the repository. Do not touch .git. "
        "Do not edit tests, CI config, or the checks definition: those paths "
        "are protected, and an attempt fails the build. "
        "Match the repo's existing style and tests. Finish when the spec is met.\n\n"
        f"Feature: {spec.get('title')}\n"
        "Acceptance criteria:\n"
        + "\n".join(f"- {text}" for _done, text in criteria) + "\n\n"
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


def _is_doc_path(rel: str) -> bool:
    """Ghost may only touch plan/spec/doc markdown. Everything else is code."""
    return Path(rel).suffix.lower() in {".md", ".markdown", ".mdx"}


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
        if safety.secret_by(relative.as_posix()):
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

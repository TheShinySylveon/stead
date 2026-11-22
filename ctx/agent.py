"""Model-driven build: plan, edit, check, commit, optionally publish.

The model is the only writer of code, through a small JSON protocol. It can
only touch files inside the repo's ``code_path``. It cannot choose a shell
command: the repo's ``checks:`` field is the command Stead runs, with a
scrubbed environment and optionally inside a container. Failed checks are fed
back so the model can repair them. Nothing is pushed unless the caller asks
for publish and the repo ceiling allows it.

Bounds: a wall-clock deadline (``max_minutes``), a step cap, a total edit cap,
and a stop file checked between steps.

A repo at ``reach: ghost`` is purely spec, docs, and a code plan for human
approval: the plan plus markdown spec/doc changes only. Zero code applied,
no checks run, no publish or merge. Code snippets may live in the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from ctx import factory, objects, safety
from ctx.autonomy import (AutonomyError, effective, factory_defaults, permit)

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
               ".specify", "dist", "build", ".next", "target"}
MAX_FILE_BYTES = 200_000
MAX_READ_CHARS = 40_000
MAX_PROMPT_CHARS = 120_000
MAX_STEPS = 30
MAX_TOTAL_EDITS = 1_000_000
MAX_MINUTES = 30
STALE_LOCK_SECONDS = 6 * 3600
LOCK_NAME = ".stead-build.lock"

# Structured output for the model call: pin the reply to one action object.
# JSON-schema form (not `json_object`): LM Studio enforces `json_schema`/`text`,
# and json_object only guarantees valid JSON, not one action of the right shape.
# Every field the build loop reads must be declared below — llama.cpp's JSON-schema
# converter defaults `additionalProperties` to false, so an undeclared field is
# silently dropped and the action loses its path/content.
_ACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "build_action",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": [
                    "plan", "list", "read", "search", "write", "delete",
                    "check", "propose", "finish"]},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "summary": {"type": "string"},
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "title": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

# The fields the build loop reads from an action object. A test asserts each is
# declared in the schema above, so a strict server never drops one.
_ACTION_FIELDS = {"action", "path", "content", "summary", "query", "kind", "title", "text"}


class BuildError(Exception):
    """A build failure, tagged with a reason code for the record.

    Reasons: precondition (nothing was built), infrastructure (the model could
    not be reached), protocol (the model broke the action protocol), gate
    (protected path), checks, budget, tamper (checks changed things), build.
    """

    def __init__(self, message: str, reason: str = "build"):
        super().__init__(message)
        self.reason = reason


def build(root: Path, contribution_ref: str, *, responder=None, runner=None,
          publish: bool = False, merge: bool = False, resume: bool = False,
          retry: bool = False, wait: bool = False, wait_minutes: int = 30,
          repair_rounds: int = 2, max_steps: int = MAX_STEPS,
          max_minutes: int = MAX_MINUTES,
          max_tokens: int | None = None,
          max_cost: float | None = None) -> dict:
    """Plan and implement one authored feature spec. Raises BuildError.

    A spec gets one automatic build attempt per approved content hash: a
    build-class failure blocks a re-run until the body is re-approved (a new
    hash) or ``retry=True``. Infrastructure failures don't consume the attempt."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise BuildError(f"contribution not found: {contribution_ref}",
                         reason="precondition")
    _path, spec, body = found
    if spec.get("kind") != "issue" or not factory.enabled(spec):
        raise BuildError("build runs from an enabled issue (stead-build label "
                         "or feature-spec tag)", reason="precondition")
    # A draft is enabled by its own tag, but its source issue is the real
    # opt-in: once the source is closed or no longer labelled, it stops being a
    # build target even though the draft was already approved.
    source_ref = spec.get("drafted_from")
    if source_ref:
        source = objects.find(root, "contribution", str(source_ref))
        if source is not None:
            _src_meta = source[1]
            if str(_src_meta.get("state") or "open") != "open":
                raise BuildError(
                    "the source issue is closed; it is no longer a build target",
                    reason="precondition")
            _src_tags = {str(t).lower() for t in (_src_meta.get("tags") or [])}
            if factory.BUILD_LABEL not in _src_tags:
                raise BuildError(
                    "the source issue no longer carries the stead-build label",
                    reason="precondition")
    description, criteria = factory.split_spec(body)
    flags = factory.spec_flags(description, criteria)
    if flags:
        raise BuildError("spec is not buildable yet: " + ", ".join(flags),
                         reason="precondition")
    from ctx import spec as spec_approval
    try:
        spec_approval.require_approval(spec, body)
    except spec_approval.SpecError as exc:
        raise BuildError(str(exc), reason="precondition") from exc
    if safety.stopped(root):
        raise BuildError("Stead is stopped. Remove .stead-stop or run "
                         "`python -m stead factory start`.", reason="precondition")
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise BuildError(f"repo not found: {spec.get('repo')!r}",
                         reason="precondition")
    _repo_path, repo_meta, repo_body = repo
    code = Path(repo_meta.get("code_path") or "")
    if not repo_meta.get("code_path") or not code.is_dir():
        raise BuildError("set the repo code_path to a local checkout before building",
                         reason="precondition")
    code = code.resolve()
    anchor = code  # the user's checkout: lock + worktree lifecycle
    policy = effective(root, repo_meta)
    defaults = factory_defaults(root)
    try:
        token_budget = (max_tokens if max_tokens is not None
                        else int(repo_meta.get("max_tokens")
                                 or defaults["max_tokens_per_build"]))
        cost_budget = (max_cost if max_cost is not None
                       else float(repo_meta.get("max_cost_usd")
                                  or defaults["max_cost_per_build_usd"]))
    except (TypeError, ValueError) as exc:
        raise BuildError(
            "max_tokens and max_cost_usd must be numbers (repo frontmatter)",
            reason="precondition") from exc
    try:
        reach = permit(policy, None)
    except AutonomyError as exc:
        raise BuildError(str(exc), reason="precondition") from exc
    ghost = reach == "ghost"
    if ghost and (publish or merge):
        raise BuildError("ghost writes the plan and spec/doc changes only, for "
                         "approval. Publish and merge need a higher reach on the repo.",
                         reason="precondition")
    checks = (repo_meta.get("checks") or "").strip()
    default = (repo_meta.get("default_branch") or "main").strip()
    base_run = runner or _git_run
    branch = branch_for(spec)
    # M0.6: one automatic attempt per approved content hash. A build-class
    # failure blocks a re-run until re-approval (a new hash) or --retry. This
    # is a validation refusal, so it sits before the lock and writes no record.
    if not resume and not retry:
        from ctx import spec as spec_approval_mod
        from ctx import writeback as writeback_mod
        attempts = writeback_mod.build_failure_attempts(
            root, str(repo_meta.get("id") or ""),
            spec_approval_mod.body_hash(body))
        if attempts:
            raise BuildError(
                "this spec already had a failed build attempt for its approved "
                "content. Re-approve the spec (changing its body) to start over, "
                "or pass --retry to try the same content again.", reason="precondition")
    started = time.monotonic()
    deadline = started + max(1, max_minutes) * 60
    lock = _lock(anchor)
    # Every git call Stead makes runs with the checkout's hooks and fsmonitor
    # disabled: checks execute model-written code that could plant either.
    hooks_dir = Path(tempfile.mkdtemp(prefix="stead-no-hooks-"))

    def run(argv, cwd):
        return base_run(safety.disable_hooks(argv, hooks_dir), cwd)

    # A killed build leaves a "started" marker AND a registered worktree;
    # reclaim both (as an infrastructure failure record) so the spec is not
    # stuck on the branch the dead process left checked out.
    _reclaim_stale_started(run, anchor, root, spec, body)

    replies: list[str] = []
    transcript: list[str] = []
    actions: list[dict] = []
    git_before: dict = {}
    initial_dirty: set[str] = set()
    on_branch = False
    wt: Path | None = None
    plan = ""
    files: dict[str, str] = {}
    deleted: list[str] = []
    checks_mode = "none"
    chars_sent = 0
    chars_received = 0
    latency_ms = 0
    step_logs: list[dict] = []
    commit_base = ""
    base_tracked_cf: set[str] = set()
    branch_tracked: set[str] = set()
    try:
        # Every build runs in its own git worktree, so the user's checkout is
        # never touched: no "must be on default", no "must be clean", and no
        # `git clean`. The branch lives in the shared repo; the worktree is
        # discarded when the build ends.
        if resume:
            if not _git(run, anchor, ["branch", "--list", branch]).strip():
                raise BuildError(
                    f"--resume needs the build branch ({branch}); it does not exist.",
                    reason="precondition")
            wt = Path(tempfile.mkdtemp(prefix="stead-wt-"))
            _git(run, anchor, ["worktree", "add", str(wt), branch])
        else:
            if _git(run, anchor, ["branch", "--list", branch]).strip():
                # A failed attempt left its branch behind. A fresh attempt
                # (--retry or a re-approved hash) moves it aside and starts clean.
                from ctx import writeback
                rec = writeback.record_for_branch(
                    root, str(repo_meta.get("id") or ""), branch)
                if rec is not None and str(rec.get("outcome") or "") == "failed":
                    retired = _retired_branch(run, anchor, branch)
                    _git(run, anchor, ["branch", "-m", branch, retired])
                else:
                    raise BuildError(
                        f"branch {branch} already exists. Use --resume or remove it.",
                        reason="precondition")
            wt = Path(tempfile.mkdtemp(prefix="stead-wt-"))
            _git(run, anchor, ["worktree", "add", "-b", branch, str(wt), default])
        code = wt
        on_branch = True
        _write_started(root, spec, body, worktree=str(wt))
        # Where this run starts, what the default branch tracks, and what the
        # branch already tracks (for --resume). The commit guard uses these:
        # HEAD must still be commit_base, and the committed range must be the
        # model's own write set.
        commit_base = _git(run, code, ["rev-parse", "HEAD"]).strip()
        base_tracked_cf = {line.casefold() for line in
                           _git(run, code, ["ls-tree", "-r", "--name-only", default]).splitlines()
                           if line}
        branch_tracked = _tracked_files(run, code)
        git_before = safety.git_state_snapshot(code)
        require_tests = safety.truthy(repo_meta.get("require_tests", "true"))
        if checks and not ghost and require_tests:
            # (a) The base alone must pass before the model runs: a pre-existing
            # red suite cannot satisfy "fails before", and it is a harness
            # problem, not the model's.
            ok, _output, _mode = _run_checks(code, checks, repo_meta, deadline)
            if not ok:
                raise BuildError(
                    "the base suite is red before the model ran. Fix the repo's "
                    "checks so the fail-before/pass-after gate can run.",
                    reason="infrastructure")
        custom_responder = responder is not None
        usage = {"prompt_tokens": 0, "completion_tokens": 0,
                 "estimated": custom_responder}
        try:
            prices = (float(repo_meta.get("input_price_per_mtok") or 0),
                      float(repo_meta.get("output_price_per_mtok") or 0))
        except (TypeError, ValueError) as exc:
            raise BuildError(
                "input_price_per_mtok and output_price_per_mtok must be numbers "
                "(repo frontmatter)", reason="precondition") from exc
        if responder is None:
            from ctx import models
            settings = models.resolve(root)

            def responder(prompt):
                if responder._plain:
                    return models.complete(prompt, settings, timeout=300,
                                           usage=usage)
                try:
                    return models.complete(prompt, settings, timeout=300,
                                           usage=usage,
                                           response_format=_ACTION_RESPONSE_FORMAT)
                except models.ModelError as exc:
                    # A server that does not support structured output rejects
                    # it with a 400 naming `response_format`. Retry once without
                    # it and remember to skip it for the rest of the build.
                    if "response_format" in str(exc):
                        responder._plain = True
                        return models.complete(prompt, settings, timeout=300,
                                               usage=usage)
                    raise

            responder._plain = False
            prices = (settings.get("input_price_per_mtok") or 0.0,
                      settings.get("output_price_per_mtok") or 0.0)
        tree = _tree(code)
        context = factory.feature_build_context(root, spec, body, repo_meta, repo_body)
        prompt = _system_prompt(spec, criteria, tree, bool(checks), repo_meta,
                                ghost=ghost, context=context)
        edits = 0
        failures = 0
        no_test = 0
        progress_nudged = False
        checks_mode = "none" if ghost or not checks else "host"
        for _step in range(max_steps):
            _remain_running(root, deadline)
            if plan and not files and not deleted and _step >= 5 and not progress_nudged:
                transcript.append(
                    "You have a plan but have not written any file yet. Stop reading "
                    "and planning. Write the full new content of the file you are "
                    "changing now, then run check, then finish.")
                progress_nudged = True
            full_prompt = prompt + "\n\n" + "\n\n".join(_fit_budget(prompt, transcript))
            chars_sent += len(full_prompt)
            _step_start = time.monotonic()
            reply = responder(full_prompt)
            _step_latency = round((time.monotonic() - _step_start) * 1000)
            latency_ms += _step_latency
            chars_received += len(reply) if isinstance(reply, str) else len(str(reply))
            step_logs.append({
                "prompt_chars": len(full_prompt),
                "reply_chars": len(reply) if isinstance(reply, str) else len(str(reply)),
                "latency_ms": _step_latency,
            })
            replies.append(reply if isinstance(reply, str) else str(reply))
            if custom_responder:
                usage["prompt_tokens"] += max(1, len(full_prompt) // 4)
                usage["completion_tokens"] += max(1, len(replies[-1]) // 4)
            tokens_total = usage["prompt_tokens"] + usage["completion_tokens"]
            if token_budget and tokens_total > token_budget:
                raise BuildError(
                    f"the build hit its token budget ({tokens_total} > {token_budget}). "
                    "Raise --max-tokens, or split the spec.")
            if cost_budget and (prices[0] or prices[1]):
                spent = (usage["prompt_tokens"] / 1e6 * prices[0]
                         + usage["completion_tokens"] / 1e6 * prices[1])
                if spent > cost_budget:
                    raise BuildError(
                        f"the build hit its cost budget (${spent:.2f} > ${cost_budget:.2f}). "
                        "Raise --max-cost, or split the spec.")
            action = _parse(reply)
            if action is None:
                transcript.append("Your last reply was not one JSON object. Reply with JSON only.")
                continue
            kind = action.get("action")
            if kind is None and isinstance(action.get("actions"), list):
                transcript.append(
                    'Send exactly one action object per reply, not an {"actions": [...]} '
                    "array. Pick the single next action and send it alone.")
                continue
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
                if safety.secret_by(rel) or safety.secret_by(_resolved_rel(target, code)):
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
                summary = str(action.get("summary") or "").strip()
                if not summary:
                    transcript.append("plan: summary is required")
                    continue
                if plan:
                    transcript.append(
                        "A plan is already recorded. Do not send plan again. Now act: "
                        "read the file you will change, write its full new content, run "
                        "check, then finish. Send one action per reply.")
                    continue
                plan = summary
                actions.append({"action": "plan"})
                transcript.append(
                    "Plan recorded. You may now write spec/doc markdown for approval. No code."
                    if ghost else
                    "Plan recorded. Do not plan again. Next: read the target file, write "
                    "its full new content, run check, then finish. One action per reply.")
                continue
            if kind == "write":
                if not plan:
                    raise BuildError("the model tried to write before a plan. Planning comes first.",
                                     reason="protocol")
                rel = _safe_rel(action.get("path") or "")
                if ghost and not _is_doc_path(rel):
                    raise BuildError(
                        f"ghost writes the plan and spec/doc changes only: refusing {rel}. "
                        "Zero code. Only markdown (.md, .markdown, .mdx) may change.",
                        reason="gate")
                text = action.get("content")
                if not isinstance(text, str):
                    transcript.append("write: content must be a string")
                    continue
                target = code / rel
                resolved_rel = _resolved_rel(target, code)
                protected = safety.protected_by(rel, repo_meta)
                if protected is None and resolved_rel != rel:
                    protected = safety.protected_by(resolved_rel, repo_meta)
                # A build may add a test, then revise or delete what it created
                # (write-test, see-it-fail, fix-it). Editing a test that
                # existed at the base commit stays refused. A case variant that
                # would collide with a tracked path on macOS/Windows is refused
                # everywhere, so Linux does not create it either.
                not_in_base = rel.casefold() not in base_tracked_cf
                allowed_test = (protected in safety.TEST_GLOBS
                                and not_in_base
                                and (not target.exists()
                                     or rel in files or rel in branch_tracked)
                                and safety.test_addition_allowed(rel, repo_meta)
                                and safety.test_addition_allowed(resolved_rel, repo_meta))
                if protected and not allowed_test:
                    raise BuildError(
                        f"refusing to write protected path {rel} ({protected}). "
                        "The repo can allow it with allow_test_edits, "
                        "allow_ci_edits, or protected_paths.", reason="gate")
                if safety.secret_by(rel) or safety.secret_by(resolved_rel):
                    raise BuildError(f"refusing to write {rel}: it looks like a secret file",
                                     reason="gate")
                data = text.encode("utf-8")
                if len(data) > MAX_FILE_BYTES:
                    transcript.append(f"write: {rel} is over {MAX_FILE_BYTES} bytes")
                    continue
                edits += len(data)
                if edits > MAX_TOTAL_EDITS:
                    raise BuildError("the model tried to write too much in one build",
                                     reason="budget")
                if _ignored(target, code):
                    raise BuildError(f"refusing to write an ignored path: {rel}",
                                     reason="gate")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                files[rel] = text
                actions.append({"action": "write", "path": rel})
                transcript.append(f"wrote {rel} ({len(data)} bytes)")
                continue
            if kind == "delete":
                if not plan:
                    raise BuildError("the model tried to delete before a plan.",
                                     reason="protocol")
                rel = _safe_rel(action.get("path") or "")
                if ghost and not _is_doc_path(rel):
                    raise BuildError(
                        f"ghost writes the plan and spec/doc changes only: refusing to delete {rel}. "
                        "Zero code. Only markdown (.md, .markdown, .mdx) may change.",
                        reason="gate")
                target = code / rel
                if _ignored(target, code) or not target.is_file():
                    transcript.append(f"delete: no file at {rel}")
                    continue
                resolved_rel = _resolved_rel(target, code)
                reason = safety.protected_by(rel, repo_meta)
                if reason is None and resolved_rel != rel:
                    reason = safety.protected_by(resolved_rel, repo_meta)
                if reason:
                    owned = (reason in safety.TEST_GLOBS
                             and rel.casefold() not in base_tracked_cf
                             and (rel in files or rel in branch_tracked))
                    if not owned:
                        raise BuildError(
                            f"refusing to delete protected path {rel} ({reason}). "
                            "The repo can allow it with allow_test_edits, "
                            "allow_ci_edits, or protected_paths.", reason="gate")
                if safety.secret_by(rel) or safety.secret_by(resolved_rel):
                    raise BuildError(f"refusing to delete {rel}: it looks like a secret file",
                                     reason="gate")
                target.unlink()
                files.pop(rel, None)
                deleted.append(rel)
                actions.append({"action": "delete", "path": rel})
                transcript.append(f"deleted {rel}")
                continue
            if kind == "check":
                if ghost:
                    transcript.append("check: ghost runs no checks. It writes the plan and docs only.")
                    continue
                if not checks:
                    transcript.append("check: no checks command is configured on this repo")
                    continue
                ok, output, checks_mode = _run_checks(code, checks, repo_meta, deadline)
                actions.append({"action": "check", "ok": ok})
                transcript.append(("checks passed" if ok else "checks failed") + ":\n" +
                                  (output[-4000:] or "(no output)"))
                continue
            if kind == "propose":
                if not plan:
                    raise BuildError("the model proposed a note before a plan.",
                                     reason="protocol")
                from ctx import writeback
                try:
                    note = writeback.propose_note(
                        root, str(action.get("kind") or "decision"),
                        str(action.get("title") or ""), str(action.get("text") or ""),
                        source=str(spec.get("id") or ""))
                except writeback.WritebackError as exc:
                    transcript.append(f"propose: {exc}")
                    continue
                actions.append({"action": "propose", "kind": note["kind"]})
                transcript.append(f"proposed {note['kind']} to inbox: {note['title']}")
                continue
            if kind == "finish":
                summary = str(action.get("summary") or "").strip()
                if not plan:
                    raise BuildError("the model finished without a plan",
                                     reason="protocol")
                dirty = _dirty_paths(run, code)
                changed = bool(files or deleted or (resume and dirty))
                if not changed and not ghost:
                    raise BuildError("the model finished without changing a file",
                                     reason="protocol")
                if criteria and not ghost and safety.truthy(repo_meta.get("require_tests", "true")):
                    touched_tests = [p for p in list(files) + deleted
                                     if safety.is_test_path(p)]
                    if not touched_tests:
                        no_test += 1
                        if no_test > repair_rounds:
                            raise BuildError(
                                "the spec has acceptance criteria but no test was added. "
                                "A build must add a test that fails without the change and "
                                "passes with it.", reason="gate")
                        transcript.append(
                            "The spec has acceptance criteria, but you changed no test. "
                            "Add a brand-new test under tests/ that fails without your "
                            "change and passes with it, using the real file paths shown "
                            "in the repository tree — not an invented path. Then run "
                            "check and finish again. Do not finish yet.")
                        continue
                if checks and not ghost:
                    # (b) Fail-before: the new test must fail against the base
                    # (without the model's code change). A test that passes
                    # anyway proves nothing, so feed it back like a missing test
                    # and fail only when the repair rounds run out.
                    if require_tests and criteria:
                        new_tests = [p for p in list(files)
                                     if safety.is_test_path(p)
                                     and p.casefold() not in base_tracked_cf]
                        if new_tests and not _require_fail_before(
                                run, anchor, code, default, new_tests, files,
                                checks, repo_meta, deadline):
                            no_test += 1
                            if no_test > repair_rounds:
                                raise BuildError(
                                    "the new test passes without the code change. "
                                    "A test that does not fail before the change "
                                    "proves nothing: write one that fails without "
                                    "the change and passes with it.", reason="gate")
                            transcript.append(
                                "The new test passes without the code change. It "
                                "does not actually exercise the change, so it "
                                "proves nothing. Rewrite it so it fails without "
                                "your change and passes with it, then run check "
                                "and finish again. Do not finish yet.")
                            continue
                    ok, output, checks_mode = _run_checks(code, checks, repo_meta, deadline)
                    if not ok:
                        failures += 1
                        if failures > repair_rounds:
                            raise BuildError("checks kept failing after repair attempts:\n" +
                                             (output[-4000:] or "(no output)"),
                                             reason="checks")
                        actions.append({"action": "finish", "checks": "fail"})
                        transcript.append(
                            "checks failed. Read the failure, fix it, and finish again:\n" +
                            (output[-4000:] or "(no output)"))
                        continue
                commit = ""
                changed_actual: list[str] = []
                deleted_actual: list[str] = []
                leftovers: list[str] = []
                if changed:
                    expected = set(files) | set(deleted) | initial_dirty
                    # Checks execute model-written code. They must not commit
                    # for themselves or move HEAD: the branch must still be
                    # where Stead left it, so the committed range is the
                    # model's own writes and nothing else.
                    if _git(run, code, ["rev-parse", "HEAD"]).strip() != commit_base:
                        raise BuildError(
                            "the branch HEAD moved during the build (checks may "
                            "have committed). Refusing to commit on top.",
                            reason="tamper")
                    fatal, leftovers = _side_effects(run, code, expected, repo_meta)
                    if fatal:
                        bad = [p for p in fatal
                               if safety.protected_by(p, repo_meta) or safety.secret_by(p)]
                        if bad:
                            raise BuildError(
                                "checks changed protected or secret paths: "
                                + ", ".join(sorted(bad))
                                + ". The repo did not allow this. Refusing to commit.",
                                reason="tamper")
                        raise BuildError(
                            "checks changed files the model did not write: "
                            + ", ".join(sorted(fatal)) + ". Refusing to commit.",
                            reason="tamper")
                    # Untracked leftovers (a coverage file, say) are not work:
                    # do not stage them, list them, remove them.
                    for path in leftovers:
                        _remove_path(code / path)
                    tracked = _tracked_files(run, code)
                    stage = sorted(p for p in expected
                                   if (code / p).exists() or p in tracked)
                    if stage:
                        _git(run, code, ["add", "-A", "--", *stage])
                    changed_actual, deleted_actual = _staged_changes(run, code)
                    if not (set(changed_actual) | set(deleted_actual)) <= expected:
                        raise BuildError(
                            "the staged diff includes paths the model did not "
                            "write. Refusing to commit.", reason="tamper")
                    message = f"{spec.get('title') or spec.get('id')}"
                    if spec.get("number"):
                        message += f" (#{spec['number']})"
                    _git(run, code, ["commit", "-m", message])
                    commit = _git(run, code, ["rev-parse", "HEAD"]).strip()
                    # The committed range is the source of truth for the ledger.
                    range_changed, range_deleted = _range_changes(run, code, commit_base)
                    if (set(range_changed) | set(range_deleted)
                            != set(changed_actual) | set(deleted_actual)):
                        raise BuildError(
                            "the committed range does not match what was staged. "
                            "Refusing to record this build.", reason="tamper")
                    changed_actual, deleted_actual = range_changed, range_deleted
                result = {
                    "ok": True,
                    "reach": reach,
                    "branch": branch,
                    "files": changed_actual,
                    "deleted": deleted_actual,
                    "leftovers": sorted(leftovers),
                    "plan": plan,
                    "summary": summary,
                    "checks": checks,
                    "checks_mode": checks_mode,
                    "tests_touched": [p for p in changed_actual if safety.is_test_path(p)],
                    "tests_deleted": [p for p in deleted_actual if safety.is_test_path(p)],
                    "ci_touched": [p for p in changed_actual + deleted_actual
                                   if safety.is_ci_path(p)],
                    "commit": commit,
                    "steps": len(actions),
                    "repair_rounds": failures,
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "chars_sent": chars_sent,
                    "chars_received": chars_received,
                    "latency_ms": latency_ms,
                    "step_logs": step_logs,
                    "tokens_in": usage["prompt_tokens"],
                    "tokens_out": usage["completion_tokens"],
                    "cost_usd": round(usage["prompt_tokens"] / 1e6 * prices[0]
                                      + usage["completion_tokens"] / 1e6 * prices[1], 4),
                    "estimated_usage": bool(usage.get("estimated")),
                    "published": False,
                    "merged": False,
                }
                if publish:
                    from ctx.publish import PublishError, publish as publish_pr
                    try:
                        opened = publish_pr(root, contribution_ref, code=code)
                    except PublishError as exc:
                        raise BuildError(f"committed on {branch}, but publish failed: {exc}") from exc
                    result["published"] = True
                    result["pr_url"] = opened["url"]
                    if safety.truthy(repo_meta.get("allow_comment")):
                        try:
                            from ctx.comment import CommentError, comment
                            result["comment"] = comment(root, contribution_ref,
                                                        opened["url"])
                        except CommentError as exc:
                            result["comment_error"] = str(exc)
                    if wait:
                        _wait_for_checks(code, spec.get("number"), wait_minutes)
                    if merge:
                        from ctx.merge import MergeError, merge as merge_pr
                        try:
                            merged = merge_pr(root, contribution_ref, code=code)
                        except MergeError as exc:
                            raise BuildError(
                                f"opened {opened['url']}, but merge failed: {exc}") from exc
                        result["merged"] = bool(merged.get("merged"))
                        result["merged_url"] = merged.get("url") or opened["url"]
                elif merge:
                    raise BuildError("--merge needs --publish; nothing was pushed")
                run_id = _record_run(root, spec, result, mode="live" if publish else "shadow",
                                     transcript=transcript, replies=replies)
                from ctx import writeback
                try:
                    record = writeback.record_delivery(root, contribution_ref, result, run_id)
                    result["record"] = record["id"]
                except writeback.WritebackError:
                    pass
                return result
            transcript.append(
                'action must be plan, list, read, search, write, delete, check, '
                'propose, or finish.')
        raise BuildError(f"the model did not finish within {max_steps} steps",
                         reason="protocol")
    except Exception as exc:
        reason = _failure_reason(exc)
        model_worked = bool(replies)
        # Only a build that actually reached the model is a build attempt: it
        # gets a record and spends the budget. A precondition failure (no
        # approval, missing repo) or an unreachable model does not, and its
        # empty branch is removed so the spec stays eligible.
        if model_worked:
            _record_failure(root, spec, replies, transcript, actions, exc, reason)
        _cleanup_failure(run, anchor, code, branch, default, files, deleted,
                         git_before, on_branch, model_worked, reason)
        if model_worked:
            from ctx import writeback
            try:
                writeback.record_failure(
                    root, contribution_ref, exc, branch=branch,
                    elapsed=round(time.monotonic() - started, 1),
                    checks_mode=checks_mode, reason=reason)
            except Exception:
                pass
        raise
    finally:
        _clear_started(root, body)
        try:
            if wt is not None:
                _git(run, anchor, ["worktree", "remove", "--force", str(wt)])
        except Exception:
            pass
        _unlock(lock)
        shutil.rmtree(hooks_dir, ignore_errors=True)


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


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _retired_branch(run, anchor: Path, branch: str) -> str:
    """A unique `stead/failed/...` name for a retired build branch. The stamp has
    second resolution, so two retirements in the same second would collide; the
    counter keeps each name unique."""
    base = f"stead/failed/{branch.removeprefix('stead/')}-{_stamp()}"
    candidate = base
    n = 2
    while _git(run, anchor, ["branch", "--list", candidate]).strip():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _marker_path(root: Path, body: str) -> Path:
    from ctx import spec as spec_approval
    digest = spec_approval.body_hash(body)
    folder = root / "factories" / "feature-builder" / "runs"
    return folder / f".build-started-{digest[:16]}.json"


def _write_started(root: Path, spec: dict, body: str, *, worktree: str = "") -> None:
    """A "started" marker, removed on normal exit. A hard kill — Task Scheduler
    or Task Manager, which skips exception handlers and finally — leaves it
    behind; the next run reclaims it as an infrastructure failure record and
    removes the worktree it records."""
    try:
        path = _marker_path(root, body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": datetime.now(timezone.utc).isoformat(),
            "contribution": spec.get("id"),
            "worktree": worktree,
        }), encoding="utf-8")
    except OSError:
        pass  # a missing marker only means a hard kill cannot be detected


def _clear_started(root: Path, body: str) -> None:
    try:
        _marker_path(root, body).unlink()
    except OSError:
        pass


def _reclaim_stale_started(run, anchor: Path, root: Path, spec: dict,
                           body: str) -> None:
    """Turn a stale started marker into an infrastructure failure record.

    Only a hard kill leaves the marker (normal failure and success both clear
    it). The dead process may also have left its worktree registered with the
    branch checked out — remove it so the spec is not stuck. If the recorded
    PID is still alive, a build of this spec is genuinely in progress and the
    marker is left alone."""
    path = _marker_path(root, body)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = int(data.get("pid") or 0)
    except (OSError, json.JSONDecodeError, ValueError):
        _clear_started(root, body)
        return
    if _pid_alive(pid):
        return
    wt = data.get("worktree")
    if wt:
        try:
            _git(run, anchor, ["worktree", "remove", "--force", str(wt)])
        except Exception:
            pass
    try:
        _git(run, anchor, ["worktree", "prune"])
    except Exception:
        pass
    from ctx import writeback
    try:
        writeback.record_failure(
            root, str(data.get("contribution") or spec.get("id") or ""),
            BuildError("the previous build was killed before it could record a result"),
            branch=branch_for(spec), reason="infrastructure")
    except Exception:
        pass
    _clear_started(root, body)


def _remain_running(root: Path, deadline: float) -> None:
    if safety.stopped(root):
        raise BuildError("stopped by .stead-stop. Remove it, or run "
                         "`python -m stead factory start`.", reason="precondition")
    if time.monotonic() > deadline:
        raise BuildError("the build hit its time budget. Raise --max-minutes, "
                         "or split the spec.", reason="budget")


def _run_checks(code: Path, command: str, repo_meta: dict,
                deadline: float) -> tuple[bool, str, str]:
    remaining = int(max(30, deadline - time.monotonic()))
    before = safety.git_state_snapshot(code)
    try:
        ok, output, mode = safety.run_checks(code, command, repo_meta, timeout=remaining)
    except safety.SafetyError as exc:
        raise BuildError(str(exc), reason="infrastructure") from exc
    if safety.git_state_snapshot(code) != before:
        raise BuildError(
            "checks changed .git (config or hooks). A check run must not rewrite "
            "git's own execution surface: hooks and config would run on the host "
            "with Stead's environment. Refusing to continue.", reason="tamper")
    return ok, output, mode


def _require_fail_before(run, anchor: Path, code: Path, default: str,
                         new_tests: list[str], files: dict, checks: str,
                         repo_meta: dict, deadline: float) -> bool:
    """(M1.5b) The new test must FAIL against the base, without the code change.

    The model's new test files are applied to a temporary worktree at the base
    commit (no code change) and the checks run there. Returns True when the test
    fails (it genuinely exercises the change) and False when it passes anyway
    (trivial or wrong). The user's checkout and the build branch are never
    touched."""
    wt = Path(tempfile.mkdtemp(prefix="stead-fb-"))
    try:
        # Detached at the default branch tip: a branch worktree would collide
        # with the anchor's own checkout of the default branch.
        base_sha = _git(run, anchor, ["rev-parse", default]).strip()
        _git(run, anchor, ["worktree", "add", "--detach", str(wt), base_sha])
    except Exception as exc:
        raise BuildError(f"could not create a fail-before worktree: {exc}",
                         reason="infrastructure") from exc
    try:
        for rel in new_tests:
            content = files.get(rel)
            if content is None:
                continue
            target = wt / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        ok, _output, _mode = _run_checks(wt, checks, repo_meta, deadline)
        return not ok
    finally:
        try:
            _git(run, anchor, ["worktree", "remove", "--force", str(wt)])
        except Exception:
            pass


def _porcelain(run, code: Path) -> list[tuple[str, str]]:
    """(path, XY) from `git status --porcelain -z -uall`. Null fields keep
    non-ASCII and quoted paths intact, unlike the line parser."""
    raw = _git(run, code, ["status", "--porcelain", "-z", "-uall"])
    fields = raw.split("\0")
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        entries.append((path, status))
        if status[0] in "RC" or status[1] in "RC":
            i += 1  # a rename/copy is followed by its original path
    return entries


def _porcelain_paths(run, code: Path) -> list[str]:
    return [path for path, _status in _porcelain(run, code)]


def _dirty_paths(run, code: Path) -> list[str]:
    """Changed paths that matter for a clean-checkout check. Build caches and
    the Stead lock are ignored, as they are at the commit step."""
    dirty: list[str] = []
    for path in _porcelain_paths(run, code):
        parts = Path(path).parts
        if any(p.casefold() in IGNORE_DIRS or p.casefold() == LOCK_NAME for p in parts):
            continue
        dirty.append(path)
    return dirty


def _side_effects(run, code: Path, expected: set[str],
                  repo_meta: dict) -> tuple[list[str], list[str]]:
    """Changes beyond the model's own writes. Returns (fatal, untracked
    leftovers). A tracked change, or any change to a protected/secret path, is
    fatal. An untracked leftover (a coverage file, say) is not work: the
    caller removes it and records it instead of failing the build."""
    fatal: list[str] = []
    leftovers: list[str] = []
    for path, status in _porcelain(run, code):
        if path in expected:
            continue
        parts = Path(path).parts
        if any(p.casefold() in IGNORE_DIRS or p.casefold() == LOCK_NAME for p in parts):
            continue
        if status == "??" and not (safety.protected_by(path, repo_meta)
                                   or safety.secret_by(path)):
            leftovers.append(path)
        else:
            fatal.append(path)
    return fatal, leftovers


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        pass


def _tracked_files(run, code: Path) -> set[str]:
    return {line.strip().strip('"')
            for line in _git(run, code, ["ls-files"]).splitlines() if line.strip()}


def _range_changes(run, code: Path, base: str) -> tuple[list[str], list[str]]:
    """The committed range from the base commit: (changed, deleted) paths."""
    changed: list[str] = []
    deleted: list[str] = []
    raw = _git(run, code, ["diff", "--name-status", base, "HEAD"])
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status.startswith("D"):
            deleted.append(parts[-1].strip())
        elif status.startswith("R") and len(parts) >= 3:
            deleted.append(parts[1].strip())
            changed.append(parts[-1].strip())
        else:
            changed.append(parts[-1].strip())
    return sorted(set(changed)), sorted(set(deleted))


def _staged_changes(run, code: Path) -> tuple[list[str], list[str]]:
    """The real diff about to be committed: (changed, deleted) paths."""
    changed: list[str] = []
    deleted: list[str] = []
    raw = _git(run, code, ["diff", "--cached", "--name-status", "HEAD"])
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status.startswith("D"):
            deleted.append(parts[-1].strip())
        elif status.startswith("R") and len(parts) >= 3:
            deleted.append(parts[1].strip())
            changed.append(parts[-1].strip())
        else:
            changed.append(parts[-1].strip())
    return sorted(set(changed)), sorted(set(deleted))


def _resolved_rel(target: Path, code: Path) -> str:
    """The path after symlinks: protection matches the real target, not the
    name the model gave (a symlinked directory must not sidestep tests/**)."""
    try:
        return target.resolve().relative_to(code.resolve()).as_posix()
    except ValueError:
        raise BuildError(f"path leaves the repository: {target}")


def _fit_budget(prompt: str, transcript: list[str],
                budget: int = MAX_PROMPT_CHARS) -> list[str]:
    """Keep the whole prompt under a character budget. The transcript is
    resent every step, so without a cap cost grows with the square of the
    step count. Trim older read/search outputs first; they are the bulk."""
    entries = list(transcript)

    def size() -> int:
        return len(prompt) + sum(len(e) + 2 for e in entries)

    for i, entry in enumerate(entries):
        if size() <= budget:
            break
        if entry.startswith("read ") or entry.startswith("search "):
            head = entry.split("\n", 1)[0]
            entries[i] = head + "\n[output trimmed to stay within the prompt budget]"
    for i in range(len(entries)):
        if size() <= budget:
            break
        if i >= len(entries) - 2:  # keep the newest feedback intact
            break
        entries[i] = "[earlier step trimmed to stay within the prompt budget]"
    return entries


def _failure_reason(exc) -> str:
    """Classify a failure for the record. BuildError carries its own reason;
    a timeout is its own class (a small local model can exceed the call timeout
    without being unreachable); anything else came from the model transport (or
    a bug), which is infrastructure."""
    if isinstance(exc, BuildError):
        return exc.reason or "build"
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    return "infrastructure"


def _cleanup_failure(run, anchor: Path, code: Path, branch: str, default: str,
                     files: dict, deleted: list, git_before: dict,
                     on_branch: bool, model_worked: bool,
                     reason: str = "build") -> None:
    """Best-effort after a failed build.

    The build ran in its own worktree, so the user's checkout is never touched
    and no `git clean` ever runs. When the model actually ran (a build-class or
    infrastructure failure after a reply), its work is committed as WIP on the
    build branch (never pushed). A precondition/infrastructure failure before
    any reply, or a tampered build, carries nothing forward: its empty branch is
    removed so the spec stays eligible. Never masks the original error.
    """
    if not on_branch:
        return
    try:
        if git_before:
            after = safety.git_state_snapshot(code)
            if after != git_before:
                safety.git_state_restore(code, git_before, after)
    except Exception:
        pass
    keep = model_worked and reason != "tamper"
    if keep:
        # Quarantine the model's own work so --resume can continue from it.
        try:
            owned = set(files) | set(deleted)
            tracked = _tracked_files(run, code)
            stage = sorted(p for p in owned if (code / p).exists() or p in tracked)
            if stage:
                _git(run, code, ["add", "-A", "--", *stage])
            if _git(run, code, ["diff", "--cached", "--name-only"]).strip():
                _git(run, code, ["commit", "-m", f"WIP: failed build on {branch}"])
        except Exception:
            pass
    try:
        _git(run, anchor, ["worktree", "remove", "--force", str(code)])
    except Exception:
        pass
    if not keep:
        # Nothing should carry forward: drop the branch if it has no commits
        # (a tamper that committed is also discarded).
        try:
            ahead = _git(run, anchor, ["rev-list", "--count",
                                       f"{default}..{branch}"]).strip()
            if reason == "tamper" or ahead == "0":
                _git(run, anchor, ["branch", "-D", branch])
        except Exception:
            pass


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


def _record_run(root: Path, spec: dict, result: dict, *, mode: str,
                transcript=None, replies=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-", (spec.get("title") or "build").lower()).strip("-") or "build"
    folder = root / "factories/feature-builder/runs" / f"{stamp}-build-{slug[:40]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.md").write_text(result.get("plan", "") + "\n", encoding="utf-8")
    (folder / "summary.md").write_text(result.get("summary", "") + "\n", encoding="utf-8")
    if replies is not None:
        (folder / "transcript.md").write_text(
            _transcript_md(replies, transcript or []), encoding="utf-8")
    result["run_dir"] = folder.relative_to(root).as_posix()
    (folder / "build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    from ctx import db
    if not db.db_path(root).exists():
        return None
    conn = db.connect(root)
    try:
        cur = conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, "
            "bundle_path, output, verdict, created) VALUES "
            "('feature-builder', ?, NULL, 'build', ?, ?, ?, 'pending', ?)",
            (spec.get("id"), mode, folder.relative_to(root).as_posix(),
             result.get("summary") or "", db.utcnow()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _transcript_md(replies: list[str], transcript: list[str]) -> str:
    lines = ["# Build transcript", ""]
    for index, reply in enumerate(replies, 1):
        lines.append(f"## Model reply {index}")
        lines.append("```")
        lines.append(str(reply)[:4000])
        lines.append("```")
        lines.append("")
    if transcript:
        lines.append("## Feedback given to the model")
        lines.append("")
        lines.extend(str(item) for item in transcript)
    return "\n".join(lines) + "\n"


def _record_failure(root: Path, spec: dict, replies: list[str],
                    transcript: list[str], actions: list[dict], error,
                    reason: str = "build") -> None:
    """A build that reached the model and failed leaves a trace: what the model
    said and did, and a runs row so the daily budget counts attempts."""
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = re.sub(r"[^a-z0-9]+", "-",
                      (spec.get("title") or "build").lower()).strip("-") or "build"
        folder = root / "factories/feature-builder/runs" / f"{stamp}-build-{slug[:40]}-failed"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "failure.json").write_text(json.dumps({
            "error": str(error),
            "error_class": type(error).__name__,
            "reason": reason,
            "model_turns": len(replies),
            "actions": actions,
        }, indent=2) + "\n", encoding="utf-8")
        (folder / "transcript.md").write_text(
            f"# Failed build\n\nReason: {reason}\n\nError: {error}\n\n"
            + _transcript_md(replies, transcript), encoding="utf-8")
        from ctx import db
        if db.db_path(root).exists():
            conn = db.connect(root)
            try:
                conn.execute(
                    "INSERT INTO runs (factory, task_ref, project, prompt_version, "
                    "mode, bundle_path, output, verdict, created) VALUES "
                    "('feature-builder', ?, NULL, 'build', 'shadow', ?, ?, 'fail', ?)",
                    (spec.get("id"), folder.relative_to(root).as_posix(),
                     str(error)[:2000], db.utcnow()))
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


def _system_prompt(spec: dict, criteria: list[str], tree: str, has_checks: bool,
                   repo_meta: dict, *, ghost: bool = False, context: str = "") -> str:
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
        "Mode GHOST (binding): purely spec, docs, and a code plan, for human\n"
        "approval. ZERO code is applied: you may write or delete markdown\n"
        "files (.md, .markdown, .mdx) only — specs, docs, and the plan. Code\n"
        "snippets inside the plan or docs are fine; never edit source, tests,\n"
        "or CI. Nothing is pushed. A human approves before any code is written.\n"
        if ghost else
        "You are implementing one feature spec in a local git checkout.\n"
    )
    return (
        intro +
        "Reply with exactly one JSON object per turn. No prose, no code fences.\n"
        'Actions: {"action":"plan","summary":"..."}, '
        '{"action":"list","path":"."}, {"action":"read","path":"a.py"}, '
        '{"action":"search","query":"name"}, '
        '{"action":"write","path":"a.py","content":"full file text"}, '
        '{"action":"delete","path":"old.py"}, {"action":"check"}, '
        '{"action":"propose","kind":"decision|glossary","title":"...","text":"..."}, '
        '{"action":"finish","summary":"..."}.\n'
        'Send exactly ONE action object per reply — never an {"actions":[...]} '
        "array, never prose, never code fences. Your first action must be a single "
        "plan. Plan ONCE; after the plan is recorded, do not send plan again. Then "
        "read the real file, write its full new content, run check, and finish. "
        "Do not write before the plan. "
        + check_line +
        "write replaces the whole file. Read a file before changing it, and use the "
        "exact paths from the repository tree below — do not invent filenames. "
        "Stay inside the repository. Do not touch .git. "
        "Do not edit or delete existing tests, CI config, or the checks "
        "definition: those paths are protected, and an attempt fails the build. "
        "Adding a brand-new test file is allowed and expected when the spec has "
        "acceptance criteria. "
        "If the work implies a decision or a glossary term, propose it with "
        "propose; it goes to the inbox for a person, never straight into context. "
        "Match the repo's existing style and tests. Finish when the spec is met.\n\n"
        + (context + "\n\n" if context else "")
        + f"Feature: {spec.get('title')}\n"
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
        raise BuildError(f"absolute paths are not allowed: {raw}", reason="gate")
    parts = [part for part in rel.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise BuildError(f"paths may not leave the repository: {raw}", reason="gate")
    if parts and parts[0].casefold() == ".git":
        raise BuildError("the model may not touch .git", reason="gate")
    return "/".join(parts)


def _ignored(path: Path, code: Path) -> bool:
    try:
        relative = path.resolve().relative_to(code.resolve())
    except ValueError:
        raise BuildError(f"path leaves the repository: {path}")
    return any(part.casefold() in IGNORE_DIRS or part.casefold() == LOCK_NAME
               for part in relative.parts)


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
    """The isolated branch a build for this spec uses (shared with
    publish/merge/review, which resolve it without a checkout)."""
    return factory.branch_for(spec)


def _git(run, code: Path, args: list[str]) -> str:
    return run(["git", *args], code)


def _git_run(argv: list[str], cwd: Path, capture: bool = False):
    try:
        done = subprocess.run(argv, cwd=cwd, check=True, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BuildError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise BuildError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""

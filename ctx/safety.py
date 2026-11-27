"""What the model may touch, and how untrusted checks run.

Two separate jobs, both about containment:

- Protected paths. A model that can edit tests or CI config can weaken its own
  gate. ``.github/`` and test files are refused by default. A repo can opt in
  per group, or add its own paths.
- Checks. The ``checks:`` command runs code the model just wrote, so it runs
  with a scrubbed environment. A repo can ask for a container instead
  (``checks_isolation: docker``), which is what merge requires unless the repo
  explicitly trusts the host.

Also the stop file: one file, checked between every model step, that halts a
build or a watched run without killing the process.
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

STOP_NAME = ".stead-stop"

CI_GLOBS = (
    ".github/**",
    ".gitlab-ci.yml",
    ".circleci/**",
    "azure-pipelines.yml",
    ".buildkite/**",
    "Jenkinsfile",
)
TEST_GLOBS = (
    "tests/**",
    "test/**",
    "spec/**",
    "**/tests/**",
    "**/test/**",
    "**/conftest.py",
    "**/test_*.py",
    "**/*_test.py",
    "**/*_test.go",
    "**/*.test.js",
    "**/*.test.ts",
    "**/*.spec.js",
    "**/*.spec.ts",
)

# A model that reads a key can send it to a provider. Hide the usual secrets
# unless the name is clearly a template.
SECRET_GLOBS = (
    ".env", "**/.env", ".env.*", "**/.env.*",
    "*.pem", "**/*.pem", "*.key", "**/*.key",
    "id_rsa", "**/id_rsa", "id_ed25519", "**/id_ed25519",
    "**/credentials.json", "**/.npmrc", "**/.pypirc",
)
SECRET_NAMES = {".env.example", ".env.sample", ".env.template",
                "example.env", "sample.env"}

# Enough to run a compiler or interpreter. Everything else is dropped so a
# model-written test cannot read the model key, GH_TOKEN, cloud credentials, or
# the Stead deployment token out of the environment.
ENV_KEEP = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
)
DOCKER_TIMEOUT = 900


class SafetyError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def stopped(root: Path) -> bool:
    return (root / STOP_NAME).is_file()


def set_stopped(root: Path, on: bool) -> dict:
    path = root / STOP_NAME
    if on:
        path.write_text(
            "Stead is paused. Builds and watched runs stop between steps.\n"
            "Remove this file, or run `python -m stead factory start`.\n",
            encoding="utf-8")
        return {"stopped": True, "path": str(path)}
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return {"stopped": False, "path": str(path)}


def truthy(value) -> bool:
    """Frontmatter values are strings. Accept the usual spellings."""
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _clean(path) -> str:
    rel = str(path or "").replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def _match(rel: str, pattern: str) -> bool:
    """Case-insensitive on every platform: macOS and Windows filesystems are
    case-insensitive, so `.GitHub/...` and `TESTS/...` are the real paths there."""
    return fnmatch.fnmatchcase(rel.casefold(), pattern.casefold())


def protected_by(path: str, repo_meta: dict) -> str | None:
    """Return the pattern that protects a repo-relative path, or None."""
    if truthy(repo_meta.get("allow_protected")):
        return None
    rel = _clean(path)
    patterns: list[str] = []
    if not truthy(repo_meta.get("allow_ci_edits")):
        patterns.extend(CI_GLOBS)
    if not truthy(repo_meta.get("allow_test_edits")):
        patterns.extend(TEST_GLOBS)
    patterns.extend(_as_list(repo_meta.get("protected_paths")))
    for pattern in patterns:
        if _match(rel, pattern) or _match("/" + rel, pattern):
            return pattern
    return None


def is_test_path(path: str) -> bool:
    rel = _clean(path)
    return any(_match(rel, pattern) for pattern in TEST_GLOBS)


def is_ci_path(path: str) -> bool:
    rel = _clean(path)
    return any(_match(rel, pattern) for pattern in CI_GLOBS)


def test_addition_allowed(path: str, repo_meta: dict) -> bool:
    """A brand-new test file may be added even when tests are protected.

    Editing or deleting an existing test weakens the gate; adding a new test is
    the discipline ``require_tests`` asks for. ``conftest.py`` and ``__init__.py``
    change how *other* tests run, so they never count as a new-test addition.
    An explicit ``protected_paths:`` entry still wins.
    """
    rel = _clean(path)
    if not is_test_path(rel):
        return False
    if rel.rsplit("/", 1)[-1].casefold() in {"conftest.py", "__init__.py"}:
        return False
    for pattern in _as_list(repo_meta.get("protected_paths")):
        if _match(rel, pattern) or _match("/" + rel, pattern):
            return False
    return True


def secret_by(path: str) -> str | None:
    """Return the pattern when a path looks like a secret, or None."""
    rel = _clean(path)
    name = rel.rsplit("/", 1)[-1]
    if name.lower() in SECRET_NAMES or name.lower().endswith(
            (".example", ".sample", ".template")):
        return None
    for pattern in SECRET_GLOBS:
        if _match(rel, pattern):
            return pattern
    return None


def runner_configs(command: str) -> list[str]:
    """Config files a check command is likely to execute transitively."""
    cmd = (command or "").lower()
    found: list[str] = []
    if re.search(r"\bmake\b", cmd):
        found += ["Makefile", "makefile", "GNUmakefile"]
    if re.search(r"\b(npm|yarn|pnpm)\b", cmd):
        found += ["package.json"]
    if re.search(r"\bpytest\b|\bunittest\b|\btox\b|\bnox\b", cmd):
        found += ["conftest.py", "pyproject.toml", "tox.ini", "noxfile.py",
                  "setup.cfg", "pytest.ini"]
    if re.search(r"\bcargo\b", cmd):
        found += ["Cargo.toml"]
    return found


def runner_warnings(code: Path, repo_meta: dict) -> list[str]:
    """Warn when a check runner's config is writable by the model."""
    command = str(repo_meta.get("checks") or "")
    if not command:
        return []
    warnings = []
    for name in runner_configs(command):
        if not (code / name).is_file():
            continue
        if protected_by(name, repo_meta) is None:
            warnings.append(
                f"checks runs `{command.split()[0]}` but {name} is not protected. "
                f"The model could edit it to change what checks do. Add it to "
                f"protected_paths, or allow it deliberately.")
    return warnings


def checks_trusted(repo_meta: dict) -> bool:
    """True when the checks run is isolated, or the repo says trust the host."""
    return (str(repo_meta.get("checks_isolation") or "").strip().lower() == "docker"
            or str(repo_meta.get("trust_checks") or "").strip().lower() == "host")


# --- Git hygiene -----------------------------------------------------------
# Checks execute model-written code with write access to the checkout, .git
# included. A planted hook or a rewritten .git/config (core.fsmonitor,
# core.sshCommand, credential.helper, filter drivers) would run on the HOST
# with Stead's full environment the next time Stead calls git. Two controls:
# every Stead git call disables the checkout's hooks and fsmonitor, and every
# check run is bracketed by a .git/config + hooks snapshot that fails the
# build on any change.

def disable_hooks(argv: list[str], hooks_dir: Path) -> list[str]:
    """Prepend config that points git's hooks at an empty dir we own."""
    if argv and argv[0] == "git":
        return ["git", "-c", f"core.hooksPath={hooks_dir}",
                "-c", "core.fsmonitor=false", *argv[1:]]
    return list(argv)


@contextlib.contextmanager
def hooks_disabled():
    """An empty, unpredictable hooks directory for one build/publish/merge."""
    folder = Path(tempfile.mkdtemp(prefix="stead-no-hooks-"))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def safe_runner(base_run):
    """Wrap a git runner so every call disables the checkout's hooks and
    fsmonitor. Each call gets its own empty hooks dir; git never executes
    anything the checkout planted."""
    def run(argv, cwd):
        with hooks_disabled() as folder:
            return base_run(disable_hooks(argv, folder), cwd)
    return run


def _git_dirs(code: Path) -> list[Path]:
    """The .git dir(s) that matter: a worktree shares the common dir's hooks
    and config, and may carry its own config.worktree."""
    git_path = code / ".git"
    if git_path.is_file():
        try:
            text = git_path.read_text(encoding="utf-8").strip()
        except OSError:
            return []
        if not text.startswith("gitdir:"):
            return []
        git_path = (code / text.split(":", 1)[1].strip()).resolve()
    if not git_path.is_dir():
        return []
    dirs = [git_path]
    commondir = git_path / "commondir"
    if commondir.is_file():
        try:
            common = (git_path / commondir.read_text(encoding="utf-8").strip()).resolve()
            if common != git_path and common.is_dir():
                dirs.append(common)
        except OSError:
            pass
    return dirs


_SNAPSHOT_CAP = 1_000_000


def git_state_snapshot(code: Path) -> dict:
    """Content of .git/config and every hook file, keyed by location.

    Values are bytes, or a sha256 digest string for files over 1 MB (those are
    compared but cannot be restored). Dict equality is the change check.
    """
    snap: dict = {}
    for git_dir in _git_dirs(code):
        try:
            label = git_dir.relative_to(code.resolve()).as_posix()
        except ValueError:
            label = str(git_dir)
        candidates = [git_dir / "config", git_dir / "config.worktree"]
        hooks = git_dir / "hooks"
        if hooks.is_dir():
            candidates.extend(sorted(p for p in hooks.rglob("*") if p.is_file()))
        for path in candidates:
            if not path.is_file():
                continue
            key = label + "/" + path.relative_to(git_dir).as_posix()
            try:
                if path.stat().st_size > _SNAPSHOT_CAP:
                    snap[key] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    snap[key] = path.read_bytes()
            except OSError:
                snap[key] = "unreadable"
    return snap


# Config keys a person's ordinary git work writes while a build runs: `git push
# -u`, a new tracking branch, setting an identity. None of them makes git run
# anything. Every other key (hooksPath, fsmonitor, sshCommand, aliases, filter
# and diff drivers, credential helpers, includes, remote URLs, ...) still counts.
_HARMLESS_CONFIG_KEYS = (
    re.compile(r"^branch\..+\.[a-z0-9-]+$"),
    re.compile(r"^user\.[a-z0-9-]+$"),
)


def _config_entries(data: bytes) -> list[tuple[str, str]] | None:
    """The settings in one git config file, as git itself parses them, without
    following includes. None when git cannot parse it."""
    handle, name = tempfile.mkstemp(suffix=".gitconfig")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        done = subprocess.run(
            ["git", "config", "--no-includes", "--file", name, "--list", "-z"],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(name)
    if done.returncode != 0:
        return None
    entries = []
    for item in done.stdout.split(b"\0"):
        if not item:
            continue
        key, _sep, value = item.partition(b"\n")
        entries.append((key.decode("utf-8", "replace"), value.decode("utf-8", "replace")))
    return entries


def _significant(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(e for e in entries
                  if not any(rx.match(e[0]) for rx in _HARMLESS_CONFIG_KEYS))


def _is_config_key(key: str) -> bool:
    return "/hooks/" not in key and (key.endswith("/config")
                                     or key.endswith("/config.worktree"))


def git_state_changes(before: dict, after: dict) -> list[str]:
    """What changed between two snapshots in a way that matters.

    Any hook change counts. A config file counts unless every setting that
    changed is a harmless one (branch tracking, user identity), so a person's
    `git push -u` during a build is not mistaken for a check rewriting git.
    A config git cannot parse counts as changed."""
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if (_is_config_key(key) and isinstance(old, (bytes, type(None)))
                and isinstance(new, (bytes, type(None)))):
            old_entries = _config_entries(old or b"")
            new_entries = _config_entries(new or b"")
            if (old_entries is not None and new_entries is not None
                    and _significant(old_entries) == _significant(new_entries)):
                continue
        changed.append(key)
    return changed


def git_state_restore(code: Path, before: dict, after: dict) -> list[str]:
    """Undo .git changes a check run made. Returns what could not be restored."""
    problems: list[str] = []
    for git_dir in _git_dirs(code):
        try:
            label = git_dir.relative_to(code.resolve()).as_posix()
        except ValueError:
            label = str(git_dir)
        prefix = label + "/"
        wanted = {k[len(prefix):]: v for k, v in before.items() if k.startswith(prefix)}
        current = {k[len(prefix):]: v for k, v in after.items() if k.startswith(prefix)}
        for rel, value in wanted.items():
            if current.get(rel) == value:
                continue
            path = git_dir / rel
            if isinstance(value, bytes):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value)
                except OSError:
                    problems.append(rel)
            else:
                problems.append(rel)  # digest-only or unreadable: cannot restore
        for rel in current:
            if rel not in wanted:
                try:
                    (git_dir / rel).unlink()
                except OSError:
                    problems.append(rel)
    return problems


def _env_pairs(value) -> dict:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    pairs = {}
    for item in _as_list(value):
        key, _sep, val = item.partition("=")
        if key.strip():
            pairs[key.strip()] = val.strip()
    return pairs


def environment(repo_meta: dict) -> dict:
    env = {key: os.environ[key] for key in ENV_KEEP if key in os.environ}
    for key, value in _env_pairs(repo_meta.get("checks_env")).items():
        env[key] = value
    return env


def run_checks(code: Path, command: str, repo_meta: dict, *,
               timeout: int = DOCKER_TIMEOUT) -> tuple[bool, str, str]:
    """Run the repo check command. Returns (ok, output, mode)."""
    isolation = str(repo_meta.get("checks_isolation") or "host").strip().lower()
    if isolation not in {"host", "docker"}:
        raise SafetyError(f"invalid checks_isolation {isolation!r}")
    name = ""
    if isolation == "docker":
        image = str(repo_meta.get("checks_image") or "").strip()
        if not image:
            raise SafetyError(
                "checks_isolation is docker but checks_image is empty. "
                "Set checks_image on the repo, for example python:3.12-slim.")
        name = f"stead-checks-{uuid.uuid4().hex[:12]}"
        argv = _docker_command(code, command, image, repo_meta, name)
        mode = "docker"
    else:
        argv = command
        mode = "host"
    try:
        done = subprocess.run(
            argv, cwd=code, shell=(isolation == "host"),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(30, timeout), env=environment(repo_meta),
        )
    except subprocess.TimeoutExpired as exc:
        if name:
            # Killing the docker client does not stop the container. Name it
            # and kill it explicitly, or it keeps running after the timeout.
            try:
                subprocess.run(["docker", "kill", name], capture_output=True,
                               timeout=30)
            except (OSError, subprocess.SubprocessError):
                pass
        raise SafetyError(f"checks timed out after {max(30, timeout)}s") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise SafetyError(f"could not run checks: {exc}") from exc
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output, mode


def _docker_command(code: Path, command: str, image: str, repo_meta: dict,
                    name: str) -> list[str]:
    argv = [
        "docker", "run", "--rm", "--name", name, "--network", "none",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "2g", "--cpus", "2",
    ]
    if os.name != "nt":
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for key, value in _env_pairs(repo_meta.get("checks_env")).items():
        argv += ["-e", f"{key}={value}"]
    argv += ["-v", f"{code}:/src"]
    # The checkout is read-write so checks can build, but .git is read-only:
    # code in the container must not plant hooks or rewrite git config that
    # the host would later execute.
    if (code / ".git").exists():
        argv += ["-v", f"{code / '.git'}:/src/.git:ro"]
    argv += ["-w", "/src", image, "sh", "-lc", command]
    return argv


def write_note(path: Path, result: dict) -> None:
    """Small local record of what a check run did. Never authoritative."""
    payload = dict(result)
    payload["written"] = datetime.now(timezone.utc).isoformat()
    note = path.with_suffix(".checks.json")
    note.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

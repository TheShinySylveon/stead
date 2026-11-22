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

import fnmatch
import json
import os
import re
import subprocess
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
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch("/" + rel, pattern):
            return pattern
    return None


def is_test_path(path: str) -> bool:
    rel = _clean(path)
    return any(fnmatch.fnmatch(rel, pattern) for pattern in TEST_GLOBS)


def is_ci_path(path: str) -> bool:
    rel = _clean(path)
    return any(fnmatch.fnmatch(rel, pattern) for pattern in CI_GLOBS)


def secret_by(path: str) -> str | None:
    """Return the pattern when a path looks like a secret, or None."""
    rel = _clean(path)
    name = rel.rsplit("/", 1)[-1]
    if name.lower() in SECRET_NAMES or name.lower().endswith(
            (".example", ".sample", ".template")):
        return None
    for pattern in SECRET_GLOBS:
        if fnmatch.fnmatch(rel, pattern):
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
    if isolation == "docker":
        image = str(repo_meta.get("checks_image") or "").strip()
        if not image:
            raise SafetyError(
                "checks_isolation is docker but checks_image is empty. "
                "Set checks_image on the repo, for example python:3.12-slim.")
        argv = _docker_command(code, command, image, repo_meta)
        mode = "docker"
    else:
        argv = command
        mode = "host"
    try:
        done = subprocess.run(
            argv, cwd=code, shell=(isolation == "host"),
            capture_output=True, text=True, timeout=max(30, timeout),
            env=environment(repo_meta),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SafetyError(f"could not run checks: {exc}") from exc
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output, mode


def _docker_command(code: Path, command: str, image: str, repo_meta: dict) -> list[str]:
    argv = [
        "docker", "run", "--rm", "--network", "none",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--memory", "2g", "--cpus", "2",
    ]
    if os.name != "nt":
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for key, value in _env_pairs(repo_meta.get("checks_env")).items():
        argv += ["-e", f"{key}={value}"]
    argv += ["-v", f"{code}:/src", "-w", "/src", image, "sh", "-lc", command]
    return argv


def write_note(path: Path, result: dict) -> None:
    """Small local record of what a check run did. Never authoritative."""
    payload = dict(result)
    payload["written"] = datetime.now(timezone.utc).isoformat()
    note = path.with_suffix(".checks.json")
    note.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

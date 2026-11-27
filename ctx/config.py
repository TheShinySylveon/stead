"""Deployment settings. Not the knowledge store.

Single-user (default) binds the cockpit to loopback. Multi-user is a deployed
process, normally the Docker image, and it will not start without an access
token. The token lives in the environment or in gitignored stead.json. It is
never written into context markdown.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

DEPLOYMENTS = ("single", "multi")
ACTOR_KINDS = ("human", "agent")
CONFIG_NAME = "stead.json"
ENV_DEPLOYMENT = "STEAD_DEPLOYMENT"
ENV_BIND = "STEAD_BIND"
ENV_PORT = "STEAD_PORT"
ENV_TOKEN = "STEAD_ACCESS_TOKEN"
ENV_HOOK = "STEAD_HOOK_TOKEN"


class ConfigError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def config_path(root: Path) -> Path:
    return root / CONFIG_NAME


def read_raw(root: Path) -> dict:
    path = config_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read {CONFIG_NAME}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_NAME} must be a JSON object")
    return data


def load(root: Path) -> dict:
    data = read_raw(root)
    if not data:
        return {"deployment": "single", "bind": "127.0.0.1", "port": 8765}
    deployment = data.get("deployment") or "single"
    if deployment not in DEPLOYMENTS:
        raise ConfigError(f"invalid deployment {deployment!r}")
    return {
        "deployment": deployment,
        "bind": data.get("bind") or ("0.0.0.0" if deployment == "multi" else "127.0.0.1"),
        "port": int(data.get("port") or 8765),
        "access_token": data.get("access_token") or "",
    }


def _write_config(root: Path, payload: dict) -> None:
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".stead-cfg-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(root: Path, data: dict) -> None:
    current = read_raw(root)
    deployment = data.get("deployment") or "single"
    if deployment not in DEPLOYMENTS:
        raise ConfigError(f"invalid deployment {deployment!r}")
    token = data.get("access_token") or ""
    if deployment == "multi" and not token:
        raise ConfigError("a multi-user deployment needs an access token")
    payload = {
        "deployment": deployment,
        "bind": "0.0.0.0" if deployment == "multi" else "127.0.0.1",
        "port": int(data.get("port") or 8765),
        "access_token": token,
    }
    for key in ("model", "reviewer", "models", "roles", "factory", "sync"):
        value = data[key] if key in data else current.get(key)
        if isinstance(value, dict) and value:
            payload[key] = value
    actor = data["actor"] if "actor" in data else current.get("actor")
    if isinstance(actor, str) and actor:
        payload["actor"] = actor
    hook = data["hook_token"] if "hook_token" in data else current.get("hook_token")
    if isinstance(hook, str) and hook:
        payload["hook_token"] = hook
    _write_config(root, payload)


def hook_token(root: Path) -> str:
    """Webhook secret. Env wins. Never written into context markdown."""
    chosen = os.environ.get(ENV_HOOK, "").strip()
    if chosen:
        return chosen
    raw = read_raw(root).get("hook_token") or ""
    return raw.strip() if isinstance(raw, str) else ""


def set_hook_token(root: Path) -> str:
    """Create a webhook token. Does not drop other settings. Returns it once."""
    token = secrets.token_urlsafe(24)
    current = read_raw(root)
    current["hook_token"] = token
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return token


def save_actor(root: Path, actor_id: str) -> None:
    """Remember who is writing. Does not drop deployment or model settings."""
    current = read_raw(root)
    current["actor"] = actor_id
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def save_factory(root: Path, factory: dict) -> None:
    """Write the install factory preference without dropping other settings."""
    current = read_raw(root)
    current["factory"] = factory
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def check_repos(repos: list[str]) -> list[str]:
    """OWNER/NAME names, deduplicated case-insensitively, in the given order."""
    seen: dict[str, str] = {}
    for raw in repos:
        name = str(raw).strip().strip("/")
        if name.lower().startswith("https://github.com/"):
            name = name[len("https://github.com/"):].strip("/")
        if not _REPO_RE.match(name):
            raise ConfigError(f"not a GitHub repo name: {raw!r}. Use OWNER/NAME.")
        seen.setdefault(name.lower(), name)
    return list(seen.values())


def sync_repos(root: Path) -> list[str]:
    """The saved `sync github` scope: [] means every repo."""
    block = read_raw(root).get("sync")
    repos = block.get("repos") if isinstance(block, dict) else None
    if not isinstance(repos, list):
        return []
    try:
        return check_repos(repos)
    except ConfigError:
        return []


def save_sync_repos(root: Path, repos: list[str]) -> list[str]:
    """Save (or, with [], clear) the `sync github` scope. Keeps other settings."""
    chosen = check_repos(repos)
    current = read_raw(root)
    if chosen:
        current["sync"] = {"repos": chosen}
    else:
        current.pop("sync", None)
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return chosen


def save_model(root: Path, model: dict, block: str = "model") -> None:
    """Write one model block without dropping the other settings."""
    current = read_raw(root)
    current[block] = model
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def save_blocks(root: Path, **blocks) -> None:
    """Write (or, with an empty value, remove) top-level blocks such as `models`
    and `roles`, without dropping the other settings."""
    current = read_raw(root)
    for key, value in blocks.items():
        if value is None or (isinstance(value, (dict, list)) and not value):
            current.pop(key, None)
        else:
            current[key] = value
    current.setdefault("deployment", "single")
    current.setdefault("bind", "127.0.0.1")
    current.setdefault("port", 8765)
    current.setdefault("access_token", "")
    config_path(root).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def effective(root: Path, *, deploy: bool = False) -> dict:
    """What this process should do. Env and --deploy override the file.

    A normal local `stead ui` stays on loopback even if stead.json says multi.
    The Docker image sets STEAD_DEPLOYMENT=multi. `stead ui --deploy` is the
    explicit local switch.
    """
    file_cfg = load(root)
    env_mode = os.environ.get(ENV_DEPLOYMENT, "").strip()
    if env_mode and env_mode not in DEPLOYMENTS:
        raise ConfigError(f"invalid {ENV_DEPLOYMENT} {env_mode!r}")
    if env_mode == "multi" or deploy:
        deployment = "multi"
    elif env_mode == "single":
        deployment = "single"
    else:
        deployment = "single"
    token = os.environ.get(ENV_TOKEN, "").strip() or file_cfg.get("access_token") or ""
    from ctx.accounts import AccountError, count
    try:
        people = count(root)
    except AccountError as exc:
        raise ConfigError(str(exc)) from exc
    if deployment == "multi" and not token and people < 1:
        raise ConfigError(
            "multi-user mode needs a person account, or STEAD_ACCESS_TOKEN "
            "until the first account exists. "
            "python -m stead account add --name NAME --actor ACTOR")
    port_raw = os.environ.get(ENV_PORT, "").strip()
    port = int(port_raw) if port_raw else int(file_cfg.get("port") or 8765)
    bind = os.environ.get(ENV_BIND, "").strip()
    if not bind:
        bind = "0.0.0.0" if deployment == "multi" else "127.0.0.1"
    return {"deployment": deployment, "bind": bind, "port": port, "access_token": token}


def public_view(root: Path) -> dict:
    """Settings the cockpit may show. Never includes the token."""
    file_cfg = load(root)
    return {
        "deployment": file_cfg["deployment"],
        "bind": file_cfg["bind"],
        "port": file_cfg["port"],
        "token_set": bool(file_cfg.get("access_token")),
    }


def choose(root: Path, deployment: str) -> dict:
    """Record single or multi. Multi generates a token if one is missing.

    Returns the token only when it was just created. Callers must show it
    once and not write it into markdown.
    """
    if deployment not in DEPLOYMENTS:
        raise ConfigError(f"invalid deployment {deployment!r}")
    current = load(root)
    created = ""
    token = current.get("access_token") or ""
    if deployment == "multi" and not token:
        created = secrets.token_urlsafe(24)
        token = created
    if deployment == "single":
        token = ""
    save(root, {"deployment": deployment, "access_token": token, "port": current.get("port") or 8765})
    view = public_view(root)
    if created:
        view["access_token"] = created
    return view


def rotate_token(root: Path) -> str:
    current = load(root)
    if current["deployment"] != "multi":
        raise ConfigError("set deployment to multi before rotating the access token")
    token = secrets.token_urlsafe(24)
    save(root, {**current, "access_token": token})
    return token

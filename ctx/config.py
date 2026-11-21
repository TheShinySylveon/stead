"""Deployment settings. Not the knowledge store.

Single-user (default) binds the cockpit to loopback. Multi-user is a deployed
process, normally the Docker image, and it will not start without an access
token. The token lives in the environment or in gitignored stead.json. It is
never written into context markdown.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

DEPLOYMENTS = ("single", "multi")
ACTOR_KINDS = ("human", "agent")
CONFIG_NAME = "stead.json"
ENV_DEPLOYMENT = "STEAD_DEPLOYMENT"
ENV_BIND = "STEAD_BIND"
ENV_PORT = "STEAD_PORT"
ENV_TOKEN = "STEAD_ACCESS_TOKEN"


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
    for key in ("model", "factory", "actor"):
        value = data[key] if key in data else current.get(key)
        if isinstance(value, dict) and value:
            payload[key] = value
    config_path(root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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


def save_model(root: Path, model: dict) -> None:
    """Write the model block without dropping the deployment fields."""
    current = read_raw(root)
    current["model"] = model
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
    if deployment == "multi" and not token:
        raise ConfigError(
            "multi-user mode needs an access token. Set STEAD_ACCESS_TOKEN "
            "or run welcome and choose Shared server.")
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

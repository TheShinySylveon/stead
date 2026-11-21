"""Who last wrote an object. Attribution, not a login.

The current actor is STEAD_ACTOR, or the actor id in gitignored stead.json.
A write stamps that id when the actor file exists. It never invents one.
"""

from __future__ import annotations

import os
from pathlib import Path

from ctx import config, objects

ENV_ACTOR = "STEAD_ACTOR"


class ActorError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def current(root: Path) -> str:
    chosen = os.environ.get(ENV_ACTOR, "").strip()
    if chosen:
        return chosen
    raw = config.read_raw(root).get("actor") or ""
    return raw.strip() if isinstance(raw, str) else ""


def use(root: Path, actor_id: str) -> str:
    actor_id = (actor_id or "").strip()
    if objects.find(root, "actor", actor_id) is None:
        raise ActorError(f"actor not found: {actor_id}")
    config.save_actor(root, actor_id)
    return actor_id


def stamp(root: Path, meta: dict) -> None:
    """Set actor: to the current actor when that file exists."""
    actor_id = current(root)
    if not actor_id or objects.find(root, "actor", actor_id) is None:
        return
    meta["actor"] = actor_id

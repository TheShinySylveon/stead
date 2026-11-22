"""How far feature-builder may go. Settings only. No remote writes.

Two knobs:

- trigger: on-demand (a person picks one spec) or watch (a scheduler may
  pick up matching specs in that repo).
- reach: the ceiling. ghost, shadow, draft-pr, pr, or merge.

The ceiling is per repo. An install default can be ghost, shadow, draft-pr,
or pr. Merge is never inherited. A repo has to say merge itself. A run may
ask for less than the ceiling. It may not ask for more.

Ghost is the lowest rung: purely spec, docs, and a code plan for human
approval — the plan plus markdown spec/doc changes only. Zero code applied,
zero checks, zero remote writes.
"""

from __future__ import annotations

from pathlib import Path

from ctx import config, frontmatter, objects

TRIGGERS = ("on-demand", "watch")
REACHES = ("ghost", "shadow", "draft-pr", "pr", "merge")
INSTALL_REACHES = ("ghost", "shadow", "draft-pr", "pr")
_RANK = {name: i for i, name in enumerate(REACHES)}


class AutonomyError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def factory_defaults(root: Path) -> dict:
    """Install preference. Merge in the file is ignored."""
    raw = config.read_raw(root).get("factory") or {}
    if not isinstance(raw, dict):
        raw = {}
    trigger = raw.get("trigger") if raw.get("trigger") in TRIGGERS else "on-demand"
    reach = raw.get("reach") if raw.get("reach") in INSTALL_REACHES else "shadow"
    try:
        builds = int(raw.get("max_builds_per_day", 3))
    except (TypeError, ValueError):
        builds = 3
    try:
        minutes = int(raw.get("build_minutes", 30))
    except (TypeError, ValueError):
        minutes = 30
    return {
        "trigger": trigger,
        "reach": reach,
        "max_builds_per_day": max(0, min(builds, 100)),
        "build_minutes": max(1, min(minutes, 480)),
    }


def set_defaults(root: Path, *, trigger: str | None = None, reach: str | None = None,
                 max_builds_per_day: int | None = None,
                 build_minutes: int | None = None) -> dict:
    current = factory_defaults(root)
    if trigger is not None:
        if trigger not in TRIGGERS:
            raise AutonomyError(f"invalid trigger {trigger!r}")
        current["trigger"] = trigger
    if reach is not None:
        if reach == "merge":
            raise AutonomyError(
                "the install default cannot be merge. Set merge on the repo.")
        if reach not in INSTALL_REACHES:
            raise AutonomyError(f"invalid reach {reach!r}")
        current["reach"] = reach
    if max_builds_per_day is not None:
        if max_builds_per_day < 0:
            raise AutonomyError("max_builds_per_day cannot be negative")
        current["max_builds_per_day"] = max_builds_per_day
    if build_minutes is not None:
        if build_minutes < 1:
            raise AutonomyError("build_minutes must be at least 1")
        current["build_minutes"] = build_minutes
    config.save_factory(root, current)
    return current


def effective(root: Path, repo_meta: dict) -> dict:
    """Ceiling for one repo. Merge only when this file says merge."""
    defaults = factory_defaults(root)
    trigger = repo_meta.get("trigger") if repo_meta.get("trigger") in TRIGGERS else defaults["trigger"]
    explicit = repo_meta.get("reach") or ""
    if explicit == "merge":
        ceiling, merge_explicit = "merge", True
    elif explicit in REACHES:
        ceiling, merge_explicit = explicit, False
    else:
        ceiling, merge_explicit = defaults["reach"], False
    return {
        "trigger": trigger,
        "ceiling": ceiling,
        "merge_explicit": merge_explicit,
        "trigger_explicit": repo_meta.get("trigger") in TRIGGERS,
        "reach_explicit": explicit in REACHES,
    }


def permit(policy: dict, requested: str | None) -> str:
    """Return the reach this run may use. Raises if it is above the ceiling."""
    asked = requested or policy["ceiling"]
    if asked not in REACHES:
        raise AutonomyError(f"invalid reach {asked!r}")
    if _RANK[asked] > _RANK[policy["ceiling"]]:
        raise AutonomyError(
            f"reach {asked} is above this repo's ceiling {policy['ceiling']}. "
            "Lower the request, or raise the ceiling on the repo. "
            "Merge is never inherited.")
    if asked == "merge" and not policy["merge_explicit"]:
        raise AutonomyError("merge must be set on the repo. It is not inherited.")
    return asked


def set_repo(root: Path, repo_id: str, *, trigger: str | None = None,
             reach: str | None = None, code_path: str | None = None,
             extra: dict | None = None) -> dict:
    found = objects.find(root, "repo", repo_id)
    if found is None:
        raise AutonomyError(f"repo not found: {repo_id}")
    path, meta, body = found
    if trigger is not None:
        if trigger not in TRIGGERS:
            raise AutonomyError(f"invalid trigger {trigger!r}")
        meta["trigger"] = trigger
    if reach is not None:
        if reach not in REACHES:
            raise AutonomyError(f"invalid reach {reach!r}")
        meta["reach"] = reach
    if code_path is not None:
        target = Path(code_path).expanduser()
        if not target.is_dir():
            raise AutonomyError(f"code_path is not a directory: {code_path}")
        if target.resolve() == root.resolve():
            raise AutonomyError("code_path must be the project checkout, not this Stead repo")
        meta["code_path"] = str(target)
    for key, value in (extra or {}).items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[str(key)] = value
    if trigger is None and reach is None and code_path is None and not extra:
        raise AutonomyError("nothing to set")
    from datetime import date
    from ctx.actors import stamp
    meta["updated"] = date.today().isoformat()
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return effective(root, meta)

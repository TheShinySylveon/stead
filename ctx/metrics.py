"""Dogfood metrics from the durable build records. No model, no network.

The ``runs`` table is a rebuildable index; the ``build-record`` documents are
the versioned truth. This reads those documents and reports what the factory
actually did: how many specs built, how many merged without a human edit, repair
rounds, checks mode, and time. These are the numbers to publish, not Lighthouse
on a loopback page.
"""

from __future__ import annotations

from pathlib import Path

from ctx import objects
from ctx.writeback import RECORD_TAG


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def collect(root: Path, repo: str | None = None) -> dict:
    records = []
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags:
            continue
        if repo and f"repo:{repo}".lower() not in tags:
            continue
        records.append(meta)
    records.sort(key=lambda m: str(m.get("created") or ""), reverse=True)

    outcomes = {"merged": 0, "published": 0, "committed": 0}
    modes = {"docker": 0, "host": 0, "none": 0}
    elapsed = 0.0
    repairs = 0
    files = tests_touched = tests_deleted = 0
    by_repo: dict[str, int] = {}
    for meta in records:
        outcome = str(meta.get("outcome") or "committed")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        mode = str(meta.get("checks_mode") or "none")
        modes[mode] = modes.get(mode, 0) + 1
        elapsed += _num(meta.get("elapsed_seconds"))
        repairs += int(_num(meta.get("repair_rounds")))
        files += len(_list(meta.get("files")))
        tests_touched += len(_list(meta.get("tests_touched")))
        tests_deleted += len(_list(meta.get("tests_deleted")))
        for tag in (meta.get("tags") or []):
            if str(tag).lower().startswith("repo:"):
                key = str(tag)[5:]
                by_repo[key] = by_repo.get(key, 0) + 1
    total = len(records)
    return {
        "builds": total,
        "outcomes": outcomes,
        "merged_share": round(outcomes["merged"] / total, 3) if total else 0.0,
        "checks_modes": modes,
        "avg_elapsed_seconds": round(elapsed / total, 1) if total else 0.0,
        "repair_rounds": repairs,
        "files_touched": files,
        "tests_touched": tests_touched,
        "tests_deleted": tests_deleted,
        "by_repo": by_repo,
        "recent": [
            {"title": m.get("title", ""), "outcome": m.get("outcome", ""),
             "created": m.get("created", ""),
             "repo": next((str(t)[5:] for t in (m.get("tags") or [])
                           if str(t).lower().startswith("repo:")), "")}
            for m in records[:10]
        ],
    }


def render(report: dict) -> str:
    if not report["builds"]:
        return ("No build records yet. Approve a spec and run `stead build`; "
                "each successful build writes a build-record document.")
    out = report["outcomes"]
    lines = [
        f"builds: {report['builds']}",
        f"merged: {out['merged']}  published: {out['published']}  "
        f"committed (local): {out['committed']}",
        f"merged share: {report['merged_share']:.0%}",
        f"checks: docker {report['checks_modes'].get('docker', 0)}  "
        f"host {report['checks_modes'].get('host', 0)}  "
        f"none {report['checks_modes'].get('none', 0)}",
        f"avg build time: {report['avg_elapsed_seconds']}s",
        f"repair rounds: {report['repair_rounds']}",
        f"files touched: {report['files_touched']}  "
        f"tests touched: {report['tests_touched']}  "
        f"tests deleted: {report['tests_deleted']}",
    ]
    if report["by_repo"]:
        lines.append("by repo: " + ", ".join(
            f"{repo}={n}" for repo, n in sorted(report["by_repo"].items())))
    if report["recent"]:
        lines.append("recent:")
        for item in report["recent"]:
            lines.append(f"  {item['created']}  {item['outcome']:<9}  {item['title']}")
    return "\n".join(lines)

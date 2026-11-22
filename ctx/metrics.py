"""Dogfood metrics from the durable build records. No model, no network.

The ``runs`` table is a rebuildable index; the ``build-record`` documents are
the versioned truth. This reads those documents and reports what the factory
actually did: how many specs built, how many failed, how many merged after
review (with or without a human edit), repair rounds, checks mode, time, and
characters sent. Failed builds write a record too, so there is a failure rate.
Merged/closed outcomes and human edits are reconciled from live PR state by
``stead sync github`` (read-only), so a human merge under the ``pr`` ceiling
reaches these numbers. These are the numbers to publish, not Lighthouse on a
loopback page.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ctx import objects
from ctx.writeback import RECORD_TAG, REVIEW_TAG


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


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string into a date. Raise a clear ValueError otherwise."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD")


def collect(root: Path, repo: str | None = None, since: str | None = None) -> dict:
    since_date = None
    if since is not None:
        since_date = _parse_date(since)
    records = []
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags:
            continue
        if repo and f"repo:{repo}".lower() not in tags:
            continue
        if since_date is not None:
            created = str(meta.get("created") or "")
            try:
                created_date = datetime.strptime(created, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if created_date < since_date:
                continue
        records.append(meta)
    records.sort(key=lambda m: str(m.get("created") or ""), reverse=True)

    outcomes = {"merged": 0, "published": 0, "committed": 0, "failed": 0, "closed": 0}
    # "committed" is mechanical; these three are the hand-checked rubric verdict.
    correct = incorrect = unverified = 0
    build_failures = 0
    infra_failures = 0
    modes = {"docker": 0, "host": 0, "none": 0}
    elapsed = 0.0
    repairs = 0
    files = tests_touched = tests_deleted = 0
    human_edits = 0
    chars_sent = tokens_in = tokens_out = 0
    cost = 0.0
    by_repo: dict[str, int] = {}
    for meta in records:
        outcome = str(meta.get("outcome") or "committed")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcome in ("committed", "published", "merged"):
            verdict = str(meta.get("correct") or "").lower()
            if verdict == "true":
                correct += 1
            elif verdict == "false":
                incorrect += 1
            else:
                unverified += 1
        if outcome == "failed":
            if str(meta.get("reason") or "build") == "infrastructure":
                infra_failures += 1
            else:
                build_failures += 1
        mode = str(meta.get("checks_mode") or "none")
        modes[mode] = modes.get(mode, 0) + 1
        elapsed += _num(meta.get("elapsed_seconds"))
        repairs += int(_num(meta.get("repair_rounds")))
        files += len(_list(meta.get("files")))
        tests_touched += len(_list(meta.get("tests_touched")))
        tests_deleted += len(_list(meta.get("tests_deleted")))
        chars_sent += int(_num(meta.get("chars_sent")))
        tokens_in += int(_num(meta.get("tokens_in")))
        tokens_out += int(_num(meta.get("tokens_out")))
        cost += _num(meta.get("cost_usd"))
        if str(meta.get("human_edits") or "").lower() == "true":
            human_edits += 1
        for tag in (meta.get("tags") or []):
            if str(tag).lower().startswith("repo:"):
                key = str(tag)[5:]
                by_repo[key] = by_repo.get(key, 0) + 1
    reviews = {"approve": 0, "reject": 0}
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if REVIEW_TAG in tags:
            verdict = str(meta.get("verdict") or "").lower()
            if verdict in reviews:
                reviews[verdict] += 1
    total = len(records)
    attempts = total - infra_failures  # an infrastructure failure is not a build attempt
    return {
        "builds": total,
        "outcomes": outcomes,
        "correct": correct,
        "incorrect": incorrect,
        "unverified": unverified,
        "build_failures": build_failures,
        "infra_failures": infra_failures,
        "merged_share": round(outcomes["merged"] / total, 3) if total else 0.0,
        "failure_rate": round(build_failures / attempts, 3) if attempts else 0.0,
        "human_edits": human_edits,
        "reviews": reviews,
        "checks_modes": modes,
        "avg_elapsed_seconds": round(elapsed / total, 1) if total else 0.0,
        "repair_rounds": repairs,
        "files_touched": files,
        "tests_touched": tests_touched,
        "tests_deleted": tests_deleted,
        "chars_sent": chars_sent,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 4),
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
                "each build, success or failure, writes a build-record document.")
    out = report["outcomes"]
    lines = [
        f"builds: {report['builds']}",
        f"merged: {out['merged']}  published: {out['published']}  "
        f"committed: {out['committed']}  failed: {out['failed']}  "
        f"closed: {out['closed']}",
        f"correct: {report['correct']}  incorrect: {report['incorrect']}  "
        f"unverified: {report['unverified']}   (hand-checked rubric; "
        f"committed is mechanical, not a success)",
        f"failures: build {report['build_failures']}  "
        f"infrastructure {report['infra_failures']}",
        f"merged share: {report['merged_share']:.0%}  "
        f"failure rate (build-class): {report['failure_rate']:.0%}",
        f"merged after a human edit: {report['human_edits']}",
        f"checks: docker {report['checks_modes'].get('docker', 0)}  "
        f"host {report['checks_modes'].get('host', 0)}  "
        f"none {report['checks_modes'].get('none', 0)}",
        f"avg build time: {report['avg_elapsed_seconds']}s",
        f"repair rounds: {report['repair_rounds']}",
        f"files touched: {report['files_touched']}  "
        f"tests touched: {report['tests_touched']}  "
        f"tests deleted: {report['tests_deleted']}",
        f"tokens: in {report['tokens_in']}  out {report['tokens_out']}  "
        f"cost: ${report['cost_usd']:.2f}",
        f"independent reviews: approve {report['reviews']['approve']}  "
        f"reject {report['reviews']['reject']}",
        f"characters sent to the model: {report['chars_sent']}",
    ]
    if report["by_repo"]:
        lines.append("by repo: " + ", ".join(
            f"{repo}={n}" for repo, n in sorted(report["by_repo"].items())))
    if report["recent"]:
        lines.append("recent:")
        for item in report["recent"]:
            lines.append(f"  {item['created']}  {item['outcome']:<9}  {item['title']}")
    return "\n".join(lines)

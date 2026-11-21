"""Import a local email, calendar, or transcript file into the inbox.

No network. Nothing is written into context/. A person still triages the note.
"""

from __future__ import annotations

import email
import re
from email import policy
from pathlib import Path

from ctx.ui import capture

_ICS_UNFOLD = re.compile(r"\r?\n[ \t]")


class InboxImportError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def import_file(root: Path, source: str) -> list[dict]:
    """Write one or more inbox notes from a local file. Returns their names."""
    path = Path(source)
    if not path.is_file():
        raise InboxImportError(f"file not found: {source}")
    suffix = path.suffix.lower()
    if suffix == ".eml":
        title, body = _email(path)
        notes = [(title, body)]
    elif suffix == ".ics":
        notes = _calendar(path)
    elif suffix in {".md", ".txt"}:
        notes = [(_transcript_title(path), path.read_text(encoding="utf-8"))]
    else:
        raise InboxImportError("import a .eml, .ics, .md, or .txt file")
    written = []
    for title, body in notes:
        written.append(capture(root, title, body, source="an imported file"))
    return written


def _email(path: Path) -> tuple[str, str]:
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    title = (message.get("subject") or path.stem).strip() or path.stem
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
    if not str(text).strip():
        text = "(no body)"
    sender = message.get("from") or ""
    when = message.get("date") or ""
    header = "\n".join(part for part in (f"From: {sender}" if sender else "",
                                          f"Date: {when}" if when else "") if part)
    return title[:200], (header + "\n\n" + str(text)).strip()


def _calendar(path: Path) -> list[tuple[str, str]]:
    text = _ICS_UNFOLD.sub("", path.read_text(encoding="utf-8", errors="replace"))
    events = []
    current: dict[str, str] = {}
    in_event = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if line == "END:VEVENT" and in_event:
            title = current.get("SUMMARY") or "Calendar event"
            bits = [f"{key}: {current[key]}" for key in ("DTSTART", "DTEND", "LOCATION", "DESCRIPTION")
                    if current.get(key)]
            events.append((title[:200], "\n".join(bits) or "(no details)"))
            in_event = False
            continue
        if not in_event or ":" not in line:
            continue
        key, _, value = line.partition(":")
        current[key.split(";")[0]] = value.replace("\\n", "\n")
    if not events:
        raise InboxImportError("no calendar events in that file")
    return events[:20]


def _transcript_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:200]
        if stripped:
            return stripped[:200]
    return path.stem

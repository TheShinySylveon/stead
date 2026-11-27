"""Minimal, deterministic YAML-subset frontmatter reader/writer.

Stdlib only by design: the supported subset is deliberately flat so ANY tool
can parse it (see CONVENTIONS.md). Supported syntax:

- ``key: value`` scalars (strings; optional single/double quotes)
- inline lists: ``key: [a, b, c]``
- block lists: ``key:`` followed by ``- item`` lines
- ``#`` comments and blank lines

Not supported: nested maps, anchors, multiline scalars. Values are always
strings or lists of strings; dates remain ISO strings.
"""

from __future__ import annotations

import re

# Key order used when writing, so files are deterministic and diff-friendly.
_KEY_ORDER = ["id", "type", "title", "created", "updated", "status", "project",
              "repo", "kind", "number", "url", "role", "state", "ci", "review",
              "method", "visibility", "actor", "default_branch", "contributing", "notes",
              "trigger", "reach", "code_path", "source_run",
              "related", "tags"]

_LIST_ITEM = re.compile(r"^\s*-\s+(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


def _split_inline(item: str) -> list[str]:
    inner = item.strip()[1:-1].strip()
    if not inner:
        return []
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in inner:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if quote == '"' and ch == "\\":
            buf.append(ch)
            escaped = True
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'" and not "".join(buf).strip():
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append(_unquote("".join(buf)))
            buf = []
        else:
            buf.append(ch)
    parts.append(_unquote("".join(buf)))
    return parts


def parse(text: str) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter dict, body).

    Returns ({}, full_text) when no frontmatter block is present.
    Raises ValueError on malformed blocks or unsupported syntax.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("frontmatter block opened with '---' but never closed") from exc

    meta: dict = {}
    pending_key: str | None = None
    for raw in lines[1:end]:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        item = _LIST_ITEM.match(line)
        if item and pending_key is not None:
            meta[pending_key].append(_unquote(item.group(1)))
            continue
        if ":" not in stripped:
            raise ValueError(f"unsupported frontmatter line: {raw!r}")
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        # strip trailing comments on scalar lines (naive but adequate for flat schema)
        if value.startswith("["):
            if not value.endswith("]"):
                raise ValueError(f"malformed inline list for key {key!r}")
            meta[key] = _split_inline(value)
            pending_key = None
        elif value == "":
            meta[key] = []
            pending_key = key
        else:
            meta[key] = _unquote(value)
            pending_key = None
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


_LINE_SEPARATORS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _fmt_scalar(value: str, *, in_list: bool = False) -> str:
    # Flat YAML subset forbids multiline scalars; collapsing every separator
    # that str.splitlines() treats as a line break prevents frontmatter key
    # injection or block termination when writing untrusted text.
    if any(ch in value for ch in _LINE_SEPARATORS):
        value = " ".join(value.splitlines()).strip()
    needs_quote = (
        value == "" or value != value.strip() or ":" in value or "#" in value
        or value.startswith(("[", "-", "'", '"'))
        or (in_list and ("," in value or "]" in value))
    )
    if needs_quote:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def dumps(meta: dict, body: str) -> str:
    """Serialize (frontmatter dict, body) back to markdown text.

    Keys are emitted in a stable order; unknown keys follow alphabetically.
    """
    keys = [k for k in _KEY_ORDER if k in meta]
    keys += sorted(k for k in meta if k not in _KEY_ORDER)
    out = ["---"]
    for key in keys:
        key_s = str(key)
        if any(ch in key_s for ch in _LINE_SEPARATORS + ":"):
            raise ValueError(f"invalid frontmatter key: {key!r}")
        value = meta[key]
        if isinstance(value, list):
            out.append(f"{key_s}: [{', '.join(_fmt_scalar(str(v), in_list=True) for v in value)}]")
        else:
            out.append(f"{key_s}: {_fmt_scalar(str(value))}")
    out.append("---")
    return "\n".join(out) + "\n\n" + body.lstrip("\n")

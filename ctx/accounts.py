"""Per-person sign-in for a shared server. Not a login on this computer.

Passwords are scrypt hashes in gitignored private/accounts.json. They are
never written into context markdown, and they are never returned by a list.
A session is a random cookie, not the password.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

from ctx import objects

_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class AccountError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def accounts_path(root: Path) -> Path:
    return root / "private" / "accounts.json"


def load(root: Path) -> list[dict]:
    path = accounts_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccountError(f"could not read accounts: {exc}") from exc
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list):
        raise AccountError("accounts file is not valid")
    return accounts


def count(root: Path) -> int:
    return len(load(root))


def public_list(root: Path) -> list[dict]:
    """Names and actors only. Never salts or hashes."""
    return [{"name": item.get("name") or "", "actor": item.get("actor") or ""}
            for item in load(root)]


def add(root: Path, name: str, actor_id: str, password: str | None = None) -> str:
    """Create an account. Returns the password once. Stores only the hash."""
    name = _name(name)
    actor_id = (actor_id or "").strip()
    if objects.find(root, "actor", actor_id) is None:
        raise AccountError(f"actor not found: {actor_id}")
    accounts = load(root)
    if any(item.get("name") == name for item in accounts):
        raise AccountError(f"account already exists: {name}")
    shown = password if password else secrets.token_urlsafe(18)
    if len(shown) < 12:
        raise AccountError("password must be at least 12 characters")
    salt, digest = _hash(shown)
    accounts.append({"name": name, "actor": actor_id, "salt": salt, "hash": digest})
    _save(root, accounts)
    return shown


def reset(root: Path, name: str) -> str:
    """Replace the password. Returns the new one once."""
    name = _name(name)
    accounts = load(root)
    found = next((item for item in accounts if item.get("name") == name), None)
    if found is None:
        raise AccountError(f"account not found: {name}")
    shown = secrets.token_urlsafe(18)
    salt, digest = _hash(shown)
    found["salt"] = salt
    found["hash"] = digest
    _save(root, accounts)
    return shown


def verify(root: Path, name: str, password: str) -> dict | None:
    """Return {name, actor} or None. Does not say which part was wrong."""
    wanted = (name or "").strip().lower()
    if not wanted or not password:
        return None
    for item in load(root):
        if item.get("name") != wanted:
            continue
        salt = item.get("salt") or ""
        expected = item.get("hash") or ""
        if not salt or not expected:
            return None
        try:
            _salt, digest = _hash(password, bytes.fromhex(salt))
        except ValueError:
            return None
        if secrets.compare_digest(digest, expected):
            return {"name": wanted, "actor": item.get("actor") or ""}
        return None
    return None


def _name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME.match(name):
        raise AccountError("name must be letters, numbers, and hyphens")
    return name


def _hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return salt.hex(), digest.hex()


def _save(root: Path, accounts: list[dict]) -> None:
    path = accounts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"accounts": accounts}, indent=2) + "\n", encoding="utf-8")

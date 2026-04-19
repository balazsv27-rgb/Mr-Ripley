"""
session.py — Run-scoped session directory management.

Each governance DAG run writes artifacts to a unique session directory
keyed by run_id.  This module handles session creation, pointer
management, and directory resolution.

Session layout::

    .claude/run/
        current_session.json          # pointer to active session
        sessions/
            <run_id>/
                artifacts/            # governance artifact envelopes
                debug/                # debug dumps (parse failures, etc.)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SessionError(RuntimeError):
    """Raised when session directory operations fail."""


_DEFAULT_SESSIONS_BASE = Path(".claude/run/sessions")
_DEFAULT_POINTER_PATH = Path(".claude/run/current_session.json")


def create_session_dir(
    run_id: str,
    base_dir: Path | None = None,
) -> Path:
    """Create a unique session directory for *run_id*.

    Creates::

        <base_dir>/<run_id>/artifacts/
        <base_dir>/<run_id>/debug/

    Returns the session root (``<base_dir>/<run_id>/``).
    Raises ``SessionError`` on failure.
    """
    base = base_dir or _DEFAULT_SESSIONS_BASE
    session_root = base / run_id

    try:
        (session_root / "artifacts").mkdir(parents=True, exist_ok=True)
        (session_root / "debug").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionError(
            f"Failed to create session directory {session_root}: {exc}"
        ) from exc

    return session_root


def write_session_pointer(
    session_dir: Path,
    run_id: str,
    pointer_path: Path | None = None,
) -> Path:
    """Write the active-session pointer file.

    Content::

        {"run_id": "<uuid>", "session_dir": "<path>", "started_at": "<iso>"}

    Returns the pointer path written.
    """
    dest = pointer_path or _DEFAULT_POINTER_PATH
    payload = {
        "run_id": run_id,
        "session_dir": str(session_dir),
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError as exc:
        raise SessionError(
            f"Failed to write session pointer to {dest}: {exc}"
        ) from exc

    return dest


def read_session_pointer(
    pointer_path: Path | None = None,
) -> dict[str, str]:
    """Read the active-session pointer file.

    Returns the parsed dict.  Raises ``SessionError`` if missing or malformed.
    """
    path = pointer_path or _DEFAULT_POINTER_PATH
    if not path.is_file():
        raise SessionError(f"Session pointer not found at {path}.")

    try:
        with path.open("r", encoding="utf-8") as f:
            pointer = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise SessionError(
            f"Session pointer at {path} is malformed: {exc}"
        ) from exc

    if not isinstance(pointer, dict) or "session_dir" not in pointer:
        raise SessionError(
            f"Session pointer at {path} is missing 'session_dir' key."
        )

    return pointer


def resolve_artifact_dir(pointer_path: Path | None = None) -> Path:
    """Resolve the active session's artifact directory from the pointer file."""
    pointer = read_session_pointer(pointer_path)
    return Path(pointer["session_dir"]) / "artifacts"


def resolve_debug_dir(pointer_path: Path | None = None) -> Path:
    """Resolve the active session's debug directory from the pointer file."""
    pointer = read_session_pointer(pointer_path)
    return Path(pointer["session_dir"]) / "debug"

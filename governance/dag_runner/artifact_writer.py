"""
artifact_writer.py — Canonical artifact envelope writer.

V2 writes ONLY hook-compatible artifact envelopes.
One format, no alternatives.  Must match .claude/hooks/lib/artifact_store.py.

Envelope schema:
  {
    "artifact": "<name>",
    "produced_by": "<step_id>",
    "session": "<run_id>",
    "timestamp": "<iso8601>Z",
    "data": { ... }
  }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArtifactWriterError(RuntimeError):
    """Raised when artifact writing fails."""


def write_artifact_envelope(
    name: str,
    data: dict[str, Any],
    produced_by: str,
    session: str,
    artifact_dir: Path,
) -> Path:
    """Write one canonical artifact envelope.

    No other write format exists in V2.

    Creates the artifact directory if needed.
    Returns the path written.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)

    envelope = {
        "artifact": name,
        "produced_by": produced_by,
        "session": session,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": data,
    }

    path = artifact_dir / f"{name}.json"
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2)
    except OSError as exc:
        raise ArtifactWriterError(
            f"Failed to write artifact '{name}' to {path}: {exc}"
        ) from exc

    return path


def read_artifact_envelope(
    name: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    """Read and validate a canonical artifact envelope.

    Returns the full envelope dict.
    Raises ``ArtifactWriterError`` if the file is missing or malformed.
    """
    path = artifact_dir / f"{name}.json"
    if not path.is_file():
        raise ArtifactWriterError(
            f"Artifact '{name}' not found at {path}."
        )

    try:
        with path.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise ArtifactWriterError(
            f"Artifact '{name}' at {path} could not be read: {exc}"
        ) from exc

    if not isinstance(envelope, dict) or "data" not in envelope:
        raise ArtifactWriterError(
            f"Artifact '{name}' at {path} is malformed: missing 'data' key."
        )

    return envelope

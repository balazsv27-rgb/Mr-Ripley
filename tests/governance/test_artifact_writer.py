"""Tests for governance.dag_runner.artifact_writer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.dag_runner.artifact_writer import (
    ArtifactWriterError,
    read_artifact_envelope,
    write_artifact_envelope,
)


@pytest.fixture
def artifact_dir(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


def test_write_creates_directory(artifact_dir: Path) -> None:
    assert not artifact_dir.exists()
    write_artifact_envelope(
        name="test_artifact",
        data={"key": "value"},
        produced_by="step-1",
        session="run-1",
        artifact_dir=artifact_dir,
    )
    assert artifact_dir.is_dir()


def test_write_creates_valid_envelope(artifact_dir: Path) -> None:
    path = write_artifact_envelope(
        name="test_artifact",
        data={"key": "value"},
        produced_by="step-1",
        session="run-1",
        artifact_dir=artifact_dir,
    )
    with path.open() as f:
        envelope = json.load(f)

    assert envelope["artifact"] == "test_artifact"
    assert envelope["produced_by"] == "step-1"
    assert envelope["session"] == "run-1"
    assert envelope["timestamp"].endswith("Z")
    assert envelope["data"] == {"key": "value"}


def test_envelope_matches_hook_artifact_store_format(artifact_dir: Path) -> None:
    """Verify the envelope has exactly the keys that artifact_store.py expects."""
    write_artifact_envelope(
        name="test",
        data={"x": 1},
        produced_by="s",
        session="r",
        artifact_dir=artifact_dir,
    )
    with (artifact_dir / "test.json").open() as f:
        envelope = json.load(f)

    # artifact_store.py expects: artifact, produced_by, session, timestamp, data
    required_keys = {"artifact", "produced_by", "session", "timestamp", "data"}
    assert set(envelope.keys()) == required_keys


def test_read_artifact_envelope(artifact_dir: Path) -> None:
    write_artifact_envelope(
        name="readable",
        data={"hello": "world"},
        produced_by="step-x",
        session="run-x",
        artifact_dir=artifact_dir,
    )
    envelope = read_artifact_envelope("readable", artifact_dir)
    assert envelope["data"]["hello"] == "world"


def test_read_missing_artifact(artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ArtifactWriterError, match="not found"):
        read_artifact_envelope("missing", artifact_dir)


def test_read_malformed_artifact(artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "bad.json").write_text('{"no_data_key": true}')
    with pytest.raises(ArtifactWriterError, match="malformed"):
        read_artifact_envelope("bad", artifact_dir)


def test_write_overwrites_existing(artifact_dir: Path) -> None:
    write_artifact_envelope("overwrite", {"v": 1}, "s1", "r1", artifact_dir)
    write_artifact_envelope("overwrite", {"v": 2}, "s2", "r2", artifact_dir)
    envelope = read_artifact_envelope("overwrite", artifact_dir)
    assert envelope["data"]["v"] == 2
    assert envelope["produced_by"] == "s2"

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from governance.dag_runner.models import ManifestSpec, WorkflowPackageSpec


DEFAULT_WORKFLOW_PATH = Path(".claude/workflows/system-orchestration.yaml")


class LoaderError(RuntimeError):
    """Raised when workflow loading fails in a fail-closed way."""


@dataclass(frozen=True)
class LoadedWorkflowPackages:
    """Container for the root manifest and all loaded package files."""

    workflow_path: Path
    manifest: ManifestSpec
    packages: list[WorkflowPackageSpec]


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise LoaderError(f"YAML file not found: {path}")

    if not path.is_file():
        raise LoaderError(f"Expected a file but got non-file path: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoaderError(f"Failed to read YAML file {path}: {exc}") from exc

    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise LoaderError(f"Invalid YAML in {path}: {exc}") from exc

    if payload is None:
        raise LoaderError(f"YAML file is empty: {path}")

    if not isinstance(payload, dict):
        raise LoaderError(
            f"Top-level YAML structure must be a mapping/dict in {path}, "
            f"got {type(payload).__name__}"
        )

    return payload


def _extract_package_file_list(payload: dict[str, Any]) -> list[str]:
    """
    Extract package filenames from the root workflow file.

    Supported V1 layouts:
    - assembly.packages:
        - path: packages/foo.yaml
          section: foo
    - package_files: ["a.yaml", ...]
    - packages: ["a.yaml", ...]
    - workflow.packages: ["a.yaml", ...]
    """

    # Preferred current layout: assembly.packages
    assembly = payload.get("assembly")
    if isinstance(assembly, dict) and "packages" in assembly:
        candidates = assembly["packages"]

        if not isinstance(candidates, list):
            raise LoaderError(
                "assembly.packages must be a list of package entries."
            )

        normalized: list[str] = []
        for item in candidates:
            if not isinstance(item, dict):
                raise LoaderError(
                    f"assembly.packages entries must be mappings/dicts, got {type(item).__name__}: {item!r}"
                )

            package_path = item.get("path")
            if not isinstance(package_path, str) or not package_path.strip():
                raise LoaderError(
                    f"assembly.packages entry missing valid 'path': {item!r}"
                )

            normalized.append(package_path.strip())

        return normalized

    # Backward-compatible fallback layouts
    candidates: list[Any] = []

    if "package_files" in payload:
        candidates = payload["package_files"]
    elif "packages" in payload:
        candidates = payload["packages"]
    elif isinstance(payload.get("workflow"), dict) and "packages" in payload["workflow"]:
        candidates = payload["workflow"]["packages"]

    if not candidates:
        raise LoaderError(
            "Could not find package file list in root workflow YAML. "
            "Expected 'assembly.packages' or one of: 'package_files', 'packages', or 'workflow.packages'."
        )

    if not isinstance(candidates, list):
        raise LoaderError(
            f"Package file list must be a list, got {type(candidates).__name__}"
        )

    normalized: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            raise LoaderError(
                f"Package file entries must be strings, got {type(item).__name__}: {item!r}"
            )
        cleaned = item.strip()
        if not cleaned:
            raise LoaderError("Package file list contains an empty string entry.")
        normalized.append(cleaned)

    return normalized


def _build_manifest_spec(
    payload: dict[str, Any],
    workflow_path: Path,
    package_files: list[str],
) -> ManifestSpec:
    workflow_name = (
        payload.get("workflow_name")
        or payload.get("name")
        or workflow_path.stem
    )

    workflow_version = payload.get("workflow_version") or payload.get("version")
    assembly_mode = payload.get("assembly_mode") or payload.get("mode")
    package_dir = payload.get("package_dir")

    return ManifestSpec(
        workflow_name=str(workflow_name),
        workflow_version=str(workflow_version) if workflow_version is not None else None,
        assembly_mode=str(assembly_mode) if assembly_mode is not None else None,
        package_dir=str(package_dir) if package_dir is not None else None,
        package_files=package_files,
        raw=payload,
    )


def _resolve_package_dir(workflow_path: Path, manifest: ManifestSpec) -> Path:
    """
    Resolve where package YAML files live.

    Precedence:
    1. explicit manifest.package_dir
    2. sibling 'packages' directory next to workflow file
    """
    if manifest.package_dir:
        package_dir = Path(manifest.package_dir)
        if not package_dir.is_absolute():
            package_dir = (workflow_path.parent / package_dir).resolve()
        return package_dir

    return (workflow_path.parent / "packages").resolve()


def load_workflow_packages(
    workflow_path: str | Path = DEFAULT_WORKFLOW_PATH,
) -> LoadedWorkflowPackages:
    """
    Load the root workflow YAML and all referenced package YAML files.

    This function is intentionally conservative and fail-closed.
    It only loads files and returns structured package objects.
    """
    workflow_path = Path(workflow_path).resolve()
    root_payload = _read_yaml_file(workflow_path)

    package_files = _extract_package_file_list(root_payload)
    manifest = _build_manifest_spec(root_payload, workflow_path, package_files)
    package_dir = _resolve_package_dir(workflow_path, manifest)

    if not package_dir.exists():
        raise LoaderError(f"Package directory does not exist: {package_dir}")

    if not package_dir.is_dir():
        raise LoaderError(f"Package directory is not a directory: {package_dir}")

    loaded_packages: list[WorkflowPackageSpec] = []

    for package_name in package_files:
        package_path = Path(package_name)

        if not package_path.is_absolute():
            if package_path.parts and package_path.parts[0] == "packages":
                package_path = (workflow_path.parent / package_path).resolve()
            else:
                package_path = (package_dir / package_path).resolve()

        payload = _read_yaml_file(package_path)

        loaded_packages.append(
            WorkflowPackageSpec(
                package_name=package_name,
                file_path=str(package_path),
                content=payload,
            )
        )

    return LoadedWorkflowPackages(
        workflow_path=workflow_path,
        manifest=manifest,
        packages=loaded_packages,
    )
"""
prompt_assembly.py — Assemble bounded prompt context for each workflow step.

Constructs a ``PromptAssemblyContext`` with deterministic priority-ordered
assembly and token budget enforcement.

Assembly order (priority, highest first):
1. Skill SKILL.md content (never truncated)
2. Agent .md file content
3. Upstream artifact payloads (ordered by production step in DAG order)
4. Canonical document paths (from agent.consumes)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from governance.dag_runner.path_policy import PathPolicy

from governance.dag_runner.agent_resolver import (
    AgentResolverError,
    load_agent_file,
    resolve_agent,
    resolve_skill_content,
)
from governance.dag_runner.skill_resolver import SkillResolverError
from governance.dag_runner.input_bounding import (
    BoundedInput,
    bound_inputs,
    estimate_tokens,
)
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    GovernanceRunState,
    PromptContext,
    WorkflowStep,
)


class PromptAssemblyError(RuntimeError):
    """Raised when prompt assembly fails."""


# ---------------------------------------------------------------------------
# Step-specific artifact input projections
# ---------------------------------------------------------------------------
# Maps step_name → {artifact_name → list of field names to keep}.
# When a projection is defined, only those fields are retained in the
# assembled prompt payload.  Unlisted artifacts pass through unchanged.
# This reduces assembled prompt size for steps that consume large upstream
# artifacts but only need a subset of their fields.

_STEP_INPUT_PROJECTIONS: dict[str, dict[str, list[str]]] = {
    "route-claims-by-role": {
        # governance_context: only need request text and run metadata
        "governance_context": [
            "produced_by", "run_id", "request_text", "request_source",
            "bootstrap_status", "workflow_name", "execution_mode",
        ],
        # claim_classification_map: keep classified claims and top-level status;
        # drop verbose evidence chains, source excerpts, and internal notes
        "claim_classification_map": [
            "produced_by", "claims", "classifications", "status",
            "overall_classification", "claim_count", "inference_used",
        ],
        # normalized_terminology_map: keep normalized terms and status;
        # drop per-term analysis detail and variant lists
        "normalized_terminology_map": [
            "produced_by", "normalized_terms", "terms", "status",
            "term_count", "inference_used",
        ],
        # interpretation_policy.claim_routing: keep as-is (already small)
    },
}


# ---------------------------------------------------------------------------
# Phase-check compact transform projections
# ---------------------------------------------------------------------------
# Deep structural transforms for steps that need more than top-level field
# filtering.  Each function receives the full artifact payload and returns
# a compact projection retaining only governance-relevant fields.


def _compact_claim_classification_for_phase_check(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Extract compact phase-check projection from claim_classification_map.

    Retains governance-relevant summary fields and compact claim identifiers.
    Drops verbose detail, reason text, and per-claim rationale/evidence.

    Supports two schema shapes:
    - nested: ``payload["request_classification"]["claims"]`` / ``["summary"]``
    - flat (legacy): ``payload["claims"]`` / ``payload["summary"]``
    """
    # Try nested shape first (real artifact), fall back to flat shape (legacy)
    rc = payload.get("request_classification", {})
    claims = rc.get("claims") or payload.get("claims")
    summary = rc.get("summary") or payload.get("summary")

    if claims is None and summary is None:
        return payload  # structural/minimal payload — pass through

    if summary is None:
        summary = {}
    if claims is None:
        claims = []

    compact: dict[str, Any] = {
        "produced_by": payload.get("produced_by"),
        "status": payload.get("status"),
        "dominant_scope": summary.get("dominant_scope"),
        "touches_current_truth": summary.get("touches_current_truth"),
        "touches_target_architecture": summary.get("touches_target_architecture"),
        "possible_blocking_conditions": summary.get(
            "possible_blocking_conditions", [],
        ),
        "claim_count": len(claims),
    }
    if claims:
        compact["claims_compact"] = [
            {
                k: c[k]
                for k in ("claim_id", "classification", "claim_scope")
                if k in c
            }
            for c in claims
        ]
    return compact


def _extract_role_citation_fields(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    """Extract overall_status, summary, and checked_claims from role_citation_verdict.

    Supports two schema shapes:
    - nested: ``payload["role_matched_citation_status"]["overall_status"]``, etc.
    - flat: ``payload["overall_status"]``, ``payload["checked_claims"]``, etc.

    Returns ``(root, summary, checked)`` where *root* contains the top-level
    status fields.  Returns ``(None, {}, [])`` when neither shape is detected
    (structural/minimal payload).
    """
    rcs = payload.get("role_matched_citation_status")
    if rcs is not None:
        # Nested shape
        return rcs, rcs.get("summary", {}), rcs.get("checked_claims", [])

    # Try flat shape — must have at least overall_status or checked_claims
    if "overall_status" in payload or "checked_claims" in payload:
        return payload, payload.get("summary", {}), payload.get("checked_claims", [])

    return None, {}, []


def _compact_role_citation_for_phase_check(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Extract compact phase-check projection from role_citation_verdict.

    Retains overall citation status, conflict flags, and guard action.
    Drops per-claim notes and verbose summary notes.

    Supports nested (``role_matched_citation_status``) and flat schemas.
    """
    root, summary, checked = _extract_role_citation_fields(payload)
    if root is None:
        return payload  # structural/minimal payload — pass through

    compact: dict[str, Any] = {
        "produced_by": payload.get("produced_by"),
        "overall_status": root.get("overall_status"),
        "source_authority_conflict_detected": root.get(
            "source_authority_conflict_detected",
        ),
        "recommended_guard_action": summary.get("recommended_guard_action"),
        "role_mismatch_detected": summary.get("role_mismatch_detected"),
        "canonical_conflict_unresolved": summary.get(
            "canonical_conflict_unresolved",
        ),
        "requires_doc_sync_escalation": summary.get(
            "requires_doc_sync_escalation",
        ),
        "checked_claim_count": len(checked),
    }
    if checked:
        compact["blocking_claims"] = [
            c.get("claim_id") for c in checked
            if c.get("verdict") in ("blocking", "block")
        ]
        compact["review_only_claims"] = [
            c.get("claim_id") for c in checked
            if c.get("verdict") == "review_only"
        ]
        compact["compliant_claims"] = [
            c.get("claim_id") for c in checked
            if c.get("verdict") in ("compliant", "pass")
        ]
    return compact


# ---------------------------------------------------------------------------
# Snapshot-contract-check compact transform projections
# ---------------------------------------------------------------------------
# Deep structural transforms for snapshot-contract-check.  These retain only
# contract-validation-relevant fields from upstream artifacts, dropping verbose
# per-claim narratives and long-form reasoning.


def _compact_role_citation_for_snapshot_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Extract compact snapshot-contract projection from role_citation_verdict.

    Retains governance status flags, blocking claim ids, escalation info,
    and block reason summaries.  Drops per-claim narratives, verbose notes,
    and full checked_claims detail.

    Supports nested (``role_matched_citation_status``) and flat schemas.
    """
    root, summary, checked = _extract_role_citation_fields(payload)
    if root is None:
        return payload  # structural/minimal payload — pass through

    compact: dict[str, Any] = {
        "produced_by": payload.get("produced_by"),
        "overall_status": root.get("overall_status"),
        "source_authority_conflict_detected": root.get(
            "source_authority_conflict_detected",
        ),
        "recommended_guard_action": summary.get("recommended_guard_action"),
        "canonical_conflict_unresolved": summary.get(
            "canonical_conflict_unresolved",
        ),
        "checked_claim_count": len(checked),
        "escalation_required": summary.get("escalation_required", False),
        "escalation_target": summary.get("escalation_target"),
    }
    # Blocking claim ids and compact block reasons
    blocking_ids = summary.get("blocking_claims", [])
    if blocking_ids:
        compact["blocking_claims"] = blocking_ids
    elif checked:
        compact["blocking_claims"] = [
            c.get("claim_id") for c in checked
            if c.get("verdict") in ("blocking", "block", "RC-4")
        ]
    block_reasons = summary.get("block_reasons")
    if block_reasons:
        compact["block_reasons_summary"] = block_reasons
    return compact


def _compact_phase_alignment_for_snapshot_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Extract compact snapshot-contract projection from phase_alignment_status.

    Retains overall verdict, gate references, blocking reasons, and summary
    risk flags.  Drops per-claim long-form reasoning and verbose explanations.
    """
    if "allowed" not in payload and "alignment_status" not in payload:
        return payload  # structural/minimal payload — pass through
    summary = payload.get("summary", {})

    compact: dict[str, Any] = {
        "produced_by": payload.get("produced_by"),
        "allowed": payload.get("allowed"),
        "alignment_status": payload.get("alignment_status"),
        "gate_reference": payload.get("gate_reference"),
        "blocking_reason_if_any": payload.get("blocking_reason_if_any"),
        "upstream_block_inherited": summary.get("upstream_block_inherited"),
        "snapshot_boundary_risk": summary.get("snapshot_boundary_risk"),
        "scope_exceeds_current_allowance": summary.get(
            "scope_exceeds_current_allowance",
        ),
        "blocking_claims_summary": summary.get("blocking_claims_summary"),
        "ambiguous_claims_summary": summary.get("ambiguous_claims_summary"),
        "recommended_next_step": summary.get("recommended_next_step"),
    }
    return compact


# Transform-based projections — step_name → {artifact_name → transform_fn}.
# Applied before field-list projections in _project_artifact_payload.
_STEP_INPUT_TRANSFORMS: dict[str, dict[str, Any]] = {
    "phase-check": {
        "claim_classification_map": _compact_claim_classification_for_phase_check,
        "role_citation_verdict": _compact_role_citation_for_phase_check,
    },
    "snapshot-contract-check": {
        "role_citation_verdict": _compact_role_citation_for_snapshot_contract,
        "phase_alignment_status": _compact_phase_alignment_for_snapshot_contract,
    },
}


def _project_artifact_payload(
    step_name: str,
    artifact_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply step-specific projection to an artifact payload.

    Checks transform-based projections first (deep structural transforms),
    then falls back to field-list projections (top-level field filtering).
    Returns the payload unchanged when no projection is defined.
    """
    # Transform-based projection (deep structural transforms)
    transforms = _STEP_INPUT_TRANSFORMS.get(step_name)
    if transforms is not None:
        transform_fn = transforms.get(artifact_name)
        if transform_fn is not None:
            return transform_fn(payload)

    # Field-list projection (top-level field filtering)
    step_projections = _STEP_INPUT_PROJECTIONS.get(step_name)
    if step_projections is None:
        return payload
    fields = step_projections.get(artifact_name)
    if fields is None:
        return payload
    return {k: v for k, v in payload.items() if k in fields}


def _apply_step_projections(
    step_name: str,
    raw_inputs: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Apply step-specific projections and collect size metadata.

    Returns ``(projected_inputs, projection_log)`` where each log entry
    records the artifact name and original/projected char/token counts.
    """
    import json as _json

    projected: dict[str, dict[str, Any]] = {}
    log: list[dict[str, Any]] = []

    for name, payload in raw_inputs.items():
        result = _project_artifact_payload(step_name, name, payload)
        projected[name] = result
        if result is not payload:
            orig_ser = _json.dumps(payload, indent=2)
            proj_ser = _json.dumps(result, indent=2)
            log.append({
                "artifact": name,
                "original_chars": len(orig_ser),
                "original_tokens": estimate_tokens(orig_ser),
                "projected_chars": len(proj_ser),
                "projected_tokens": estimate_tokens(proj_ser),
            })

    return projected, log


# Section delimiters for the assembled prompt text.
_SECTION_DELIM = "\n\n" + "=" * 60 + "\n"


def _get_repo_root() -> Path:
    """Resolve the project repo root (two levels up from governance/dag_runner/)."""
    return Path(__file__).resolve().parent.parent.parent


def _resolve_spec_path(
    spec: AssembledWorkflowSpec,
    dotted_name: str,
) -> dict[str, Any] | None:
    """Resolve a dotted name against spec-level data fields.

    Supports paths like ``interpretation_policy.claim_routing`` which resolve
    to ``spec.interpretation_policy.raw["data"]["claim_routing"]``.

    Returns ``None`` when the path does not match any spec attribute or field.
    """
    parts = dotted_name.split(".", 1)
    if len(parts) != 2:
        return None
    section, field_name = parts

    spec_attr = getattr(spec, section, None)
    if spec_attr is None:
        return None

    raw = getattr(spec_attr, "raw", None)
    if raw is None or not isinstance(raw, dict):
        return None

    # Prefer data sub-key (standard YAML package layout), fall back to raw root.
    data = raw.get("data", raw)
    if field_name not in data:
        return None

    value = data[field_name]
    if isinstance(value, dict):
        return value
    # Wrap non-dict values for consistent artifact-like shape.
    return {"value": value}


def _gather_artifact_inputs(
    step: WorkflowStep,
    agent: AgentSpec | None,
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec | None = None,
) -> dict[str, dict[str, Any]]:
    """Gather upstream artifact payloads for this step's inputs.

    When *spec* is provided, dotted input names (e.g.
    ``interpretation_policy.claim_routing``) that are absent from
    ``run_state.artifacts`` are resolved against the assembled spec.
    """
    result: dict[str, dict[str, Any]] = {}

    # Collect input names from step.raw and agent.consumes
    input_names: list[str] = []
    raw_inputs = step.raw.get("inputs", []) or []
    if isinstance(raw_inputs, list):
        input_names.extend(str(i) for i in raw_inputs)

    if agent is not None:
        for c in agent.consumes:
            if c not in input_names:
                input_names.append(c)

    for name in input_names:
        artifact = run_state.artifacts.get(name)
        if artifact is not None and artifact.status == "present":
            result[name] = artifact.payload
        elif spec is not None and "." in name:
            resolved = _resolve_spec_path(spec, name)
            if resolved is not None:
                result[name] = resolved

    return result


def _gather_document_paths(
    agent: AgentSpec | None,
    repo_root: Path,
) -> list[str]:
    """Gather canonical document paths from agent.consumes.

    Only includes paths that resolve to existing files.
    """
    if agent is None:
        return []

    paths: list[str] = []
    for consume_name in agent.consumes:
        # Skip artifact references (artifacts are handled separately)
        if consume_name.startswith("canonical_docs"):
            continue

        # Check common document locations
        for candidate in [
            repo_root / consume_name,
            repo_root / "Documentation" / consume_name,
        ]:
            if candidate.is_file():
                paths.append(str(candidate))
                break

    return paths


def _validate_file_read(
    path: Path,
    path_policy: "PathPolicy | None",
) -> None:
    """Validate a file path against the active policy, if any.

    Raises ``PathPolicyViolation`` when the path violates the policy.
    No-op when ``path_policy is None`` (V2A backward compat / mock usage).
    """
    if path_policy is None:
        return
    from governance.dag_runner.path_policy import validate_path
    validate_path(path, path_policy)


def assemble_step_prompt(
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState,
    repo_root: Path | None = None,
    token_budget: int = 100_000,
    path_policy: "PathPolicy | None" = None,
) -> dict[str, Any]:
    """Assemble bounded prompt context for a single workflow step.

    Returns a dict with:
      - ``agent``: resolved AgentSpec (or None)
      - ``skill_content``: concatenated SKILL.md content
      - ``agent_instructions``: agent .md file content
      - ``artifact_inputs``: upstream artifact payloads
      - ``document_paths``: resolved canonical doc paths
      - ``token_budget``: the budget
      - ``token_estimate``: estimated total token count after bounding
      - ``truncated``: whether any input was truncated
      - ``truncation_events``: list of truncation events (if any)

    When ``path_policy`` is provided, every file read is validated
    against the policy before reading.  Violations raise
    ``PathPolicyViolation`` (fail-closed).
    """
    if repo_root is None:
        repo_root = _get_repo_root()

    # Resolve agent
    agent = resolve_agent(step, spec)

    # Resolve skill content (path policy validated inside agent_resolver
    # at the skill_resolver level; we validate the resolved paths here)
    skill_content = ""
    if agent is not None:
        try:
            # Validate skill file paths before reading
            if path_policy is not None and agent.skill_bindings:
                for skill_name in agent.skill_bindings:
                    skill_path = repo_root / ".claude" / "skills" / skill_name / "SKILL.md"
                    _validate_file_read(skill_path, path_policy)
            skill_content = resolve_skill_content(agent, repo_root)
        except (AgentResolverError, SkillResolverError):
            skill_content = ""

    # Load agent instructions
    agent_instructions = ""
    if agent is not None:
        try:
            agent_path = repo_root / ".claude" / "agents" / f"{agent.name}.md"
            _validate_file_read(agent_path, path_policy)
            agent_instructions = load_agent_file(agent.name, repo_root)
        except AgentResolverError:
            agent_instructions = ""

    # Gather raw artifact inputs then apply step-specific projections
    raw_artifact_inputs = _gather_artifact_inputs(step, agent, run_state, spec=spec)
    artifact_inputs, projection_log = _apply_step_projections(
        step.name, raw_artifact_inputs,
    )

    # Gather document paths
    document_paths = _gather_document_paths(agent, repo_root)

    # Build bounded inputs
    bounded = []
    if skill_content:
        bounded.append(BoundedInput(
            name="skill_instructions",
            content=skill_content,
            priority=1,
        ))
    if agent_instructions:
        bounded.append(BoundedInput(
            name="agent_instructions",
            content=agent_instructions,
            priority=2,
        ))

    # Artifact payloads as serialized JSON strings
    import json
    for art_name, art_payload in artifact_inputs.items():
        bounded.append(BoundedInput(
            name=f"artifact:{art_name}",
            content=json.dumps(art_payload, indent=2),
            priority=3,
        ))

    # Document content (read files with path policy validation)
    for doc_path in document_paths:
        try:
            resolved = Path(doc_path).resolve()
            _validate_file_read(resolved, path_policy)
            doc_content = resolved.read_text(encoding="utf-8")
            bounded.append(BoundedInput(
                name=f"doc:{doc_path}",
                content=doc_content,
                priority=4,
            ))
        except (OSError, UnicodeDecodeError):
            pass

    # Apply token budget
    bounding_result = bound_inputs(bounded, token_budget)

    return {
        "agent": agent,
        "step_name": step.name,
        "expected_outputs": list(step.outputs),
        "skill_content": skill_content if not any(
            b.name == "skill_instructions" and b.truncated for b in bounding_result.inputs
        ) else next(
            (b.content for b in bounding_result.inputs if b.name == "skill_instructions"), ""
        ),
        "agent_instructions": next(
            (b.content for b in bounding_result.inputs if b.name == "agent_instructions"),
            "",
        ),
        "artifact_inputs": artifact_inputs,
        "document_paths": document_paths,
        "token_budget": token_budget,
        "token_estimate": bounding_result.total_tokens,
        "truncated": bounding_result.truncated,
        "truncation_events": bounding_result.truncation_events,
        "projection_log": projection_log,
    }


def build_prompt_composition_metadata(context: dict[str, Any]) -> dict[str, Any]:
    """Extract prompt composition metadata from an assembly context dict.

    Returns a dict of diagnostic fields suitable for inclusion in
    timeout debug artifacts and execution trace events.

    Includes ``input_contributions`` — a per-input breakdown of chars and
    estimated tokens — and ``assembled_prompt_chars`` / ``assembled_prompt_tokens``
    for the final concatenated prompt text.
    """
    import json as _json

    artifact_inputs = context.get("artifact_inputs", {})
    document_paths = context.get("document_paths", [])
    skill_content = context.get("skill_content", "")
    agent_instructions = context.get("agent_instructions", "")

    # Per-input contribution breakdown
    input_contributions: dict[str, dict[str, int]] = {}
    if skill_content:
        input_contributions["skill_instructions"] = {
            "chars": len(skill_content),
            "estimated_tokens": estimate_tokens(skill_content),
        }
    if agent_instructions:
        input_contributions["agent_instructions"] = {
            "chars": len(agent_instructions),
            "estimated_tokens": estimate_tokens(agent_instructions),
        }
    for art_name, art_payload in artifact_inputs.items():
        serialized = _json.dumps(art_payload, indent=2)
        input_contributions[f"artifact:{art_name}"] = {
            "chars": len(serialized),
            "estimated_tokens": estimate_tokens(serialized),
        }

    # Assembled prompt total size
    assembled_text = build_prompt_text(context)
    assembled_chars = len(assembled_text)
    assembled_tokens = estimate_tokens(assembled_text)

    # Projection diagnostics — original vs projected sizes for transformed artifacts
    projection_log = context.get("projection_log", [])
    projected_artifact_names = [p["artifact"] for p in projection_log]
    input_contributions_original: dict[str, dict[str, int]] = {}
    input_contributions_projected: dict[str, dict[str, int]] = {}
    for entry in projection_log:
        art_key = f"artifact:{entry['artifact']}"
        input_contributions_original[art_key] = {
            "chars": entry["original_chars"],
            "estimated_tokens": entry["original_tokens"],
        }
        input_contributions_projected[art_key] = {
            "chars": entry["projected_chars"],
            "estimated_tokens": entry["projected_tokens"],
        }

    return {
        "step_name": context.get("step_name", ""),
        "skill_content_length": len(skill_content),
        "agent_instructions_length": len(agent_instructions),
        "artifact_input_names": sorted(artifact_inputs.keys()),
        "artifact_input_count": len(artifact_inputs),
        "document_paths": list(document_paths),
        "document_count": len(document_paths),
        "token_estimate": context.get("token_estimate", 0),
        "token_budget": context.get("token_budget", 100_000),
        "truncated": context.get("truncated", False),
        "truncation_events": context.get("truncation_events", []),
        "expected_outputs": context.get("expected_outputs", []),
        # Per-input contribution diagnostics
        "input_contributions": input_contributions,
        "assembled_prompt_chars": assembled_chars,
        "assembled_prompt_tokens": assembled_tokens,
        # Projection diagnostics
        "projected_artifact_names": projected_artifact_names,
        "input_contributions_original": input_contributions_original,
        "input_contributions_projected": input_contributions_projected,
    }


def build_prompt_text(context: dict[str, Any]) -> str:
    """Build the assembled prompt text from a prompt assembly context dict.

    Concatenates sections in priority order with clear delimiters:
    1. Skill instructions (highest priority)
    2. Agent instructions
    3. Upstream artifact payloads (serialized JSON)
    4. Document content

    Each non-empty section is separated by a delimiter for parseability.
    """
    import json

    sections: list[str] = []

    skill = context.get("skill_content", "")
    if skill:
        sections.append(f"[SKILL INSTRUCTIONS]{_SECTION_DELIM}{skill}")

    agent_inst = context.get("agent_instructions", "")
    if agent_inst:
        sections.append(f"[AGENT INSTRUCTIONS]{_SECTION_DELIM}{agent_inst}")

    artifacts = context.get("artifact_inputs", {})
    if artifacts:
        art_text = json.dumps(artifacts, indent=2)
        sections.append(f"[UPSTREAM ARTIFACTS]{_SECTION_DELIM}{art_text}")

    doc_paths = context.get("document_paths", [])
    if doc_paths:
        sections.append(f"[DOCUMENT PATHS]{_SECTION_DELIM}" + "\n".join(doc_paths))

    # Output format specification — required for backend-dispatched steps
    expected_outputs = context.get("expected_outputs", [])
    step_name = context.get("step_name", "")
    if expected_outputs and step_name:
        artifact_examples = ", ".join(
            f'"{o}": {{"produced_by": "{step_name}", ...your analysis fields...}}'
            for o in expected_outputs
        )

        if context.get("use_structured_output"):
            # Structured output mode: --json-schema enforces shape at the
            # API level, so the verbose "do NOT wrap / do NOT include" rules
            # are unnecessary.  Keep only a minimal reminder.
            format_section = (
                f"[REQUIRED OUTPUT FORMAT]{_SECTION_DELIM}"
                f"Respond with a JSON object matching this structure:\n"
                f'{{"artifacts": {{{artifact_examples}}}}}\n\n'
                f'Each artifact MUST include "produced_by": "{step_name}".\n'
                f"Produce ALL listed artifacts: {', '.join(expected_outputs)}."
            )
        else:
            format_section = (
                f"[REQUIRED OUTPUT FORMAT]{_SECTION_DELIM}"
                f"CRITICAL: Your entire response must be a single valid JSON object and nothing else.\n"
                f"Do NOT include any text, explanation, or commentary before or after the JSON.\n"
                f"Do NOT wrap in markdown code fences.\n"
                f"Do NOT attempt to read files like ctx.json, governance_context.json, or any artifact files — "
                f"all upstream artifacts are already provided in the [UPSTREAM ARTIFACTS] section above.\n"
                f"Even if you cannot fully complete the analysis, you MUST still respond with ONLY the JSON object.\n\n"
                f"Required structure:\n"
                f'{{"artifacts": {{{artifact_examples}}}}}\n\n'
                f"Rules:\n"
                f'- Each artifact MUST be a JSON object with a "produced_by" field set to "{step_name}".\n'
                f"- Include your analysis results as additional fields within each artifact object.\n"
                f"- You must produce ALL of the listed artifacts: {', '.join(expected_outputs)}.\n"
                f"- The top-level response must be a single JSON object with one key: \"artifacts\".\n"
                f'- Artifact names must match exactly: {", ".join(expected_outputs)}.'
            )
        sections.append(format_section)

    return (_SECTION_DELIM).join(sections)


def build_prompt_context(context: dict[str, Any]) -> PromptContext:
    """Convert a prompt assembly dict to a ``PromptContext``."""
    return PromptContext(
        assembled_prompt=build_prompt_text(context),
        agent=context.get("agent"),
        skill_content=context.get("skill_content", ""),
        agent_instructions=context.get("agent_instructions", ""),
        artifact_inputs=context.get("artifact_inputs", {}),
        document_paths=context.get("document_paths", []),
        token_budget=context.get("token_budget", 100_000),
        token_estimate=context.get("token_estimate", 0),
        truncated=context.get("truncated", False),
        truncation_events=context.get("truncation_events", []),
    )

"""
role_citation.py — Deterministic role-matched citation verdict synthesis.

Produces ``role_citation_verdict`` structurally from:
- claim_classification_map (upstream classified claims)
- governance_context.canonical_doc_extracts (bounded document evidence)
- governance_context.code_context (implementation evidence)
- governance_context.runtime_context (runtime evidence)
- interpretation_policy.claim_routing (routing table)

Design constraints:
- NO LLM invocation — pure deterministic policy evaluation.
- Preserves upstream claim IDs exactly (c1, c2, ...).
- Does not invent new claim IDs (no C-001, C-002).
- Decomposed sub-claims use suffixes: c3.a, c3.b with original_claim_id.
- Strong implementation claims require SYSTEM_IMPLEMENTATION_RECORD_v1.md.
- Negative guard claims can be compliant from canonical docs + code_context.
- Code evidence corroborates but does not replace role-matched canonical docs.
- inference_used=false when all inputs are present and direct-observed.
"""
from __future__ import annotations

from typing import Any

from governance.dag_runner.models import GovernanceRunState, WorkflowStep


# ---------------------------------------------------------------------------
# Claim-type routing table (fallback when interpretation_policy absent)
# ---------------------------------------------------------------------------

_DEFAULT_ROUTING: dict[str, str] = {
    "architecture": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
    "implementation": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
    "limitation": "SYSTEM_LIMITATIONS_AND_APPROXIMATIONS_v1.md",
    "technical_constraint": "SYSTEM_TECHNICAL_HANDBOOK_v1.md",
    "documentation_consistency": "DOCUMENTATION_VERIFICATION_MATRIX_v1.md",
    "collaborator_workflow": "README_LAYER2.md",
    "governance": "CLAUDE.md",
    "readiness": "SYSTEM_ARCHITECTURE_AND_BUILD_SEQUENCE_v1.md",
    "historical": "SYSTEM_IMPLEMENTATION_RECORD_v1.md",
    "top_level_orientation": "README_v1.md",
}

# Maps interpretation_policy.claim_routing keys to our claim_type keys
_POLICY_KEY_TO_TYPE: dict[str, str] = {
    "architecture_claims": "architecture",
    "implementation_claims": "implementation",
    "limitation_claims": "limitation",
    "technical_constraint_claims": "technical_constraint",
    "documentation_consistency_claims": "documentation_consistency",
    "collaborator_workflow_claims": "collaborator_workflow",
    "top_level_orientation_claims": "top_level_orientation",
}

# Claim scopes / evidence classes that indicate a negative guard
_NEGATIVE_GUARD_KEYWORDS: frozenset[str] = frozenset({
    "not implemented",
    "not ready",
    "not claimed",
    "not built",
    "is not",
    "not a semantic rename",
    "not a constitutional amendment",
    "explicit constraint",
    "explicit guard",
    "preserved",
})

# Strong claim indicator keywords
_STRONG_CLAIM_KEYWORDS: frozenset[str] = frozenset({
    "is complete",
    "is implemented",
    "is operational",
    "has been completed",
    "have been closed",
    "has been closed",
    "needs to be updated",
    "requires alignment",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_routing_table(
    spec_routing: dict[str, Any] | None,
) -> dict[str, str]:
    """Build the claim-type → canonical-doc routing table.

    Prefers interpretation_policy.claim_routing when available;
    falls back to _DEFAULT_ROUTING.
    """
    if spec_routing is None:
        return dict(_DEFAULT_ROUTING)

    table = dict(_DEFAULT_ROUTING)
    for policy_key, doc_name in spec_routing.items():
        claim_type = _POLICY_KEY_TO_TYPE.get(policy_key)
        if claim_type and isinstance(doc_name, str):
            table[claim_type] = doc_name
    return table


def _classify_claim_type(claim: dict[str, Any]) -> str:
    """Infer claim type from claim text, scope, and evidence class."""
    text = claim.get("claim_text", "").lower()
    scope = claim.get("claim_scope", "").lower()
    evidence_class = claim.get("evidence_class", "").lower()

    # Negative guards
    if any(kw in text for kw in _NEGATIVE_GUARD_KEYWORDS):
        # Still need a routing type — infer from content
        if "layer-3" in text or "layer 3" in text:
            return "architecture"
        if "execution" in text or "readiness" in text:
            return "readiness"
        if "rename" in text or "amendment" in text or "terminology" in text:
            return "governance"
        return "governance"

    # Documentation sync claims (check BEFORE implementation — "documentation
    # needs to be updated" is a doc-sync claim, not an implementation claim)
    if "documentation" in text and ("alignment" in text or "update" in text or "align" in text):
        return "documentation_consistency"
    if "verification" in text and "delta" in text:
        return "documentation_consistency"

    # Implementation claims
    if "implementation" in scope or "implementation" in evidence_class:
        return "implementation"
    if any(kw in text for kw in (
        "sp500", "todo", "fix", "complete", "closed", "adapter", "implemented",
    )):
        return "implementation"

    # Architecture
    if "architecture" in text or "boundary" in text or "phase" in text:
        return "architecture"

    # Limitation
    if "limitation" in text or "approximation" in text:
        return "limitation"

    # Default: documentation_consistency for doc-sync requests
    if scope == "current-state":
        return "implementation"

    return "documentation_consistency"


def _is_negative_guard(claim: dict[str, Any]) -> bool:
    """Return True if the claim is a negative guard (preserving a constraint)."""
    text = claim.get("claim_text", "").lower()
    return any(kw in text for kw in _NEGATIVE_GUARD_KEYWORDS)


def _is_strong_claim(claim: dict[str, Any]) -> bool:
    """Return True if the claim makes a strong assertion requiring evidence."""
    text = claim.get("claim_text", "").lower()
    if _is_negative_guard(claim):
        return True  # guards are strong but may be easily satisfied
    return any(kw in text for kw in _STRONG_CLAIM_KEYWORDS)


def _doc_extract_supports_claim(
    doc_extract: dict[str, Any] | None,
    claim: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check if a canonical doc extract has keyword sections supporting a claim.

    Returns (supported, provided_sources) where supported means relevant
    keyword sections exist in the extract.
    """
    if doc_extract is None or doc_extract.get("status") == "missing":
        return False, []

    keyword_sections = doc_extract.get("keyword_sections", [])
    if not keyword_sections:
        return False, []

    text = claim.get("claim_text", "").lower()
    # Check for keywords relevant to this claim in the extract
    claim_keywords = set()
    for word in ("sp500", "sp500_proxy", "todo", "layer-2", "layer-3",
                 "layer 2", "layer 3", "execution", "blocked", "phase",
                 "rename", "amendment", "verification", "implementation"):
        if word in text:
            claim_keywords.add(word.upper() if len(word) <= 6 else word)

    matched_keywords = []
    for section in keyword_sections:
        kw = section.get("keyword", "").lower()
        context = section.get("context", "").lower()
        for ck in claim_keywords:
            if ck.lower() in kw or ck.lower() in context:
                matched_keywords.append(kw)
                break

    if matched_keywords:
        return True, [f"keyword_sections({', '.join(sorted(set(matched_keywords))[:5])})"]
    return False, []


def _code_context_supports_claim(
    code_context: dict[str, Any] | None,
    claim: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check if code_context provides corroborating evidence for a claim."""
    if code_context is None:
        return False, []

    text = claim.get("claim_text", "").lower()
    evidence: list[str] = []

    if "sp500" in text or "spy" in text:
        sr = code_context.get("series_registry", {})
        if sr.get("sp500_proxy_detected"):
            evidence.append("code_context: SP500_PROXY in registry")
        ai = code_context.get("adapter_inventory", {})
        if "spy_adapter.py" in (ai.get("adapter_files") or []):
            evidence.append("code_context: spy_adapter.py present")

    if "layer-3" in text or "layer 3" in text:
        es = code_context.get("execution_artifact_scan", {})
        if es.get("layer3_execution_artifacts_absent"):
            evidence.append("code_context: layer3_execution_artifacts_absent=true")

    return bool(evidence), evidence


def _runtime_context_supports_claim(
    runtime_context: dict[str, Any] | None,
    claim: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check if runtime_context provides corroborating evidence."""
    if runtime_context is None:
        return False, []

    text = claim.get("claim_text", "").lower()
    evidence: list[str] = []

    if "layer-3" in text or "layer 3" in text:
        if runtime_context.get("layer3_runtime_absent"):
            evidence.append("runtime_context: layer3_runtime_absent=true")

    if "execution" in text and "not" in text:
        if runtime_context.get("layer3_runtime_absent"):
            evidence.append("runtime_context: no execution runtime present")

    return bool(evidence), evidence


# ---------------------------------------------------------------------------
# Main synthesis
# ---------------------------------------------------------------------------

def synthesize_role_citation_verdict(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> dict[str, Any]:
    """Produce a deterministic role_citation_verdict from upstream artifacts.

    Evaluates each classified claim against:
    - the interpretation_policy routing table
    - canonical_doc_extracts for role-matched evidence
    - code_context / runtime_context for corroboration
    """

    # --- Gather inputs ---
    ccm_record = run_state.artifacts.get("claim_classification_map")
    gc_record = run_state.artifacts.get("governance_context")

    ccm_payload: dict[str, Any] = (
        ccm_record.payload if ccm_record and ccm_record.status == "present" else {}
    )
    gc_payload: dict[str, Any] = (
        gc_record.payload if gc_record and gc_record.status == "present" else {}
    )

    # Extract claims
    rc = ccm_payload.get("request_classification", {})
    claims = rc.get("claims") or ccm_payload.get("claims") or []

    # Extract evidence sources from governance_context
    code_context = gc_payload.get("code_context")
    runtime_context = gc_payload.get("runtime_context")
    doc_extracts = gc_payload.get("canonical_doc_extracts", {})

    # Get routing table from interpretation_policy if available
    ip_record = run_state.artifacts.get("interpretation_policy.claim_routing")
    spec_routing: dict[str, Any] | None = None
    if ip_record is not None:
        # This is already the resolved routing dict from spec
        spec_routing = ip_record if isinstance(ip_record, dict) else None
    # Also check if it was stored directly as an artifact
    if spec_routing is None:
        ip_art = run_state.artifacts.get("interpretation_policy.claim_routing")
        if ip_art and hasattr(ip_art, "payload"):
            spec_routing = ip_art.payload

    routing_table = _build_routing_table(spec_routing)

    # --- Fail-closed: no claims ---
    if not claims:
        return {
            "produced_by": "route-claims-by-role",
            "role_matched_citation_status": {
                "overall_status": "conflict_requires_block",
                "inference_used": True,
                "inference_reason": (
                    "claim_classification_map contains no classified claims. "
                    "Cannot evaluate role-matched citations without claims."
                ),
                "source_authority_conflict_detected": False,
                "checked_claims": [],
                "summary": {
                    "role_mismatch_detected": False,
                    "canonical_conflict_unresolved": False,
                    "readme_layer2_used_as_override": False,
                    "requires_conflict_note": False,
                    "requires_doc_sync_escalation": False,
                    "recommended_guard_action": "block",
                    "blocking_claims": [],
                    "compliant_claims": [],
                    "review_only_claims": [],
                    "block_reason": "No claims available for role-matched citation check.",
                    "notes": [],
                },
            },
        }

    # --- Evaluate each claim ---
    checked_claims: list[dict[str, Any]] = []
    blocking_claims: list[str] = []
    compliant_claims: list[str] = []
    review_only_claims: list[str] = []
    role_mismatch_detected = False
    source_authority_conflict = False
    inference_used = False

    for claim in claims:
        if not isinstance(claim, dict):
            continue

        claim_id = claim.get("claim_id", "unknown")
        claim_text = claim.get("claim_text", "")
        source_priority = claim.get("source_priority", [])
        claim_type = _classify_claim_type(claim)
        is_guard = _is_negative_guard(claim)
        is_strong = _is_strong_claim(claim)

        # Determine required primary source
        if source_priority:
            required_primary = source_priority[0]
        else:
            required_primary = routing_table.get(claim_type, "SYSTEM_IMPLEMENTATION_RECORD_v1.md")

        # Look up the document extract for the required primary source
        # The key in doc_extracts is the filename only (e.g. "README_v1.md")
        doc_filename = required_primary.split("/")[-1] if "/" in required_primary else required_primary
        doc_extract = doc_extracts.get(doc_filename)

        # Check if the extract supports this claim
        doc_supported, doc_sources = _doc_extract_supports_claim(doc_extract, claim)

        # Check code/runtime corroboration
        code_supported, code_sources = _code_context_supports_claim(code_context, claim)
        runtime_supported, runtime_sources = _runtime_context_supports_claim(runtime_context, claim)

        # Build provided_sources list
        provided_sources: list[str] = []
        if doc_supported:
            provided_sources.append(f"{required_primary} (extract)")
            provided_sources.extend(doc_sources)
        if code_supported:
            provided_sources.extend(code_sources)
        if runtime_supported:
            provided_sources.extend(runtime_sources)

        # Also check secondary sources from source_priority
        secondary_support = False
        for sp in source_priority[1:]:
            sp_filename = sp.split("/")[-1] if "/" in sp else sp
            sp_extract = doc_extracts.get(sp_filename)
            sp_supported, sp_sources = _doc_extract_supports_claim(sp_extract, claim)
            if sp_supported:
                secondary_support = True
                provided_sources.append(f"{sp} (extract)")

        # --- Determine verdict ---
        role_match = doc_supported
        blocking_condition: str | None = None
        verdict: str
        reason: str
        notes: str = ""

        if is_guard:
            # Negative guard claims: compliant if docs + code/runtime agree,
            # or if the claim is a self-framing governance assertion confirmed
            # by the request text itself.
            request_text = gc_payload.get("request_text", "").lower()
            claim_text_lower = claim_text.lower()
            is_self_framing_guard = (
                claim_type == "governance"
                and any(kw in claim_text_lower for kw in (
                    "not a semantic rename", "not a constitutional amendment",
                    "documentation synchronization",
                ))
                and any(kw in request_text for kw in (
                    "not a semantic rename", "not a constitutional amendment",
                    "documentation synchronization",
                ))
            )

            if doc_supported or code_supported or runtime_supported or is_self_framing_guard:
                verdict = "compliant"
                if is_self_framing_guard and not (doc_supported or code_supported or runtime_supported):
                    reason = (
                        f"Governance self-framing guard: request text confirms "
                        f"this constraint. Compliant by request-claim consistency."
                    )
                else:
                    reason = (
                        f"Negative guard claim is supported by "
                        f"{'canonical doc extract' if doc_supported else ''}"
                        f"{' + code/runtime context' if code_supported or runtime_supported else ''}. "
                        f"Request preserves this constraint."
                    )
                role_match = True
            else:
                # Guard claims without any evidence — still review_only since
                # they are preserving a known constitutional constraint
                verdict = "review_only"
                reason = (
                    f"Negative guard claim: no direct extract evidence found in "
                    f"{required_primary}, but claim preserves a constitutional "
                    f"constraint. Review recommended."
                )
                notes = "Guard claims that preserve CLAUDE.md constraints are low-risk."
        elif is_strong and claim_type == "implementation":
            # Strong implementation claims require the role-matched canonical source
            if doc_supported and doc_extract and doc_extract.get("status") == "present":
                # Doc extract exists and has relevant sections
                if code_supported:
                    verdict = "review_only"
                    reason = (
                        f"Implementation claim has supporting extract from "
                        f"{required_primary} and corroborating code evidence. "
                        f"Review: confirm extract sections explicitly confirm completion."
                    )
                else:
                    verdict = "review_only"
                    reason = (
                        f"Implementation claim has supporting extract from "
                        f"{required_primary} but no code corroboration. "
                        f"Review required."
                    )
            elif code_supported and not doc_supported:
                # Code evidence exists but canonical doc doesn't support
                verdict = "review_only"
                role_match = False
                role_mismatch_detected = True
                reason = (
                    f"Implementation claim has code evidence but role-matched "
                    f"canonical source {required_primary} does not have "
                    f"supporting extract sections. "
                    f"Code evidence alone does not substitute for canonical citation."
                )
                blocking_condition = (
                    f"Implementation claim lacks role-matched canonical citation "
                    f"in {required_primary}."
                )
                notes = (
                    f"Code context provides corroborating evidence but "
                    f"CLAUDE.md Section 2.2 requires {required_primary} "
                    f"as the authoritative source for implementation state."
                )
            else:
                # No supporting evidence at all
                verdict = "conflict_requires_block"
                role_match = False
                role_mismatch_detected = True
                source_authority_conflict = True
                reason = (
                    f"Strong implementation claim with no citation from "
                    f"role-matched source {required_primary} and no code "
                    f"corroboration. CLAUDE.md Section 16: unverified claims "
                    f"must be treated as non-binding."
                )
                blocking_condition = (
                    f"Strong implementation claim asserted without role-matched "
                    f"canonical citation. Rule D2 applies."
                )
        elif is_strong and claim_type == "documentation_consistency":
            # Doc-sync claims: compliant if the matrix/doc exists
            if doc_supported or secondary_support:
                verdict = "compliant"
                reason = (
                    f"Documentation consistency claim is supported by "
                    f"canonical doc extracts. CLAUDE.md Section 11 applies."
                )
            else:
                verdict = "review_only"
                reason = (
                    f"Documentation consistency claim: relevant extract from "
                    f"{required_primary} not found. Review required."
                )
        else:
            # Other claims: check evidence
            if doc_supported or code_supported or runtime_supported:
                verdict = "compliant"
                reason = f"Claim supported by available evidence."
            elif doc_extract and doc_extract.get("status") == "present":
                verdict = "review_only"
                reason = (
                    f"Primary source {required_primary} is present but "
                    f"no directly relevant extract sections found. Review required."
                )
            else:
                verdict = "review_only"
                reason = f"Primary source {required_primary} not available in extracts."
                inference_used = True

        # Collect
        checked_claim: dict[str, Any] = {
            "claim_id": claim_id,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "required_primary_source": required_primary,
            "provided_sources": provided_sources,
            "role_match": role_match,
            "strong_claim": is_strong,
            "explicit_citation_required": is_strong and not is_guard,
            "conflict_detected": verdict == "conflict_requires_block",
            "blocking_condition_if_any": blocking_condition,
            "verdict": verdict,
            "reason": reason,
        }
        if notes:
            checked_claim["notes"] = notes

        checked_claims.append(checked_claim)

        if verdict == "conflict_requires_block":
            blocking_claims.append(claim_id)
        elif verdict == "review_only":
            review_only_claims.append(claim_id)
        else:
            compliant_claims.append(claim_id)

    # --- Aggregate ---
    if blocking_claims:
        overall_status = "conflict_requires_block"
        guard_action = "block"
    elif review_only_claims:
        overall_status = "review_only"
        guard_action = "review"
    else:
        overall_status = "compliant"
        guard_action = "proceed"

    block_reason = ""
    if blocking_claims:
        block_reason = (
            f"{len(blocking_claims)} claim(s) blocked due to missing "
            f"role-matched canonical citations: {', '.join(blocking_claims)}. "
            f"CLAUDE.md Section 16 requires traceable canonical evidence."
        )

    return {
        "produced_by": "route-claims-by-role",
        "role_matched_citation_status": {
            "overall_status": overall_status,
            "inference_used": inference_used,
            "source_authority_conflict_detected": source_authority_conflict,
            "checked_claims": checked_claims,
            "summary": {
                "role_mismatch_detected": role_mismatch_detected,
                "canonical_conflict_unresolved": source_authority_conflict,
                "readme_layer2_used_as_override": False,
                "requires_conflict_note": source_authority_conflict,
                "requires_doc_sync_escalation": False,
                "recommended_guard_action": guard_action,
                "blocking_claims": blocking_claims,
                "compliant_claims": compliant_claims,
                "review_only_claims": review_only_claims,
                "block_reason": block_reason,
                "notes": [
                    f"Deterministic synthesis from {len(claims)} classified claim(s).",
                    f"Routing table: {'interpretation_policy' if spec_routing else 'default'}.",
                    f"Doc extracts available: {len(doc_extracts)}.",
                ],
            },
        },
    }

from __future__ import annotations

from dataclasses import dataclass, field

from governance.dag_runner.blockers import BlockerSummary
from governance.dag_runner.validator import ValidationResult


class VerdictError(RuntimeError):
    """Raised when verdict computation fails."""


@dataclass(frozen=True)
class GovernanceVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def is_review_only(self) -> bool:
        return self.status == "review_only"


def compute_verdict(
    validation_result: ValidationResult,
    blocker_summary: BlockerSummary,
) -> GovernanceVerdict:
    reasons: list[str] = []

    if not validation_result.is_valid:
        reasons.append(
            f"Validation failed with {len(validation_result.issues)} issue(s)."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    if blocker_summary.has_unknown_references:
        reasons.append(
            f"Unknown blocker references detected: {len(blocker_summary.unknown_references)}."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    if blocker_summary.has_orphans:
        reasons.append(
            f"Declared blocker(s) not referenced by any planned step: {len(blocker_summary.orphan_blockers)}."
        )
        return GovernanceVerdict(status="review_only", reasons=reasons)

    if not blocker_summary.is_structurally_consistent:
        reasons.append("Blocker summary is not structurally consistent.")
        return GovernanceVerdict(status="review_only", reasons=reasons)

    reasons.append("Validation passed and blocker structure is consistent.")
    return GovernanceVerdict(status="ready", reasons=reasons)
# Reviewer Agent

Role:
Audit code changes for correctness, safety, and architecture compliance.

---

## Review Checklist

1. Fail-closed behavior preserved
2. Snapshot contract unchanged
3. Registry semantics unchanged
4. No silent data overwrites
5. Schema migrations handled safely

---

## Critical Areas

Pay special attention to:

- observations table writes
- snapshot hash logic
- alignment rules
- tier1 gating logic
- registry parsing

---

## Required Tests

Ensure:

- quality_gate.py PASS
- snapshot_publisher.py --dry-run succeeds


Reject patches that bypass these checks.
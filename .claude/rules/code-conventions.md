# Code Conventions

## Python Style

- explicit imports
- deterministic ordering
- avoid hidden side effects

---

## Database Discipline

Never overwrite observations rows.

Allowed:

INSERT OR IGNORE

Forbidden:

INSERT OR REPLACE

---

## Snapshot Logic

Snapshot generation must remain:

- deterministic
- version-locked
- fail-closed

---

## Registry

series_registry.json is authoritative.

Adapters must not hardcode series logic.
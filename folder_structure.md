gold_macro_engine/
  README.md

  configs/
    current_series_registry.json                 # your source-of-truth config
    snapshots/
      cfg-current-series__2026-02-28T21-30-00Z.json
      cfg-current-series__2026-03-01T09-00-00Z.json

  db/
    schema.sql                                   # the SQL above
    engine.sqlite                                # MVP (or point to Postgres via env)

  src/
    engine/
      __init__.py
      settings.py                                # DB URL, API key env vars, timeouts
      db.py                                      # connection + migrations
      hashing.py                                 # sha256 helpers
      timeutil.py                                # ISO time, date ranges

    ingestion/
      __init__.py
      contract.py                                # validates config + builds run plan
      fred_client.py                             # GET series/observations w/ retry/backoff
      mapper.py                                  # maps config milestone->series ids
      writer.py                                  # writes ingestion_runs + observations
      backfill.py                                # orchestrates M0/M1/M2
      incremental.py                              # daily/weekly update

    features/
      __init__.py
      definitions.py                             # feature registry (in code or JSON)
      builder.py                                 # computes feature_values from observations

    decision/
      __init__.py
      state_builder.py                           # produces state_vectors
      index_suite.py                             # indices table writes
      regime_gate.py                             # regime_labels writes
      supervisor.py                              # veto/permissions
      decision_builder.py                         # emits decision_packets

  runs/
    2026-02-28/
      run__M0__BACKFILL__2026-02-28T21-30-00Z/
        plan.json                                # resolved series list, date bounds
        fred_payloads/
          DFII10__page1.json
          DGS10__page1.json
        metrics.json                              # counts, missing, latencies
        errors.json                               # if any

  scripts/
    run_backfill.py                              # CLI entry
    run_incremental.py

  tests/
    test_contract.py
    test_idempotency.py
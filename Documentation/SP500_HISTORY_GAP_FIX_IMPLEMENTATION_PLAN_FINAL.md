# SP500 History Gap Fix — Implementation Plan (Validated)

## Summary

This plan resolves the historical gap in S&P 500 data by introducing a new series:

- **SP500** (unchanged) → FRED index  
- **SP500_PROXY** → Yahoo Finance SPY adjusted-close proxy (2005–present)

No existing data is modified. The system remains deterministic, auditable, and fail-closed.

---

## 1. Arguments

### Rationale

- FRED SP500 starts ~2016 → insufficient for long-term analysis  
- SPY ETF provides continuous history back to 2005+  
- Layer-2 is a **truth layer** → do not redefine existing series  

### Decision

SP500        = FRED index  
SP500_PROXY  = SPY adjusted close  

### Assumptions

- Yahoo adjusted close is an acceptable proxy  
- No synthetic blending allowed  
- Layer-3 remains not built, consistent with architecture documentation  
- This work does not initiate or implement Layer-3 components  

---

## 2. Short Execution Order

1. Create branch  
2. Add SP500_PROXY to registry  
3. Increment registry_version  
4. Implement spy_adapter.py  
5. Add adapter to run_backfill  
6. Add tests  
7. Validate registry  
8. Run backfill  
9. Verify DB + isolation  
10. Run quality gate  
11. Dry-run snapshot  
12. Update documentation  
13. Commit  

---

## 3. Step-by-Step Description

### 3.1 Registry Entry

```json
{
  "series_id": "SP500_PROXY",
  "description": "S&P 500 proxy via SPY ETF adjusted close",
  "tier": 1,
  "frequency": "D",
  "staleness_days": 3,
  "blocks_snapshot": true,
  "group": "risk",
  "source": "yahoo_spy",
  "full_history_start": "2005-01-03",
  "discontinued": false,
  "is_estimate": false,
  "include_in_snapshot": true,
  "revision_risk": false,
  "notes": "Yahoo Finance SPY adjusted close. Long-history equity proxy from 2005. Does not replace FRED SP500."
}
```

---

### 3.2 Adapter Implementation

```python
from datetime import datetime, timedelta, timezone, date

def fetch_spy_yahoo(start: date, end: date) -> list[tuple[date, float, str]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is not installed. Run: pip install yfinance"
        ) from exc

    data = yf.download(
        "SPY",
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
    )

    rows = []
    for ts, row in data.iterrows():
        value = float(row["Close"])
        if value > 0:
            rows.append((ts.date(), value, "yahoo_spy"))

    return rows
```

---

### 3.3 as_of_ts Convention

```python
as_of = datetime(
    obs_date.year,
    obs_date.month,
    obs_date.day,
    21,
    0,
    0,
    tzinfo=timezone.utc,
)
```

---

### 3.4 Backfill

```bash
python layer2/adapters/spy_adapter.py --backfill-start 2005-01-03
```

Expected runtime: ~1–2 seconds

---

### 3.5 Validation Queries

```sql
SELECT strftime('%Y', obs_ts) AS year,
       COUNT(*) AS rows,
       MIN(obs_ts),
       MAX(obs_ts)
FROM observations
WHERE series_id = 'SP500_PROXY'
GROUP BY year
ORDER BY year;
```

---

### 3.6 Quality Gate

```bash
python layer2/adapters/quality_gate.py
```

Expected output:

```
VERDICT: PASS
SP500_PROXY: OK
```

---

### 3.7 Tests

Create:

tests/layer2/test_spy_adapter.py

Follow patterns from:
- tests/layer2/test_gold_adapter.py
- tests/layer2/test_move_adapter.py

Use fixtures from:
- tests/conftest.py

---

### 3.8 Rollback Procedure

1. Remove SP500_PROXY from registry  
2. Run:

```sql
DELETE FROM observations WHERE series_id = 'SP500_PROXY';
```

3. Revert commit  

---

## Conclusion

This plan fixes the SP500 history gap without redefining existing data.

Next steps:
- Implement adapter
- Backfill data
- Validate snapshots

SP500 remains the index truth.  
SP500_PROXY becomes the long-history proxy.

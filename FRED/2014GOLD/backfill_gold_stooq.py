import csv
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

OUT_FILE = "gold_xauusd_stooq_2014_yesterday.json"

# Correct Stooq symbol for Gold / USD is usually XAUUSD
STOOQ_URL = "https://stooq.com/q/d/l/?s=xauusd&i=d"

def utc_yesterday_str() -> str:
    y = datetime.now(timezone.utc).date() - timedelta(days=1)
    return y.isoformat()

def download_csv(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            # Some sites behave better with a user-agent
            "User-Agent": "Mozilla/5.0"
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8", errors="replace")

def main():
    start_date = "2014-01-01"
    end_date = utc_yesterday_str()

    print("Downloading Stooq XAUUSD daily CSV...")
    csv_text = download_csv(STOOQ_URL)

    # Debug: if Stooq changes format, show the top of the response
    head = "\n".join(csv_text.splitlines()[:5])
    if "Date" not in head:
        print("Unexpected response header. First lines:")
        print(head)
        raise RuntimeError("CSV header does not contain 'Date'. Stooq format/symbol may have changed.")

    reader = csv.DictReader(csv_text.splitlines())
    rows: List[Dict[str, Any]] = []

    def f(x):
        try:
            return float(x) if x not in (None, "", "null") else None
        except ValueError:
            return None

    for r in reader:
        d = r.get("Date")
        if not d:
            continue

        if d < start_date or d > end_date:
            continue

        close_val = f(r.get("Close"))
        if close_val is None:
            continue

        rows.append({
            "date": d,
            "close": close_val,
            "open": f(r.get("Open")),
            "high": f(r.get("High")),
            "low": f(r.get("Low")),
            "volume": f(r.get("Volume")),
            "vendor": "stooq",
            "symbol": "XAUUSD",
            "pricing_convention": "close",
            "sampling_rule": "daily_ohlc",
        })

    if not rows:
        print("No rows parsed. First lines:")
        print(head)
        raise RuntimeError("No rows parsed. Possibly blocked response or changed format.")

    # Ensure sorted + no duplicates
    rows.sort(key=lambda x: x["date"])
    dates = [x["date"] for x in rows]
    if len(dates) != len(set(dates)):
        raise RuntimeError("Duplicate dates found in output.")

    with open(OUT_FILE, "w", encoding="utf-8") as f_out:
        json.dump(rows, f_out, indent=2)

    print(f"Saved {len(rows)} records to {OUT_FILE}")
    print(f"First: {rows[0]['date']}  Last: {rows[-1]['date']}")

if __name__ == "__main__":
    main()
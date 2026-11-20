#!/usr/bin/env python3
"""Public delayed E-mini Nasdaq-100 futures market snapshot.
Hourly report checks serve as a fallback when scheduled GitHub Actions runs are skipped.
Scheduled checks may be deferred by GitHub; also triggered via source edits.
No credentials, no Plus500 or account data. Fail closed if source unavailable.
Yahoo Finance chart endpoint is unofficial and may stop working."""
import json
import math
import pathlib
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OUT = pathlib.Path("data/futures.json")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF?range=1d&interval=5m"
req = urllib.request.Request(URL, headers={
    "User-Agent": "Mozilla/5.0 (compatible; PayAndPrayMarketMonitor/1.0)",
    "Accept": "application/json"
})
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    name = str(meta.get("shortName") or meta.get("longName") or "")
    symbol = str(meta.get("symbol") or "")
    # Yahoo metadata name can be abbreviated/localized; the exact futures ticker is decisive.
    if symbol != "NQ=F":
        raise ValueError(f"Unexpected ticker {symbol!r}, source name={name!r}")
    ts = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or []
    vals = (quotes[0].get("close") or []) if quotes else []
    ticks = [(int(t), float(p)) for t, p in zip(ts, vals)
             if isinstance(p, (int, float)) and math.isfinite(p) and p > 1000]
    if ticks:
        last_ts, last_px = ticks[-1]
        quote_field = "intradayClose"
    elif (isinstance(meta.get("regularMarketTime"), int)
          and isinstance(meta.get("regularMarketPrice"), (int, float))
          and math.isfinite(meta["regularMarketPrice"]) and meta["regularMarketPrice"] > 1000):
        last_ts, last_px = meta["regularMarketTime"], meta["regularMarketPrice"]
        quote_field = "regularMarketPrice"
    else:
        raise ValueError("No usable timestamped close")
    now = datetime.now(timezone.utc)
    quote_dt = datetime.fromtimestamp(last_ts, timezone.utc)
    age = (now - quote_dt).total_seconds()
    if age < -120 or age > 86400:
        raise ValueError("Stale or future timestamp")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    prev = float(previous) if previous is not None else None
    change = (last_px / prev - 1) * 100 if prev and prev > 0 else None
    output = {
        "symbol": "NQ=F",
        "name": "E-mini Nasdaq-100 futures",
        "instrumentType": "FUTURES",
        "source": "Yahoo Finance chart (unofficial)",
        "sourceUrl": "https://finance.yahoo.com/quote/NQ=F/",
        "quoteField": quote_field,
        "price": round(last_px, 2),
        "changePercent": round(change, 2) if change is not None else None,
        "quotedAtUtc": quote_dt.isoformat().replace("+00:00", "Z"),
        "quotedAtPrague": quote_dt.astimezone(ZoneInfo("Europe/Prague")).strftime("%d. %m. %Y %H:%M"),
        "fetchedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "delayed": True
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if old.get("quotedAtUtc") and datetime.fromisoformat(old["quotedAtUtc"].replace("Z", "+00:00")) > quote_dt:
        raise ValueError("Quote predates the published snapshot")
    if old.get("quotedAtUtc") != output["quotedAtUtc"] or old.get("price") != output["price"]:
        OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"NQ=F {last_px:.2f}, timestamp={last_ts}, age_s={round(age)}")
except Exception as exc:
    # Keep the last successful source timestamp intact; the site handles staleness.
    raise SystemExit(f"Quote update FAILED (no new data published): {exc}")

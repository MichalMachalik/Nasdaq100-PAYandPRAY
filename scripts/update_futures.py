#!/usr/bin/env python3
"""Public delayed E-mini Nasdaq-100 futures market snapshot.
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
    if symbol != "NQ=F" or "Nasdaq" not in name.lower():
        raise ValueError("Unexpected instrument name or symbol")
    ts = result.get("timestamp") or []
    vals = (result["indicators"]["quote"][0].get("close") or [])
    ticks = [(int(t), float(p)) for t, p in zip(ts, vals)
             if isinstance(p, (int, float)) and math.isfinite(p) and p > 1000]
    if not ticks:
        raise ValueError("No usable timestamped close")
    last_ts, last_px = ticks[-1]
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
        "price": round(last_px, 2),
        "changePercent": round(change, 2) if change is not None else None,
        "quotedAtUtc": quote_dt.isoformat().replace("+00:00", "Z"),
        "quotedAtPrague": quote_dt.astimezone(ZoneInfo("Europe/Prague")).strftime("%d. %m. %Y %H:%M"),
        "fetchedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "delayed": True
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    # Do not commit repeatedly unless provider's quote timestamp changes.
    if old.get("quotedAtUtc") != output["quotedAtUtc"] or old.get("price") != output["price"]:
        OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"NQ=F {last_px:.2f}, timestamp={last_ts}, age_s={round(age)}")
except Exception as exc:
    # Keep the last successful source timestamp intact; the site handles staleness.
    print(f"Quote update unavailable: {exc}")

#!/usr/bin/env python3
"""Refresh the observed historical high of Yahoo's continuous NQ=F futures series.
Separate from the fast live-quote update: a transient history failure must not
change the live quote or replace a verified reference with an invented number.
Yahoo chart is an unofficial endpoint and may become unavailable.
"""
import json
import math
import pathlib
import urllib.request
from datetime import datetime, timezone

OUT = pathlib.Path("data/futures-ath.json")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF?range=max&interval=1wk"
req = urllib.request.Request(URL, headers={
    "User-Agent": "Mozilla/5.0 (compatible; PayAndPrayMarketMonitor/1.0)",
    "Accept": "application/json",
})
try:
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    if result["meta"].get("symbol") != "NQ=F":
        raise ValueError("Historical series is not NQ=F")
    timestamps = result.get("timestamp") or []
    highs = (result["indicators"]["quote"][0].get("high") or [])
    candles = [
        (int(ts), float(high))
        for ts, high in zip(timestamps, highs)
        if isinstance(ts, (int, float)) and isinstance(high, (int, float))
        and math.isfinite(high) and 1000 < high < 1000000
    ]
    now = datetime.now(timezone.utc)
    if len(candles) < 120:
        raise ValueError("Too few candles to call the peak historical")
    oldest = datetime.fromtimestamp(min(ts for ts, _ in candles), timezone.utc)
    newest = datetime.fromtimestamp(max(ts for ts, _ in candles), timezone.utc)
    if (now - oldest).days < 5 * 365 or not 0 <= (now - newest).days <= 21:
        raise ValueError("Historical coverage is incomplete or stale")
    peak_ts, peak_price = max(candles, key=lambda item: item[1])
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if previous.get("symbol") == "NQ=F" and isinstance(previous.get("maxPrice"), (int, float)):
        if peak_price < previous["maxPrice"] * 0.98:
            raise ValueError("Historical peak unexpectedly below verified prior reference")
    output = {
        "symbol": "NQ=F",
        "maxPrice": round(peak_price, 2),
        "benchmark": "historical",
        "observedWeek": datetime.fromtimestamp(peak_ts, timezone.utc).date().isoformat(),
        "source": "Yahoo Finance continuous NQ=F weekly candle highs (unofficial)",
        "sourceUrl": "https://finance.yahoo.com/quote/NQ=F/",
        "range": "max",
        "interval": "1wk",
        "historyPoints": len(candles),
        "checkedAtUtc": now.isoformat().replace("+00:00", "Z"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"NQ=F observed historical peak {peak_price:.2f}; candles {len(candles)}")
except Exception as exc:
    # Fail closed: retain the last verified 52-week/history reference.
    raise SystemExit(f"NQ historical high update FAILED (reference kept): {exc}")

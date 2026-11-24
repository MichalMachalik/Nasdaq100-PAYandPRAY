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
def fetch_chart():
    failures = []
    for url in (URL, URL.replace("query1.finance.yahoo.com", "query2.finance.yahoo.com")):
        try:
            request = urllib.request.Request(url, headers=dict(req.header_items()))
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
            if data["chart"]["result"][0]["meta"].get("symbol") != "NQ=F":
                raise ValueError("Unexpected futures symbol")
            return data
        except Exception as exc:
            failures.append(str(exc))
    raise ValueError("Both Yahoo chart hosts unavailable: " + "; ".join(failures))

try:
    payload = fetch_chart()
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    name = str(meta.get("shortName") or meta.get("longName") or "")
    symbol = str(meta.get("symbol") or "")
    # Yahoo metadata name can be abbreviated/localized; the exact futures ticker is decisive.
    if symbol != "NQ=F":
        raise ValueError(f"Unexpected ticker {symbol!r}, source name={name!r}")
    now = datetime.now(timezone.utc)
    ts = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or []
    vals = (quotes[0].get("close") or []) if quotes else []
    candidates = []
    # A completed 5-minute bar can lag the provider's timestamped last quote.
    # Compare both; neither a missing bar nor an old bar may hide newer metadata.
    for tick, price in zip(ts, vals):
        if (isinstance(tick, (int, float)) and not isinstance(tick, bool)
                and math.isfinite(tick) and isinstance(price, (int, float))
                and not isinstance(price, bool) and math.isfinite(price) and price > 1000):
            age = now.timestamp() - tick
            if age >= -120:
                candidates.append((int(tick), float(price), "intradayClose"))
    market_time, market_price = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if (isinstance(market_time, int) and not isinstance(market_time, bool)
            and isinstance(market_price, (int, float)) and not isinstance(market_price, bool)
            and math.isfinite(market_price) and market_price > 1000
            and now.timestamp() - market_time >= -120):
        candidates.append((market_time, float(market_price), "regularMarketPrice"))
    if not candidates:
        raise ValueError("No usable timestamped close (invalid or future quote)")
    last_ts, last_px, quote_field = max(
        candidates, key=lambda row: (row[0], row[2] == "regularMarketPrice"))
    quote_dt = datetime.fromtimestamp(last_ts, timezone.utc)
    age = (now - quote_dt).total_seconds()
    # Weekends/holidays do not create new quotes. Retain the true timestamp
    # and mark its age, rather than reject a valid last quotation after 24 h.
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
        "checkedAtUtc": now.isoformat().replace("+00:00", "Z"),
        "quoteStatus": "stale" if age > 86400 else "delayed",
        "delayed": True
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if old.get("quotedAtUtc") and datetime.fromisoformat(old["quotedAtUtc"].replace("Z", "+00:00")) > quote_dt:
        raise ValueError("Quote predates the published snapshot")
    # Successful unchanged checks are observable without relabeling quote time.
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"NQ=F {last_px:.2f}, timestamp={last_ts}, age_s={round(age)}")
except Exception as exc:
    # Keep the last successful source timestamp intact; the site handles staleness.
    raise SystemExit(f"Quote update FAILED (no new data published): {exc}")


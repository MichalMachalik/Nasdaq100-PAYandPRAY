#!/usr/bin/env python3
"""Refresh verified market inputs for Pay & Pray's 1–3m NDX scenario.

Uses Yahoo's unofficial ^VXN daily chart and Treasury's official daily rates CSV.
No subjective news scoring or made-up data. Each source keeps its own observation
date; source outages retain the last verified value. This does NOT predict prices.
"""
import csv
import io
import json
import math
import pathlib
import urllib.request
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

OUT = pathlib.Path("data/risk-model.json")
VXN_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVXN?range=1mo&interval=1d"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                "interest-rates/daily-treasury-rates.csv/2026/all"
                "?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv")
HEADER = {"User-Agent": "Mozilla/5.0 (compatible; PayAndPrayEvidenceModel/1.0)",
          "Accept": "application/json,text/csv,*/*"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADER)
    with urllib.request.urlopen(req, timeout=23) as response:
        return response.read().decode("utf-8-sig")

def parse_vxn(payload, now):
    result = payload["chart"]["result"][0]
    symbol = result.get("meta", {}).get("symbol")
    if symbol != "^VXN":
        raise ValueError(f"Expected ^VXN, received {symbol!r}")
    ts = result.get("timestamp") or []
    candles = result["indicators"]["quote"][0].get("close") or []
    vals = []
    for tick, price in zip(ts, candles):
        if not isinstance(tick, (int, float)) or not isinstance(price, (int, float)):
            continue
        val = float(price)
        if not math.isfinite(val) or not 8 <= val <= 100:
            continue
        obs = datetime.fromtimestamp(int(tick), ZoneInfo("America/New_York")).date()
        age = (now.date() - obs).days
        if 0 <= age <= 7:
            vals.append((obs.isoformat(), val))
    if not vals:
        raise ValueError("No dated ^VXN observations in past 7 calendar days")
    obs_date, val = max(vals)
    return obs_date, round(val, 2)

def parse_treasury(text, now):
    reader = csv.DictReader(io.StringIO(text))
    candidates = []
    for line in reader:
        try:
            stamp = (line.get("Date") or "").strip()
            obs = datetime.strptime(stamp, "%m/%d/%Y").date()
            if not 0 <= (now.date() - obs).days <= 7:
                continue
            values = [float((line.get(key) or "").strip()) for key in ("2-year", "10-year", "30-year")]
            if not all(math.isfinite(x) and 0.5 <= x <= 15 for x in values):
                continue
            candidates.append((obs.isoformat(), values))
        except (TypeError, ValueError):
            continue
    if not candidates:
        raise ValueError("No usable fresh US Treasury 2y/10y/30y daily data")
    return max(candidates, key=lambda item: item[0])

def calculate_downside_pct(volatility_pct, months):
    """25th-percentile lognormal terminal-price decline, not maximum drawdown."""
    if not 8 <= volatility_pct <= 100 or months not in (1, 3):
        raise ValueError("Unsupported annual IV or period")
    s = volatility_pct / 100
    t = months / 12
    return 100 * (1 - math.exp(-0.5 * s * s * t - 0.6744897501960817 * s * math.sqrt(t)))

def main():
    now = datetime.now(timezone.utc)
    model = json.loads(OUT.read_text(encoding="utf-8"))
    if model.get("schemaVersion") != 1 or model.get("id") != "ndx-evidence-volatility-v1":
        raise ValueError("Unexpected schema; manual reconciliation required")
    market = model["market"]
    outcomes, failures = [], []
    try:
        obs, value = parse_vxn(json.loads(fetch(VXN_URL)), now)
        if obs >= market["vxnAsOf"]:
            if obs != market["vxnAsOf"] or value != market["vxnPct"]:
                market.update(vxnPct=value, vxnAsOf=obs,
                              vxnSource="https://finance.yahoo.com/quote/%5EVXN/",
                              vxnRetrievedAtUtc=now.isoformat().replace("+00:00", "Z"))
                outcomes.append(f"VXN {obs}: {value:.2f}%")
    except Exception as exc:
        failures.append(f"VXN: {exc}")
    try:
        obs, rates = parse_treasury(fetch(TREASURY_URL), now)
        if obs >= market["treasuryAsOf"]:
            previous = (market.get("treasury2yPct"), market.get("treasury10yPct"),
                        market.get("treasury30yPct"))
            if obs != market["treasuryAsOf"] or tuple(rates) != previous:
                market.update(treasury2yPct=rates[0], treasury10yPct=rates[1],
                              treasury30yPct=rates[2], treasuryAsOf=obs,
                              treasurySource="https://home.treasury.gov/",
                              treasuryRetrievedAtUtc=now.isoformat().replace("+00:00", "Z"))
                outcomes.append(f"Treasury {obs}: 2Y {rates[0]:.2f}%, 10Y {rates[1]:.2f}%, 30Y {rates[2]:.2f}%")
    except Exception as exc:
        failures.append(f"UST: {exc}")
    # A live market is never relabeled with fetch time if its price did not move.
    if outcomes:
        OUT.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    # A valid unchanged Saturday snapshot is fine. If both feeds failed, surface
    # the failure in Actions; do not overwrite the verified JSON.
    if len(failures) == 2:
        raise SystemExit("Both evidence feeds unavailable; retained last verified snapshot: "
                         + "; ".join(failures))
    print("; ".join(outcomes) if outcomes else "Evidence inputs unchanged; dated source values retained")
    for problem in failures:
        print("Warning:", problem)

if __name__ == "__main__":
    main()

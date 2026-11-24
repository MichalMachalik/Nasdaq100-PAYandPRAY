#!/usr/bin/env python3
"""Refresh verified market inputs for Pay & Pray's 1–3m NDX scenario.

Uses dated VXN daily closes from FRED (Cboe), or Yahoo Finance when fresher,
and Treasury's official daily rates CSV.
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
FRED_VXN_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VXNCLS"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                "interest-rates/daily-treasury-rates.csv/{year}/all"
                "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
HEADER = {"User-Agent": "Mozilla/5.0 (compatible; PayAndPrayEvidenceModel/1.0)",
          "Accept": "application/json,text/csv,*/*"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADER)
    with urllib.request.urlopen(req, timeout=23) as response:
        return response.read().decode("utf-8-sig")

def vxn_observations(payload, now):
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
        local = now.astimezone(ZoneInfo("America/New_York"))
        age = (local.date() - obs).days
        if 0 <= age <= 14 and (obs < local.date() or (local.hour, local.minute) >= (16, 30)):
            vals.append((obs.isoformat(), val))
    if not vals:
        raise ValueError("No dated ^VXN observations")
    return sorted(dict(vals).items())

def parse_vxn(payload, now):
    obs_date, val = vxn_observations(payload, now)[-1]
    if not 0 <= (now.date()-date.fromisoformat(obs_date)).days <= 7:
        raise ValueError("No dated ^VXN observations in past 7 calendar days")
    return obs_date, round(val, 2)

def parse_fred_vxn(text, now):
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            obs = date.fromisoformat(row.get("observation_date") or row.get("DATE") or "")
            val = float(row["VXNCLS"])
            if 0 <= (now.date()-obs).days <= 14 and math.isfinite(val) and 8 <= val <= 100:
                rows[obs.isoformat()] = val
        except (TypeError, ValueError, KeyError):
            continue
    if not rows:
        raise ValueError("FRED VXNCLS: no valid dated observation")
    return sorted(rows.items())

def current_vxn(now):
    feeds = []
    try:
        feeds.append((parse_fred_vxn(fetch(FRED_VXN_URL), now),
                      "https://fred.stlouisfed.org/series/VXNCLS"))
    except Exception as exc:
        print("FRED VXN unavailable:", exc)
    try:
        feeds.append((vxn_observations(json.loads(fetch(VXN_URL)), now),
                      "https://finance.yahoo.com/quote/%5EVXN/"))
    except Exception as exc:
        print("Yahoo Finance VXN unavailable:", exc)
    if not feeds:
        raise ValueError("No valid VXN feed")
    # Prefer official source on equal observation dates; never substitute an older
    # official close for a newer verified close. Conflicting same-day values fail closed.
    feeds.sort(key=lambda f: (f[0][-1][0], "fred.stlouisfed.org" in f[1]), reverse=True)
    rows, source = feeds[0]
    obs, val = rows[-1]
    if not 0 <= (now.date()-date.fromisoformat(obs)).days <= 7:
        raise ValueError("Stale VXN close")
    for other, _ in feeds[1:]:
        same = dict(other).get(obs)
        if same is not None and abs(same-val) > 0.05:
            raise ValueError("VXN sources disagree on same-day close")
    previous = rows[-2] if len(rows)>1 else None
    delta = round((round(val,2)/round(previous[1],2)-1)*100,2) if previous else None
    return obs, round(val,2), source, delta, previous

def parse_treasury(text, now):
    reader = csv.DictReader(io.StringIO(text))
    candidates = []
    for line in reader:
        try:
            stamp = (line.get("Date") or "").strip()
            obs = datetime.strptime(stamp, "%m/%d/%Y").date()
            if not 0 <= (now.date() - obs).days <= 7:
                continue
            values = [float(str(line.get(short) or line.get(long) or "").strip())
                      for short, long in (("2 Yr", "2-year"), ("10 Yr", "10-year"), ("30 Yr", "30-year"))]
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
    outcomes, failures, checked = [], [], []
    checked_at = now.isoformat().replace("+00:00", "Z")
    try:
        obs, value, source, delta, previous = current_vxn(now)
        if obs < market["vxnAsOf"]:
            raise ValueError("VXN source predates the published observation")
        if obs == market["vxnAsOf"] and abs(value-market["vxnPct"]) > 0.05:
            raise ValueError("VXN conflicts with previously published close")
        market.update(vxnPct=value, vxnAsOf=obs, vxnSource=source,
                      vxnQuoteKind="daily-close", vxnChangePercent=delta,
                      vxnPreviousClose=round(previous[1],2) if previous else None,
                      vxnPreviousCloseAsOf=previous[0] if previous else None,
                      vxnRetrievedAtUtc=checked_at, vxnCheckedAtUtc=checked_at)
        outcomes.append(f"VXN {obs}: {value:.2f}")
        checked.append("VXN")
    except Exception as exc:
        failures.append(f"VXN: {exc}")
    try:
        obs, rates = parse_treasury(fetch(TREASURY_URL.format(year=now.year)), now)
        if obs < market["treasuryAsOf"]:
            raise ValueError("Treasury source predates the published observation")
        if obs >= market["treasuryAsOf"]:
            previous = (market.get("treasury2yPct"), market.get("treasury10yPct"),
                        market.get("treasury30yPct"))
            if obs != market["treasuryAsOf"] or tuple(rates) != previous:
                market.update(treasury2yPct=rates[0], treasury10yPct=rates[1],
                              treasury30yPct=rates[2], treasuryAsOf=obs,
                              treasurySource="https://home.treasury.gov/",
                              treasuryRetrievedAtUtc=now.isoformat().replace("+00:00", "Z"))
                outcomes.append(f"Treasury {obs}: 2Y {rates[0]:.2f}%, 10Y {rates[1]:.2f}%, 30Y {rates[2]:.2f}%")
            market["treasuryCheckedAtUtc"] = checked_at
            checked.append("Treasury")
    except Exception as exc:
        failures.append(f"UST: {exc}")
    # Successful checks are separate from the unchanged observation dates.
    # A partial source failure must not claim a full-model successful refresh.
    if len(checked) == 2:
        model["checkedAtUtc"] = checked_at
    if checked:
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


#!/usr/bin/env python3
"""Publish dated Nasdaq-100 50-session breadth from ChartVault's public data.

Input: current Nasdaq-100 security classes, share of eligible close > each 50DMA.
The measure is not a probability, and eligibility/member composition matters.
Failure, stale upstream data, or denominator inconsistency never overwrite a
previous observation. No hidden stale-data substitution or 39/61 hardcoding.
"""
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

OUT = Path("data/breadth.json")
SOURCE_URL = (
    "https://raw.githubusercontent.com/AveCeasar/AveCeasar.github.io/"
    "main/chart-data/nasdaq100-percent-above-moving-averages.json"
)
PUBLIC_URL = "https://aveceasar.github.io/nasdaq100-percent-above-moving-averages/"

def fetch_chart():
    request = Request(SOURCE_URL, headers={
        "User-Agent": "PayAndPray-Breadth/1.0 (public-data-reader)",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("Breadth data source returned non-200 status")
        raw = response.read(250_000)
        if len(raw) >= 250_000:
            raise ValueError("Breadth data response unexpectedly large")
        return json.loads(raw)

def make_snapshot(chart, now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be offset aware")
    if not isinstance(chart, dict) or chart.get("cadence") != "daily":
        raise ValueError("Unknown or non-daily Nasdaq breadth feed")
    if not any(x.get("key") == "above50" for x in chart.get("lines", []) if isinstance(x, dict)):
        raise ValueError("Above-50DMA key is missing")
    series = chart.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("No source observations")
    dated = [x for x in series if isinstance(x, dict) and isinstance(x.get("date"), str)]
    if not dated or any(x.get("date") != str(date.fromisoformat(x["date"])) for x in dated):
        raise ValueError("Invalid market date")
    if len({x["date"] for x in dated}) != len(dated):
        raise ValueError("Duplicate daily observations")
    if len(dated) != len(series):
        raise ValueError("Incomplete observations")
    current = max(dated, key=lambda row: row["date"])
    as_of = date.fromisoformat(current["date"])
    age = (now.date() - as_of).days
    if age < 0 or age > 7:
        raise ValueError("Missing, future-dated, or stale Nasdaq breadth data")
    updated = datetime.fromisoformat(chart.get("updatedAt", ""))
    if updated.tzinfo is None or updated > now:
        raise ValueError("Source update timestamp missing or in future")
    if updated.date() < as_of:
        raise ValueError("Source updated before reported market observation")
    eligible = current.get("eligible50")
    pct = current.get("above50")
    if type(eligible) is not int or not 95 <= eligible <= 120:
        raise ValueError("Insufficient MA50 coverage / impossible share-class count")
    if not isinstance(pct, (float, int)) or isinstance(pct, bool) or not math.isfinite(pct) or not 0 <= pct <= 100:
        raise ValueError("Invalid MA50 breadth percentage")
    count_f = pct / 100 * eligible
    above = round(count_f)
    if abs(count_f-above) > 0.0005:
        raise ValueError("Percent inconsistent with eligible security count")
    # The provider may count 101 securities for Nasdaq-100 due to dual classes.
    # Exactly-on-the-MA50 securities are included in the complement (not above).
    below = eligible - above
    return {
        "schemaVersion": 1,
        "id": "ndx-ma50-breadth",
        "asOf": as_of.isoformat(),
        "sourceUpdatedAt": updated.isoformat(),
        "eligibleSecurities": eligible,
        "aboveCount": above,
        "atOrBelowCount": below,
        "abovePct": round(100*above/eligible, 1),
        "belowPct": round(100*below/eligible, 1),
        "countedSecurityClasses": True,
        "source": "ChartVault · current Nasdaq-100 security classes vs their own 50-session SMA",
        "sourceUrl": PUBLIC_URL,
        "sourceDataUrl": SOURCE_URL,
        "methodology": (
            "Current Nasdaq-100 securities with enough history (not point-in-time members); "
            "each adjusted close > own trailing SMA50 counts as above; remaining eligible "
            "securities are at/below. Not forecasts. Historical member changes create "
            "survivorship bias."
        ),
        "feedStatus": "published",
    }

def main():
    now = datetime.now(timezone.utc)
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    snapshot = make_snapshot(fetch_chart(), now)
    if previous.get("asOf", "") > snapshot["asOf"]:
        raise ValueError("Upstream source is older than existing publication")
    checked_at = now.isoformat().replace("+00:00", "Z")
    if all(previous.get(k)==v for k,v in snapshot.items()):
        snapshot = previous
        print("MA50 breadth unchanged", snapshot["asOf"])
    else:
        snapshot["collectedAtUtc"] = checked_at
    snapshot["checkedAtUtc"] = checked_at
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Published MA50 breadth", snapshot["abovePct"], "above,",
          snapshot["belowPct"], "not above; as of", snapshot["asOf"])

if __name__ == "__main__":
    main()


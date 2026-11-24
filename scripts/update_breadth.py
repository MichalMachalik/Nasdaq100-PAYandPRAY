#!/usr/bin/env python3
"""Publish dated Nasdaq-100 50-session breadth from the dated StockCurry financial-data table.

Input: current Nasdaq-100 security classes, share of eligible close > each 50DMA.
The measure is not a probability, and eligibility/member composition matters.
Failure, stale upstream data, or denominator inconsistency never overwrite a
previous observation. No hidden stale-data substitution or 39/61 hardcoding.
"""
import json
import re
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

OUT = Path("data/breadth.json")
STOCKCURRY_URL = "https://stockcurry.com/index_timeline.php?index=Nasdaq100&view=percent"
NY = ZoneInfo("America/New_York")

class TimelineParser(HTMLParser):
    """Only use the named historical table columns, never a generic percentage."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None

def expected_cash_date(now):
    """Use a dated, validated cash-index observation; don't infer a holiday close."""
    dates = []
    try:
        d = json.loads((OUT.parent / "oversold.json").read_text(encoding="utf-8"))
        if d.get("instrument") == "^NDX" and d.get("schemaVersion") == 1:
            if isinstance(d.get("ndxClose"), (int, float)) and d["ndxClose"] > 1000:
                dates.append(date.fromisoformat(d["asOf"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        d = json.loads((OUT.parent / "latest.json").read_text(encoding="utf-8"))["ndx"]
        if isinstance(d.get("value"), (int, float)) and d["value"] > 1000:
            raw = str(d.get("asOf", ""))
            m = re.match(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b", raw)
            if m:
                day, month, year = map(int, m.groups())
                dates.append(date(year, month, day))
            elif re.match(r"^\d{4}-\d{2}-\d{2}\b", raw):
                dates.append(date.fromisoformat(raw[:10]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    local = now.astimezone(NY)
    dates = [x for x in dates if 0 <= (local.date()-x).days <= 7
             and (x != local.date() or local.hour >= 13)]
    return max(dates).isoformat() if dates else ""

def stockcurry_snapshot(html, now, expected=""):
    parser = TimelineParser()
    parser.feed(html)
    header = None
    candidates = []
    local = now.astimezone(NY)
    for row in parser.rows:
        names = [re.sub(r"\s+", "", x).lower() for x in row]
        if all(k in names for k in ("date", "totalstocks", ">sma50")):
            header = tuple(names.index(k) for k in ("date", "totalstocks", ">sma50"))
            continue
        if header is None or len(row) <= max(header):
            continue
        ds, count, percent = (row[i] for i in header)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
            continue
        try:
            day = date.fromisoformat(ds)
        except ValueError:
            continue
        if not 0 <= (local.date()-day).days <= 7:
            continue
        if day == local.date() and local.hour < 16 and ds != expected:
            continue
        if not re.fullmatch(r"\d{2,3}", count) or not re.fullmatch(r"\d{1,3}(?:\.\d{1,4})?%", percent):
            continue
        eligible = int(count)
        pct = float(percent[:-1])
        if not 95 <= eligible <= 120 or not 0 <= pct <= 100:
            continue
        above = round(pct*eligible/100)
        precision = len(percent.split(".")[-1][:-1]) if "." in percent else 0
        tolerance = .5*10**(-precision)+1e-7
        if abs(100*above/eligible-pct) > tolerance or sum(
            abs(100*n/eligible-pct) <= tolerance for n in range(eligible+1)
        ) != 1:
            continue
        candidates.append((ds, eligible, above, pct))
    if not candidates:
        raise ValueError("StockCurry: no verified dated MA50 table row")
    ds, eligible, above, pct = max(candidates)
    if len({x for x in candidates if x[0] == ds}) != 1:
        raise ValueError("StockCurry: conflicting rows for same date")
    below = eligible-above
    return {
        "schemaVersion": 1, "id": "ndx-ma50-breadth", "asOf": ds,
        "sourceUpdatedAt": None, "sourceReportedPct": pct,
        "eligibleSecurities": eligible, "aboveCount": above,
        "atOrBelowCount": below, "abovePct": round(100*above/eligible, 1),
        "belowPct": round(100*below/eligible, 1),
        "countedSecurityClasses": True,
        "source": "StockCurry · Nasdaq100 Timeline, > SMA50",
        "sourceUrl": STOCKCURRY_URL, "sourceDataUrl": STOCKCURRY_URL,
        "methodology": "Current Nasdaq-100 securities (not point-in-time members); provider's end-of-day percentage above own 50-session SMA and reported security denominator. Integer count reconstructed from the rounded percentage. Different providers may use different pricing histories and basket rules.",
        "feedStatus": "published",
    }

def fetch_stockcurry():
    req = Request(STOCKCURRY_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PayAndPray-Breadth/1.1)",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urlopen(req, timeout=25) as response:
        if response.status != 200:
            raise ValueError("StockCurry non-200 response")
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("StockCurry response too large")
        return raw.decode("utf-8")

def main():
    now = datetime.now(timezone.utc)
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    expected = expected_cash_date(now)
    snapshot = stockcurry_snapshot(fetch_stockcurry(), now, expected)
    # Validate the denominator against the official Nasdaq constituent list.
    members = json.loads((OUT.parent / "ndx-constituents.json").read_text(encoding="utf-8"))
    symbols = members.get("symbols", [])
    if (members.get("index") != "NDX" or
        members.get("sourceUrl") != "https://api.nasdaq.com/api/quote/list-type/nasdaq100" or
        not isinstance(symbols, list) or len(set(symbols)) != len(symbols) or
        not 95 <= len(symbols) <= 120 or snapshot["eligibleSecurities"] != len(symbols)):
        raise ValueError("Breadth denominator conflicts with official Nasdaq membership")
    checked_members = datetime.fromisoformat(members["checkedAtUtc"].replace("Z", "+00:00"))
    if not 0 <= (now-checked_members).total_seconds() <= 7*86400:
        raise ValueError("Official Nasdaq membership verification is stale")
    snapshot["constituentsSourceUrl"] = members["sourceUrl"]
    snapshot["constituentsCheckedAtUtc"] = members["checkedAtUtc"]
    # Never replace a newer observation with an older one.
    if snapshot["asOf"] < previous.get("asOf", ""):
        raise ValueError("Source predates the last published observation")
    checked_at = now.isoformat().replace("+00:00", "Z")
    if (previous.get("asOf", "") == snapshot["asOf"] and
        previous.get("sourceUrl") == STOCKCURRY_URL):
        # Do not silently revise a same-day count when providers disagree, and
        # never overwrite a newer observation with an older fallback.
        if (previous.get("aboveCount"), previous.get("eligibleSecurities")) != (snapshot["aboveCount"], snapshot["eligibleSecurities"]):
            raise ValueError("Conflicting same-session breadth values; retain prior observation")
        snapshot["collectedAtUtc"] = previous.get("collectedAtUtc", checked_at)
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


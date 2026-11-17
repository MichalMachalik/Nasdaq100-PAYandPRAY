#!/usr/bin/env python3
"""Refresh Top 10 Nasdaq-100 firms from CompaniesMarketCap by market capitalization."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

URL = "https://companiesmarketcap.com/tech/largest-tech-companies-by-market-cap/"
OUT = Path("data/top10.json")
# Nasdaq-100 constituent whitelist; not all tech firms on CompaniesMarketCap belong to Nasdaq-100.
# Includes a wider pool than today's top ten for changes to rankings.
ELIGIBLE = set((
    "NVDA AAPL MSFT GOOG GOOGL AMZN AVGO META TSLA MU AMD COST NFLX PLTR "
    "ASML CSCO AMAT LRCX INTC KLAC ANET CRWD ARM TXN MRVL PANW ADBE "
    "QCOM ISRG BKNG PDD INTU AMGN GILD SBUX ADP MELI MDLZ CDNS SNPS "
    "REGN ABNB APP MAR PYPL MSTR ORLY CEG CTAS CSX PCAR ROST FTNT "
    "ADSK EA DASH WDAY NXPI ODFL IDXX FAST PAYX KDP MNST CHPX "
    "TEAM DDOG ZS NET TTWO XEL FANG BKR"
).split())
ALIASES = {"GOOGL": "GOOG"}

def money(text):
    cleaned = text.replace(",", "").replace("$", "").replace("\u00a0", " ")
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*([TBM])?\b", cleaned, re.I)
    if not m:
        raise ValueError("Unparseable money: " + text[:70])
    return float(m.group(1)) * {"T": 1e12, "B": 1e9, "M": 1e6, None: 1}[m.group(2).upper() if m.group(2) else None]

def percent(cell):
    txt = cell.get_text(" ", strip=True).replace(",", ".")
    m = re.search(r"([-+−]?\d+(?:\.\d+)?)\s*%", txt)
    if not m:
        raise ValueError("Unparseable change: " + txt)
    num = float(m.group(1).replace("−", "-"))
    classes = " ".join(cell.get("class", []))
    if num > 0 and ("red" in classes or "negative" in classes or "down" in classes or "▼" in txt or "▾" in txt):
        num = -num
    return num

def retrieve():
    req = Request(URL, headers={"User-Agent":"Mozilla/5.0 (compatible; PayAndPrayMarketReport/1.0)","Accept":"text/html"})
    with urlopen(req, timeout=25) as response:
        html = response.read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    companies = {}
    print("DIAG", "len", len(html), "title", (soup.title.get_text(" ", strip=True) if soup.title else "-")[:110], "tables", len(soup.select("table")), "rows", len(soup.select("table tbody tr")), "tr", str(soup.select_one("tr"))[:600])
    for tr in soup.select("table tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        label = cells[1].get_text(" ", strip=True)
        try:
            ticker = next((t for t in ELIGIBLE if re.search(r"(?<![A-Z])"+re.escape(t)+r"(?![A-Z])", label)), None)
            if not ticker:
                continue
            ticker = ALIASES.get(ticker, ticker)
            cap, price, change = money(cells[2].get_text(" ", strip=True)), money(cells[3].get_text(" ", strip=True)), percent(cells[4])
            if cap < 1e9 or price <= 0 or not -80 <= change <= 80:
                continue
            link = cells[1].find("a")
            name = link.get_text(" ", strip=True) if link else label
            name = re.sub(r"\b(?:GOOG|GOOGL|"+re.escape(ticker)+r")\b\s*$", "", name).strip()
            obj = {"ticker": ticker, "name": name or ticker, "marketCapUsd": round(cap), "priceUsd": round(price, 2), "changePercent": round(change, 2)}
            if ticker not in companies or companies[ticker]["marketCapUsd"] < cap:
                companies[ticker] = obj
        except (ValueError, IndexError):
            continue
    ranked = sorted(companies.values(), key=lambda x: x["marketCapUsd"], reverse=True)[:10]
    if len(ranked) != 10:
        raise RuntimeError(f"Expected 10 constituents, found {len(ranked)} — refusing partial update")
    now = datetime.now(timezone.utc)
    return {"source": "CompaniesMarketCap", "sourceUrl": URL,
            "fetchedAtUtc": now.isoformat().replace("+00:00", "Z"),
            "fetchedAtPrague": now.astimezone(ZoneInfo("Europe/Prague")).strftime("%d. %m. %Y %H:%M"),
            "market": "Nasdaq-100", "currency": "USD", "companies": ranked}

if __name__ == "__main__":
    try:
        data = retrieve()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        if old.get("companies") != data["companies"] or not old.get("companies"):
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            print("Updated ten companies: " + ", ".join(x["ticker"] for x in data["companies"]))
        else:
            print("Ranking unchanged; no new price data")
    except Exception as exc:
        print("Top10 update FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)

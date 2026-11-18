#!/usr/bin/env python3
"""Publish independently source-dated commodities and EUR/USD, EUR/CZK, USD/CZK quotes."""
import calendar
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

OUT = Path("data/markets.json")
PAGES = {
    "commodities": "https://tradingeconomics.com/commodities",
    "currencies": "https://tradingeconomics.com/currencies",
}
ASSETS = [
    ("WTI", "USD/bbl", "https://tradingeconomics.com/commodity/crude-oil", 1, 500),
    ("Brent", "USD/bbl", "https://tradingeconomics.com/commodity/brent-crude-oil", 1, 500),
    ("Natural Gas", "USD/MMBtu", "https://tradingeconomics.com/commodity/natural-gas", .05, 100),
    ("Gasoline", "USD/gal", "https://tradingeconomics.com/commodity/gasoline", .05, 40),
    ("EU Gas", "EUR/MWh", "https://tradingeconomics.com/commodity/eu-natural-gas", .1, 1000),
    ("Gold", "USD/oz", "https://tradingeconomics.com/commodity/gold", 100, 20000),
    ("EUR/USD", "EUR/USD", "https://tradingeconomics.com/euro-area/currency", .4, 2.2),
    ("EUR/CZK", "EUR/CZK", "https://tradingeconomics.com/eurczk:cur", 10, 60),
    ("USD/CZK", "USD/CZK", "https://tradingeconomics.com/czech-republic/currency", 10, 60),
]
MONTHS = {name.lower():i for i,name in enumerate(calendar.month_name) if name}

def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = Request(url,headers=headers)
    with urlopen(req,timeout=25) as response:
        html = response.read().decode("utf-8",errors="replace")
    if len(html)<3000:
        raise ValueError("Unusually short instrument page")
    return BeautifulSoup(html,"html.parser")

def decimal(text):
    if not text:raise ValueError("Empty number")
    cleaned = text.replace(",","").replace("\xa0","").replace("−","-")
    m = re.search(r"[-+]?(?:\d+\.\d+|\d+|\.\d+)",cleaned)
    if not m:raise ValueError("Missing number "+text[:70])
    value=float(m.group())
    if not math.isfinite(value):raise ValueError("NaN value")
    return value

def date_from_description(description):
    # Metadata carries the provider's trading day; retrieval time is NOT quote time.
    m = re.search(r"\bon\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b",description or "")
    if not m:raise ValueError("Provider trading date not present in metadata")
    month=MONTHS.get(m.group(1).lower())
    if not month:raise ValueError("Unknown month "+m.group(1))
    return date(int(m.group(3)),month,int(m.group(2)))

def get_instrument(ident,unit,url,low,high,now):
    soup=fetch(url)
    val=soup.select_one("#market_last")
    day=soup.select_one("#market_daily_Pchg")
    meta=soup.find("meta",attrs={"id":"metaDesc"}) or soup.find("meta",attrs={"name":"description"})
    if val is None or day is None or meta is None:
        raise ValueError("Required live quote fields missing from "+url)
    value=decimal(val.get_text(" ",strip=True))
    change=decimal(day.get_text(" ",strip=True))
    try:
        asof=date_from_description(meta.get("content",""))
    except ValueError:
        if ident!="EUR/CZK":
            raise
        # EURCZK cross view lacks dated metadata. Validate its quote against the
        # cross on the same provider's dated Czech currency overview.
        companion=fetch("https://tradingeconomics.com/czech-republic/currency")
        date_meta=companion.find("meta",attrs={"id":"metaDesc"}) or companion.find("meta",attrs={"name":"description"})
        if date_meta is None:
            raise ValueError("Dated Czech currency reference not available")
        asof=date_from_description(date_meta.get("content",""))
        cross=None
        for a in companion.select("a"):
            if a.get_text(" ",strip=True).upper()=="EURCZK":
                tr=a.find_parent("tr")
                if tr:
                    cells=tr.find_all("td",recursive=False)
                    nums=[]
                    for cell in cells:
                        try: nums.append(decimal(cell.get_text(" ",strip=True)))
                        except ValueError: continue
                    if nums:
                        cross=next((z for z in nums if 10<=z<=60),None)
                        if cross is not None: break
        if cross is None or abs(cross/value-1)>0.02:
            raise ValueError(f"EURCZK undated quote cannot be cross-checked: EURCZK={value}, companion={cross}")
        print(f"EURCZK verified against dated CZK cross: {cross}, day={asof.isoformat()}",flush=True)
    if not low<=value<=high or not -60<=change<=60:
        raise ValueError("Out-of-range "+ident+" quote")
    if asof>now.date()+timedelta(days=1):
        raise ValueError("Future provider quote date for "+ident)
    return {
        "id":ident,"unit":unit,
        "price":value,"changePercent":change,
        "quoteDate":asof.strftime("%b/%d"),
        "quoteDateISO":asof.isoformat(),
        "sourceUrl":url,
        "fetchedAtUtc":now.isoformat().replace("+00:00","Z"),
    }

def main():
    now=datetime.now(timezone.utc)
    old=json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    previous={x.get("id"):x for x in old.get("quotes",[]) if isinstance(x,dict)}
    quotes=[]
    failed=[]
    for ident,unit,url,low,high in ASSETS:
        try:
            q=get_instrument(ident,unit,url,low,high,now)
            print(f"{ident}: {q['price']} {unit}, daily {q['changePercent']}%, dated {q['quoteDateISO']}",flush=True)
        except Exception as exc:
            if ident in previous:
                q=previous[ident]
                print(f"STALE {ident}: retained original price/date after {type(exc).__name__}: {exc}",flush=True)
            else:
                failed.append(ident)
                print(f"UNAVAILABLE {ident}: {type(exc).__name__}: {exc}",flush=True)
                continue
        quotes.append(q)
    if failed or len(quotes)!=len(ASSETS):
        raise RuntimeError("Incomplete nine-asset snapshot: "+",".join(failed))
    result={
        "source":"Trading Economics",
        "sourceUrls":PAGES,
        "timestampKind":"retrieval timestamp is separate from trading day",
        "fetchedAtUtc":now.isoformat().replace("+00:00","Z"),
        "fetchedAtPrague":now.astimezone(ZoneInfo("Europe/Prague")).strftime("%d. %m. %Y %H:%M"),
        "quotes":quotes,
    }
    if old.get("quotes")!=quotes:
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("Wrote nine price references with verified source dates",flush=True)
    else:print("Trading Economics prices unchanged; preserved original data",flush=True)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("Market quote update FAILED:",exc,file=sys.stderr,flush=True)
        raise SystemExit(1)

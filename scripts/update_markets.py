#!/usr/bin/env python3
"""Fetch dated Trading Economics market-reference quotes for the public dashboard."""
import calendar, json, math, re, sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

OUT=Path("data/markets.json")
PAGES={"commodities":"https://tradingeconomics.com/commodities",
       "currencies":"https://tradingeconomics.com/currencies"}
ASSETS=[
    ("WTI", "Crude Oil", "commodities", "USD/bbl", "https://tradingeconomics.com/commodity/crude-oil", 1,500),
    ("Brent", "Brent", "commodities", "USD/bbl", "https://tradingeconomics.com/commodity/brent-crude-oil", 1,500),
    ("Natural Gas", "Natural gas", "commodities", "USD/MMBtu", "https://tradingeconomics.com/commodity/natural-gas", .05,100),
    ("Gasoline", "Gasoline", "commodities", "USD/gal", "https://tradingeconomics.com/commodity/gasoline", .05,40),
    ("EU Gas", "EU Gas", "commodities", "EUR/MWh", "https://tradingeconomics.com/commodity/eu-natural-gas", .1,1000),
    ("Gold", "Gold", "commodities", "USD/oz", "https://tradingeconomics.com/commodity/gold", 100,20000),
    ("EUR/USD", "EURUSD", "currencies", "USD/EUR", "https://tradingeconomics.com/euro-area/currency", .4,2.2)]
MONTHS={name.lower():i for i,name in enumerate(calendar.month_abbr) if name}
MONTHS.update({name.lower():i for i,name in enumerate(calendar.month_name) if name})

def get_page(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36","Accept":"text/html,application/xhtml+xml","Accept-Language":"en-US,en;q=0.9"})
    with urlopen(req,timeout=24) as response: html=response.read().decode("utf-8",errors="replace")
    if len(html)<2000: raise ValueError("Short Trading Economics HTML "+url)
    soup=BeautifulSoup(html,"html.parser")
    print(f"Retrieved {url}: {len(html)} characters, {len(soup.select('tr'))} table rows",flush=True)
    if not soup.select("tr"):
        for term in ("TELastUpdate", "markets/commodities", "assetQuote", "loader", "Price", "GetMarkets", "json", "ChartData"):
            at=html.lower().find(term.lower())
            if at>=0: print("PAGE_DIAG",term,at,repr(html[max(0,at-120):at+270]),flush=True)
        print("INLINE_JS_COUNT",len(soup.find_all("script")),"TABLES",len(soup.find_all("table")),flush=True)
    return soup

def numeric(text):
    m=re.search(r"[-+]?(?:\d+\.\d+|\d+|\.\d+)",text.replace("\xa0","").replace("−","-").replace(",",""))
    if not m: raise ValueError("Numeric parse failed: "+text[:60])
    v=float(m.group())
    if not math.isfinite(v):raise ValueError("Non-finite price")
    return v

def source_date(text,now):
    m=re.search(r"\b([A-Za-z]{3,9})[\s/.-]+(\d{1,2})(?:[\s/.-]+(\d{4}))?\b",text or "")
    if not m: return None
    month=MONTHS.get(m.group(1).lower())
    if not month:return None
    year=int(m.group(3)) if m.group(3) else now.year
    try:dt=date(year,month,int(m.group(2)))
    except ValueError:return None
    if not m.group(3) and dt>now.date()+timedelta(days=1):dt=dt.replace(year=year-1)
    return dt.isoformat()

def extract(soup,label,now):
    for a in soup.select("tr a"):
        if re.sub(r"\s+"," ",a.get_text(" ",strip=True)).casefold()!=label.casefold():continue
        tr=a.find_parent("tr"); td=a.find_parent("td")
        if tr is None or td is None:continue
        cells=tr.find_all("td",recursive=False)
        if td not in cells:continue
        i=cells.index(td)
        if len(cells)<=i+3:continue
        contents=[c.get_text(" ",strip=True) for c in cells]
        try:
            price=numeric(contents[i+1]); change=numeric(contents[i+3])
        except (ValueError,IndexError):continue
        raw_date=contents[i+5] if len(contents)>i+5 else ""
        asof=source_date(raw_date,now)
        return {"price":price,"changePercent":change,"quoteDate":raw_date or None,"quoteDateISO":asof,"sample":str(tr)[:700]}
    return None


def probe_alternatives():
    urls=[item[4] for item in ASSETS]
    for url in urls:
        try:
            req=Request(url,headers={"User-Agent":"Mozilla/5.0"})
            with urlopen(req,timeout=10) as r:
                text=r.read().decode("utf-8",errors="replace")
                print("ALT_DIAG",url,"length",len(text),"body",repr(text[:160]),flush=True)
                if "/commodity/" in url or "euro-area" in url:
                    soup=BeautifulSoup(text,"html.parser")
                    for name in ("description","og:description"):
                        tag=soup.find("meta",attrs={"name":name}) or soup.find("meta",attrs={"property":name})
                        if tag:print("ALT_META",name,repr(tag.get("content","")[:500]),flush=True)
                    for node in soup.select('[id^="market_"], [id*="last"], [id*="chg"], [id*="daily"]')[:22]:
                        print("ALT_ELEMENT",node.get("id"),node.name,repr(node.get_text(" ",strip=True)[:125]),flush=True)
                    for term in ("Daily Change","Crude Oil - Stats","EUR/USD"):
                        at=text.find(term)
                        if at>=0:print("ALT_MATCH",term,repr(text[max(0,at-70):at+160]),flush=True)
        except Exception as e:print("ALT_ERROR",url,type(e).__name__,str(e)[:180],flush=True)

def main():
    now=datetime.now(timezone.utc)
    pages={name:get_page(url) for name,url in PAGES.items()}
    if all(not soup.select("tr") for soup in pages.values()):probe_alternatives()
    old=json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    previous={q.get("id"):q for q in old.get("quotes",[]) if isinstance(q,dict)}
    quotes=[];missing=[]
    for ident,label,page,unit,url,minprice,maxprice in ASSETS:
        candidate=extract(pages[page],label,now)
        if candidate and minprice<=candidate["price"]<=maxprice and -60<=candidate["changePercent"]<=60 and candidate["quoteDateISO"]:
            q={"id":ident,"unit":unit,"price":candidate["price"],"changePercent":candidate["changePercent"],
               "quoteDate":candidate["quoteDate"],"quoteDateISO":candidate["quoteDateISO"],
               "sourceUrl":url,"fetchedAtUtc":now.isoformat().replace("+00:00","Z")}
            print(f"{ident}: {q['price']} {unit}, {q['changePercent']}%, source date {q['quoteDateISO']}",flush=True)
        elif ident in previous:
            q=previous[ident]
            print(f"STALE {ident}: kept original dated quote",flush=True)
        else:
            print(f"MISSING {ident}: raw={candidate}",flush=True)
            missing.append(ident);continue
        quotes.append(q)
    if missing or len(quotes)!=7:
        raise RuntimeError("Insufficient verified rows: "+",".join(missing))
    output={"source":"Trading Economics","sourceUrls":PAGES,"timestampKind":"retrieval; source trading dates are day precision",
            "fetchedAtUtc":now.isoformat().replace("+00:00","Z"),
            "fetchedAtPrague":now.astimezone(ZoneInfo("Europe/Prague")).strftime("%d. %m. %Y %H:%M"),"quotes":quotes}
    if old.get("quotes")!=quotes or not old.get("quotes"):
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print("Saved seven source-dated market references",flush=True)
    else: print("No quote values changed; provider dates not refreshed",flush=True)

if __name__=="__main__":
    try:main()
    except Exception as e:
        print("Markets update FAILED:",e,file=sys.stderr,flush=True)
        raise SystemExit(1)

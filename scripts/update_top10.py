#!/usr/bin/env python3
"""Rank verified Nasdaq-100 constituents by company market cap, across all sectors.
Membership: Nasdaq's current index endpoint, never a hand-maintained ticker list.
Quotes: CompaniesMarketCap's global ranking, never the technology-only category.
Fail closed on stale membership, incomplete coverage or ambiguous quote signs.
"""
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

MEMBERS_URL = 'https://api.nasdaq.com/api/quote/list-type/nasdaq100'
SOURCE_URL = 'https://companiesmarketcap.com/'
OUT = Path('data/top10.json')
MEMBERS_OUT = Path('data/ndx-constituents.json')
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.9',
           'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}


def fetch(url, accept='text/html'):
    request = Request(url, headers={**HEADERS, 'Accept': accept})
    with urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8')


def parse_date(value):
    text = str(value or '').strip()
    for form in ('%b %d, %Y', '%b %d, %Y %I:%M %p', '%B %d, %Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            pass
    raise ValueError('Unrecognized membership date: '+repr(value))


def validate_members(symbols, source_date, now):
    if not 99 <= len(symbols) <= 110 or not all(re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}', t) for t in symbols):
        raise ValueError('Nasdaq membership is incomplete or malformed: '+str(len(symbols)))
    age = (now.astimezone(ZoneInfo('America/New_York')).date()-source_date).days
    if age < -1 or age > 7:
        raise ValueError('Stale Nasdaq membership date: '+source_date.isoformat())


def current_members(now):
    try:
        payload = json.loads(fetch(MEMBERS_URL, 'application/json'))
    except (URLError, TimeoutError):
        if not MEMBERS_OUT.exists():
            raise
        saved = json.loads(MEMBERS_OUT.read_text(encoding='utf-8'))
        if saved.get('sourceUrl') != MEMBERS_URL or saved.get('index') != 'NDX':
            raise ValueError('Cached membership source is unverified')
        symbols = set(saved['symbols'])
        source_date = parse_date(saved['sourceDate'])
        validate_members(symbols, source_date, now)
        return symbols, source_date.isoformat(), False
    data = payload.get('data') or {}
    rows = (data.get('data') or {}).get('rows') or []
    if data.get('totalrecords') is not None and int(data['totalrecords']) != len(rows):
        raise ValueError('Nasdaq membership response is paginated or truncated')
    symbols = {str(row.get('symbol', '')).strip().upper() for row in rows}
    source_date = parse_date(data.get('date'))
    validate_members(symbols, source_date, now)
    return symbols, source_date.isoformat(), True


def money(text):
    text = text.replace(',', '').replace('\u00a0', ' ').strip()
    match = re.fullmatch(r'\$?\s*(\d+(?:\.\d+)?)\s*([TBM])?', text, re.I)
    if not match:
        raise ValueError('Unparseable USD value: '+repr(text))
    unit = (match.group(2) or '').upper()
    value = float(match.group(1))*{'T': 1e12, 'B': 1e9, 'M': 1e6, '': 1}[unit]
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid USD value')
    return value


def daily_change(cell):
    text = cell.get_text(' ', strip=True).replace('\u2212', '-').replace(',', '.')
    match = re.search(r'([+\-]?\d+(?:\.\d+)?)\s*%', text)
    if not match:
        raise ValueError('Missing daily percentage')
    value = float(match.group(1))
    if abs(value) > 100:
        raise ValueError('Unexpected daily percentage')
    if value == 0 or match.group(1).startswith(('+', '-')):
        return value
    tokens = ' '.join(' '.join(node.get('class', [])) for node in [cell, *cell.find_all(True)]).lower()
    down = any(word in tokens for word in ('red','negative','down')) or any(c in text for c in ('▼','▾','↘'))
    up = any(word in tokens for word in ('green','positive','up')) or any(c in text for c in ('▲','▴','↗'))
    if down == up:
        raise ValueError('Ambiguous daily percentage sign')
    return -value if down else value


def company_key(ticker):
    # Company-level market cap counts Alphabet once, not once per share class.
    return 'ALPHABET' if ticker in ('GOOG', 'GOOGL') else ticker


def ranked_page(html, eligible):
    soup = BeautifulSoup(html, 'html.parser')
    for table in soup.select('table'):
        headers = [node.get_text(' ', strip=True).lower() for node in table.select('thead th')]
        if not {'rank','name','market cap','price','today'}.issubset(headers):
            continue
        positions = {key: headers.index(key) for key in ('rank','name','market cap','price','today')}
        all_rows, included = [], {}
        for tr in table.select('tbody tr'):
            cells = tr.find_all('td', recursive=False)
            if len(cells) < len(headers):
                continue
            rank_text = cells[positions['rank']].get_text('', strip=True).replace(',', '')
            if not rank_text.isdigit():
                continue
            rank = int(rank_text)
            name_cell = cells[positions['name']]
            ticker_node = name_cell.select_one('.company-code')
            if ticker_node is None:
                raise ValueError('Missing exact ticker field at global rank '+str(rank))
            ticker = ticker_node.get_text('', strip=True).strip()
            cap = money(cells[positions['market cap']].get_text(' ', strip=True))
            all_rows.append((rank,cap))
            if ticker not in eligible:
                continue
            price = money(cells[positions['price']].get_text(' ', strip=True))
            change = daily_change(cells[positions['today']])
            name_node = name_cell.select_one('.company-name')
            name = name_node.get_text(' ', strip=True) if name_node else ticker
            link = name_cell.select_one('a[href]')
            item = {'ticker':ticker,'name':name,'marketCapUsd':round(cap),
                    'priceUsd':round(price,2),'changePercent':round(change,2),
                    'sourceUrl':urljoin(SOURCE_URL,link['href']) if link else SOURCE_URL,
                    'indexMembershipVerified':True}
            key = company_key(ticker)
            # Preserve the displayed class's own price, without adding duplicate company caps.
            if key not in included or ticker == 'GOOG':
                included[key] = item
        all_rows.sort()
        ranks = [rank for rank,_ in all_rows]
        if len(ranks) < 50 or ranks != list(range(1,len(ranks)+1)):
            raise ValueError('Global company ranking coverage is incomplete')
        caps = [cap for _,cap in all_rows]
        if any(a < b*0.999 for a,b in zip(caps,caps[1:])):
            raise ValueError('Global ranking is not sorted by market cap')
        top = sorted(included.values(),key=lambda item:item['marketCapUsd'],reverse=True)[:10]
        if len(top) != 10 or top[-1]['marketCapUsd'] <= caps[-1]:
            raise ValueError('Insufficient global ranking coverage for the full Top 10')
        return top, len(all_rows), len(included)
    raise ValueError('CompaniesMarketCap global ranking table was not found')


def atomic_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def retrieve():
    now = datetime.now(timezone.utc)
    eligible, source_date, refreshed = current_members(now)
    print('Membership:',len(eligible),'securities, Nasdaq date',source_date,
          '(retrieved)' if refreshed else '(saved Nasdaq snapshot)')
    top, coverage, candidates = ranked_page(fetch(SOURCE_URL), eligible)
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat().replace('+00:00','Z')
    output = {'source':'CompaniesMarketCap','sourceUrl':SOURCE_URL,'market':'Nasdaq-100','currency':'USD',
              'fetchedAtUtc':timestamp,
              'fetchedAtPrague':now.astimezone(ZoneInfo('Europe/Prague')).strftime('%d. %m. %Y %H:%M'),
              'timestampKind':'retrieval; quote time not supplied by source',
              'constituentsSourceUrl':MEMBERS_URL,'constituentsAsOf':source_date,
              'membershipLookup':'retrieved' if refreshed else 'cached',
              'constituentSecurityCount':len(eligible),'rankingScope':'all sectors; company market cap',
              'globalCompaniesChecked':coverage,'eligibleCompaniesCompared':candidates,
              'companies':top}
    membership = {'index':'NDX','sourceUrl':MEMBERS_URL,'sourceDate':source_date,
                  'checkedAtUtc':timestamp,'symbols':sorted(eligible)}
    # Update the check timestamp even if prices are unchanged; it is not a quote timestamp.
    if refreshed:
        atomic_json(MEMBERS_OUT,membership)
    atomic_json(OUT,output)
    print('Verified Top 10: '+', '.join(item['ticker'] for item in top))


if __name__ == '__main__':
    try:
        retrieve()
    except Exception as exc:
        print('Top10 update FAILED; previous snapshot preserved: '+str(exc),file=sys.stderr)
        raise SystemExit(1)

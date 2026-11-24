#!/usr/bin/env python3
"""Idempotent report migration plus JavaScript syntax and DOM regression checks."""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup

PAGE = Path('index.html')


def prepare():
    original = PAGE.read_text(encoding='utf-8')
    html = original
    # Regulation belongs in sourced news items, not an always-visible placeholder.
    html, count = re.subn(
        r'<section\b[^>]*>\s*<h2\b[^>]*>AI regulace</h2>\s*<div\b[^>]*\bid="regulation"[^>]*>[^<]*</div>\s*</section>',
        '', html)
    if count > 1:
        raise ValueError('Unexpected duplicate regulation sections')
    html = html.replace("setSentences('regulation',d.regulation||'Bez zveřejněné aktualizace');", '')
    # Remove the obsolete renderer: its target was replaced by the Top 10 table.
    html = re.sub(r"^rows\('leaders',d\.leaders,.*?\);\s*$", '', html, flags=re.MULTILINE)
    html = html.replace("const set=(id,v)=>{$(id).textContent=safe(v)};",
                        "const set=(id,v)=>{const el=$(id);if(el)el.textContent=safe(v)};")
    html = html.replace("let root=$(id);root.replaceChildren();", "let root=$(id);if(!root)return;root.replaceChildren();")
    # Use the all-sector source; the tech-only list omits non-tech constituents.
    html = html.replace('href="https://companiesmarketcap.com/tech/largest-tech-companies-by-market-cap/"',
                        'href="https://companiesmarketcap.com/"')
    html = html.replace("'Data '+data.fetchedAtPrague+' Praha'", "'Načteno '+data.fetchedAtPrague+' Praha'")
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('#regulation') or soup.find('h2', string='AI regulace'):
        raise ValueError('The standalone regulation section remains')
    ids = [node['id'] for node in soup.select('[id]')]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate DOM ids')
    required = {'news','top10-body','top10-time','macro','driver','forecast-ath',
                'forecast-down','futures-price','refresh','updated','archive','commodity-rows','fx-rows','commodities-updated','fx-updated','policy-rates','quarterly-gdp'}
    if not required.issubset(ids):
        raise ValueError('Missing dashboard DOM targets: '+str(required-set(ids)))
    # Validate the period and comparison for each quarterly growth figure.
    econ = json.loads(Path('data/economy.json').read_text(encoding='utf-8'))
    if {x['id'] for x in econ.get('rates',[])} != {'FED','ECB','ČNB'}:
        raise ValueError('Missing official central bank reference rates')
    if {x['id'] for x in econ.get('gdp',[])} != {'USA','EU','ČR'}:
        raise ValueError('Missing verified GDP regions')
    if any(x.get('comparison') != 'y/y' or
           not re.fullmatch(r'\d{4}-Q[1-4]', x.get('period', ''))
           for x in econ['gdp']):
        raise ValueError('GDP must be y/y growth for a quarterly period, not q/q SAAR')
    if not all(isinstance(x.get('valuePercent'), (int, float)) for x in econ['gdp']):
        raise ValueError('GDP values missing')
    if html.count('</html>') != 1 or html.count('</body>') != 1:
        raise ValueError('Duplicate document endings')
    scripts = [node.get_text() for node in soup.select('script:not([src])')
               if node.get('type', '') not in ('application/json','application/ld+json')]
    code = '\n'.join(scripts)
    if "rows('leaders'" in code:
        raise ValueError('Obsolete market mover renderer remains')
    if 'function loadTop10' not in code or 'function loadFutures' not in code or 'function loadMarkets' not in code or 'function loadEconomy' not in code:
        raise ValueError('Quote or ranking loader is missing')
    with tempfile.TemporaryDirectory() as directory:
        check = Path(directory)/'dashboard.js'
        check.write_text(code, encoding='utf-8')
        subprocess.run(['node','--check',str(check)],check=True)
        # Execute the real report renderer against current JSON, not just parse syntax.
        prefix = r'''const vm=require('node:vm'); const fs=require('node:fs');
function element(){return {textContent:'',className:'',children:[],childNodes:[],style:{},classList:{add(){}},append(...x){this.children.push(...x);this.childNodes.push(...x)},replaceChildren(...x){this.children=x;this.childNodes=x},addEventListener(){},querySelector(){return null}}}
const ids=JSON.parse(process.argv[3]);const nodes=Object.fromEntries(ids.map(id=>[id,element()]));
const context={console,URL,Date,Intl,Number,String,Math,Array,Set,Map,Promise,
 document:{hidden:true,getElementById:id=>nodes[id]||null,createElement:element,createTextNode:t=>({textContent:t}),createDocumentFragment:element,querySelector:()=>null,addEventListener(){}},
 window:{location:{href:'https://example.invalid/',replace(){}}},setInterval(){},
 fetch:()=>new Promise(()=>{})};vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
context.__fixture=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));vm.runInContext('render(__fixture)',context);
const filled=n=>Boolean(n.textContent?.trim())||Boolean(n.children?.length)||Boolean(n.childNodes?.length);
if(!filled(nodes['forecast-down'])||!filled(nodes.macro))throw Error('Incomplete report render');
// Editorial regression: exercise exactly the formatter used by news and narratives.
const editorialFixtures=[{"input":"HPE Q4: tržby 14,55 mld. USD vs. kons. 14,43 (beat 0,8 %). Upr.\nEPS 1,43 USD vs. kons. 1,28 (beat 11,7 %). Cloud & AI 11,3 mld. USD, 68,6 % y/y. Q1 výhled tržeb 14,0–14,6 mld. USD, upr. EPS 1,30–1,40 USD.","colors":[["beat 0,8 %","up"],["beat 11,7 %","up"],["68,6 %","up"]]},{"input":"US flash PMI: Composite 54,6 vs. 55,9 (−1,3 b.); služby 54,7 vs. 56,1 (−1,4 b.); výroba 54,5 vs. 54,9 (−0,4 b.).","colors":[["1,3 b.","down"],["1,4 b.","down"],["0,4 b.","down"]]},{"input":"Dell Q3 očekávaný růst tržeb 82,6 %. Hedgeové fondy: týdenní ztráta přes 3 %. NQ futures: odraz téměř 3 %.","colors":[["82,6 %","up"],["3 %","down"],["3 %","up"]]},{"input":"NVDA +31,48 %, SOX +14,03 %. NDX −5,61 %. EPS miss 2,1 %.","colors":[["31,48 %","up"],["14,03 %","up"],["5,61 %","down"],["miss 2,1 %","down"]]},{"input":"Inflace 3,5 % y/y, návrat k 2% cíli; MA50 breadth 31,7 %; margin ratio 120 % z 130 %; výhled 5-7 %, 5 – 7 %, 5 - 7 %; nulová změna +0 %.","colors":[]},{"input":"Pokles tržeb 5 % y/y. Růst cen o 2,1 %. Změna −25 bb a +12 bps.","colors":[["5 %","down"],["2,1 %","up"],["25 bb","down"],["12 bps","up"]]},{"input":"<img src=x onerror=alert(1)>; sazba 4,92 %. Tržby 14,0–14,6 mld. USD.","colors":[]},{"input":"Data 15.–16. 11. CET. St. Louis Fed: 4,92 %. Upr. EPS 1,43 USD.","colors":[]}];
context.__editorialFixtures=editorialFixtures;
vm.runInContext(`for(const f of __editorialFixtures){const got=narrativeParts(sentenceBreaks(f.input)).filter(p=>p.kind).map(p=>[protectNarrativeText(p.text).replace(/[\\u00a0\\u202f]/g,' '),p.kind]);if(JSON.stringify(got)!==JSON.stringify(f.colors))throw Error('Editorial color regression: '+f.input+' => '+JSON.stringify(got));}if(!sentenceBreaks(__editorialFixtures[0].input).includes('\\nUpr. EPS')||sentenceBreaks(__editorialFixtures[0].input).includes('upr.\\nEPS'))throw Error('Abbreviation split');if(!protectNarrativeText('Upr. EPS 1,43 USD').includes('Upr.\\u00a0EPS'))throw Error('Nonbreaking abbreviation');`,context);
console.log('PASS: editorial HPE, abbreviations, directional percentages, points and neutral ranges');
vm.runInContext("if(rsiState(42)[0]!=='Mírná převaha poklesové dynamiky'||rsiState(20)[1]!=='green'||rsiState(80)[1]!=='red'||vxnState(36.31)[1]!=='amber'||vxnState(45)[1]!=='red'||cashObservationDate({asOf:'23. 11. 2026 – závěr Nasdaq'})!=='2026-11-23')throw Error('Indicator gauge regression');",context);
for(const id of ['rsi-pointer','rsi-track','rsi-state','rsi-date','vxn-value','vxn-pointer','vxn-track','vxn-state','vxn-date','breadth-source-link','breadth-freshness'])if(!nodes[id])throw Error('Missing indicator DOM target: '+id);
console.log('PASS: RSI/VXN gauges, dated observation and breadth source controls');
console.log('PASS: report renderer, macro, forecasts and DOM targets');
'''
        harness = Path(directory)/'check.cjs'
        harness.write_text(prefix,encoding='utf-8')
        subprocess.run(['node',str(harness),str(check),json.dumps(ids),'data/latest.json'],check=True)
    if html != original:
        PAGE.write_text(html, encoding='utf-8')
    print('PASS: no standalone AI regulation, intact Top 10, commodities, FX and quote loaders')


if __name__ == '__main__':
    prepare()

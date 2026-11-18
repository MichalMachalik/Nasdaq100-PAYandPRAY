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
    # Economy data must be official, complete, and explicitly YoY for Q3 2026.
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
        fixture = json.loads(Path('data/latest.json').read_text(encoding='utf-8'))
        prefix = r'''const vm=require('node:vm'); const fs=require('node:fs');
function element(){return {textContent:'',className:'',children:[],childNodes:[],style:{},classList:{add(){}},append(...x){this.children.push(...x);this.childNodes.push(...x)},replaceChildren(...x){this.children=x;this.childNodes=x},addEventListener(){},querySelector(){return null}}}
const ids=JSON.parse(process.argv[3]);const nodes=Object.fromEntries(ids.map(id=>[id,element()]));
const context={console,URL,Date,Intl,Number,String,Math,Array,Set,Map,Promise,
 document:{hidden:true,getElementById:id=>nodes[id]||null,createElement:element,createTextNode:t=>({textContent:t}),createDocumentFragment:element,querySelector:()=>null,addEventListener(){}},
 window:{location:{href:'https://example.invalid/',replace(){}}},setInterval(){},
 fetch:()=>new Promise(()=>{})};vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
context.__fixture=JSON.parse(process.argv[4]);vm.runInContext('render(__fixture)',context);
const filled=n=>Boolean(n.textContent?.trim())||Boolean(n.children?.length)||Boolean(n.childNodes?.length);
if(!filled(nodes['forecast-down'])||!filled(nodes.macro))throw Error('Incomplete report render');
console.log('PASS: report renderer, macro, forecasts and DOM targets');
'''
        harness = Path(directory)/'check.cjs'
        harness.write_text(prefix,encoding='utf-8')
        subprocess.run(['node',str(harness),str(check),json.dumps(ids),json.dumps(fixture)],check=True)
    if html != original:
        PAGE.write_text(html, encoding='utf-8')
    print('PASS: no standalone AI regulation, intact Top 10, commodities, FX and quote loaders')


if __name__ == '__main__':
    prepare()

"""Offline regressions for 24/7 checks without fabricated market timestamps."""
import io
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import update_breadth as breadth
import update_oversold as oversold
import update_risk_model as risk


class Clock(datetime):
    current = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class FuturesChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        before = Path.cwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, before)
        Clock.current = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        self.out = Path("data/futures.json")
        self.last_quote = 1795211999  # Friday 2026-11-20 21:59:59 UTC

    def update(self, *, market_time=None, market_price=25126.5,
               timestamps=(), closes=(), symbol="NQ=F"):
        payload = {"chart": {"result": [{
            "meta": {"symbol": symbol, "regularMarketTime": market_time,
                     "regularMarketPrice": market_price, "chartPreviousClose": 26600.25},
            "timestamp": timestamps, "indicators": {"quote": [{"close": closes}]},
        }]}}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())), \
                patch("datetime.datetime", Clock):
            runpy.run_path(str(SCRIPTS / "update_futures.py"))
        return json.loads(self.out.read_text())

    def test_newer_timestamped_metadata_beats_last_five_minute_bar(self):
        row = self.update(market_time=self.last_quote, timestamps=[1795211700], closes=[25291])
        self.assertEqual((row["price"], row["quoteField"]), (25126.5, "regularMarketPrice"))
        self.assertEqual(row["quotedAtUtc"], "2026-11-20T21:59:59Z")
        self.assertEqual(row["changePercent"], -5.54)

    def test_newer_bar_wins_and_future_metadata_is_not_published(self):
        for meta_time in (self.last_quote - 60, int(Clock.current.timestamp()) + 3600):
            with self.subTest(meta_time=meta_time):
                row = self.update(market_time=meta_time, timestamps=[self.last_quote], closes=[25126.5])
                self.assertEqual(row["quoteField"], "intradayClose")
                self.assertEqual(row["quotedAtUtc"], "2026-11-20T21:59:59Z")

    def test_weekend_check_advances_without_relabeling_friday_price(self):
        first = self.update(market_time=self.last_quote)
        Clock.current += timedelta(hours=1)
        second = self.update(market_time=self.last_quote)
        self.assertEqual(first["quotedAtUtc"], second["quotedAtUtc"])
        self.assertEqual(first["quotedAtPrague"], second["quotedAtPrague"])
        self.assertEqual(first["price"], second["price"])
        self.assertNotEqual(first["checkedAtUtc"], second["checkedAtUtc"])
        self.assertEqual(second["quoteStatus"], "stale")
        self.assertTrue(second["delayed"])

    def test_invalid_or_older_feed_cannot_overwrite_or_claim_a_successful_check(self):
        self.update(market_time=self.last_quote)
        before = self.out.read_bytes()
        for params in ({"market_time": self.last_quote - 1},
                       {"market_time": int(Clock.current.timestamp()) + 3600},
                       {"market_time": self.last_quote, "market_price": 0},
                       {"market_time": self.last_quote, "symbol": "OTHER"}, {}):
            with self.subTest(params=params), self.assertRaises(SystemExit):
                self.update(**params)
            self.assertEqual(self.out.read_bytes(), before)


class DailySourceChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.out = Path(directory.name) / "snapshot.json"
        Clock.current = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        self.old_checked = "2026-11-21T08:00:00Z"

    def test_unchanged_rsi_keeps_observation_and_collection_time(self):
        last = datetime(2026, 11, 20, tzinfo=timezone.utc)
        history = [((last - timedelta(days=59-i)).date().isoformat(), 26000-i*10)
                   for i in range(60)]
        previous = oversold.build_snapshot(history)
        previous.update(collectedAtUtc=self.old_checked, checkedAtUtc=self.old_checked)
        self.out.write_text(json.dumps(previous))
        with patch.object(oversold, "OUT", self.out), patch.object(oversold, "datetime", Clock), \
                patch.object(oversold, "fetch_history", return_value={}), \
                patch.object(oversold, "parse_daily_closes", return_value=history):
            oversold.main()
        result = json.loads(self.out.read_text())
        checked = result.pop("checkedAtUtc")
        previous.pop("checkedAtUtc")
        self.assertEqual(result, previous)
        self.assertEqual(checked, "2026-11-22T12:00:00Z")

    def test_unchanged_breadth_keeps_source_day_and_collection_time(self):
        html = """<table><tr><th>Date</th><th>Total Stocks</th><th>&gt; SMA50</th></tr>
        <tr><td>2026-11-20</td><td>101</td><td>31.68%</td></tr></table>"""
        members = self.out.parent / "ndx-constituents.json"
        symbols = ["T"+str(i) for i in range(101)]
        members.write_text(json.dumps({"index":"NDX","sourceUrl":"https://api.nasdaq.com/api/quote/list-type/nasdaq100",
                                       "symbols":symbols,"checkedAtUtc":self.old_checked}))
        previous = breadth.stockcurry_snapshot(html, Clock.current)
        previous.update(collectedAtUtc=self.old_checked, checkedAtUtc=self.old_checked,
                        constituentsSourceUrl="https://api.nasdaq.com/api/quote/list-type/nasdaq100",
                        constituentsCheckedAtUtc=self.old_checked)
        self.out.write_text(json.dumps(previous))
        with patch.object(breadth, "OUT", self.out), patch.object(breadth, "datetime", Clock), \
                patch.object(breadth, "fetch_stockcurry", return_value=html):
            breadth.main()
        result = json.loads(self.out.read_text())
        checked = result.pop("checkedAtUtc")
        previous.pop("checkedAtUtc")
        self.assertEqual(result, previous)
        self.assertEqual(checked, "2026-11-22T12:00:00Z")

    def run_risk_check(self, fail_treasury=False, fail_all=False):
        # A fixed Sunday fixture must not depend on the live file advancing
        # to a later trading date after this regression test is published.
        model = {
            "schemaVersion": 1,
            "id": "ndx-evidence-volatility-v1",
            "market": {
                "vxnPct": 45.25, "vxnAsOf": "2026-11-20",
                "vxnSource": "https://finance.yahoo.com/quote/%5EVXN/",
                "vxnQuoteKind": "daily-close", "vxnChangePercent": None,
                "vxnPreviousClose": None, "vxnPreviousCloseAsOf": None,
                "vxnRetrievedAtUtc": self.old_checked,
                "treasury2yPct": 4.63, "treasury10yPct": 4.92,
                "treasury30yPct": 5.31, "treasuryAsOf": "2026-11-20",
            },
        }
        model["checkedAtUtc"] = self.old_checked
        model["market"].update(vxnCheckedAtUtc=self.old_checked,
                               treasuryCheckedAtUtc=self.old_checked)
        self.out.write_text(json.dumps(model))
        values = model["market"]
        vxn = json.dumps({"chart": {"result": [{"meta": {"symbol": "^VXN"},
                         "timestamp": [1795194000],
                         "indicators": {"quote": [{"close": [values["vxnPct"]]}]}}]}})
        treasury = "Date,2-year,10-year,30-year\n11/20/2026,{},{},{}\n".format(
            values["treasury2yPct"], values["treasury10yPct"], values["treasury30yPct"])
        def fetch(url):
            if fail_all or (fail_treasury and url != risk.VXN_URL):
                raise OSError("source unavailable")
            return vxn if url == risk.VXN_URL else treasury
        with patch.object(risk, "OUT", self.out), patch.object(risk, "datetime", Clock), \
                patch.object(risk, "fetch", side_effect=fetch):
            if fail_all:
                before = self.out.read_bytes()
                with self.assertRaises(SystemExit):
                    risk.main()
                self.assertEqual(before, self.out.read_bytes())
            else:
                risk.main()
        return model, json.loads(self.out.read_text())

    def test_risk_unchanged_success_records_both_checks_not_new_observations(self):
        before, after = self.run_risk_check()
        self.assertEqual(after["checkedAtUtc"], "2026-11-22T12:00:00Z")
        for key in ("vxnCheckedAtUtc", "treasuryCheckedAtUtc"):
            self.assertEqual(after["market"].pop(key), "2026-11-22T12:00:00Z")
            before["market"].pop(key)
        self.assertEqual(after["market"].pop("vxnRetrievedAtUtc"), "2026-11-22T12:00:00Z")
        before["market"].pop("vxnRetrievedAtUtc")
        after.pop("checkedAtUtc")
        before.pop("checkedAtUtc")
        self.assertEqual(after, before)

    def test_risk_partial_failure_does_not_refresh_failed_source_or_whole_model(self):
        before, after = self.run_risk_check(fail_treasury=True)
        self.assertEqual(after["market"]["vxnCheckedAtUtc"], "2026-11-22T12:00:00Z")
        self.assertEqual(after["market"]["treasuryCheckedAtUtc"], self.old_checked)
        self.assertEqual(after["checkedAtUtc"], before["checkedAtUtc"])

    def test_risk_all_failed_preserves_snapshot(self):
        self.run_risk_check(fail_all=True)


class ScheduleAndDisplayChecks(unittest.TestCase):
    def test_every_existing_data_workflow_runs_all_days_at_least_hourly(self):
        files = list((ROOT / ".github/workflows").glob("*.yml"))
        self.assertGreaterEqual(len(files), 7)
        for path in files:
            cron = re.search(r'cron:\s*[\"\x27]([^\"\x27]+)', path.read_text())
            self.assertIsNotNone(cron, path.name)
            minute, hour, dom, month, dow = cron.group(1).split()
            self.assertEqual((hour, dom, month, dow), ("*", "*", "*", "*"), path.name)
            if path.name == "futures.yml":
                self.assertEqual(minute, "*/5")

    def test_weekend_quote_is_visible_with_original_time_and_stale_label(self):
        source = (ROOT / "index.html").read_text()
        scripts = "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", source))
        fixture = {"symbol": "NQ=F", "instrumentType": "FUTURES", "price": 25126.5,
                   "changePercent": -5.54, "quotedAtUtc": "2026-11-20T21:59:59Z",
                   "quotedAtPrague": "20. 11. 2026 22:59",
                   "checkedAtUtc": "2026-11-22T12:00:00Z", "delayed": True}
        harness = r'''
const vm=require('node:vm');let raw='';process.stdin.on('data',x=>raw+=x);
process.stdin.on('end',async()=>{
 const input=JSON.parse(raw),nodes={};
 function element(){return {textContent:'',className:'',children:[],childNodes:[],style:{},attrs:{},
 classList:{add(){}},append(...x){this.children.push(...x);this.childNodes.push(...x)},
 replaceChildren(...x){this.children=x;this.childNodes=x},addEventListener(){},
 querySelector(){return null},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]}}}
 class Clock extends Date {static now(){return Date.parse('2026-11-22T12:00:00Z')}}
 const context={console,URL,Date:Clock,Intl,Number,String,Math,Array,Set,Map,Promise,
 document:{hidden:true,getElementById:id=>nodes[id]??=element(),createElement:element,
 createTextNode:t=>({textContent:t}),createDocumentFragment:element,querySelector:()=>null,addEventListener(){}},
 window:{location:{href:'https://example.invalid/',replace(){}}},setInterval(){},fetch:()=>new Promise(()=>{})};
 vm.createContext(context);vm.runInContext(input.script,context);
 context.fetch=async url=>({ok:true,json:async()=>url.includes('futures-ath')?
 {symbol:'NQ=F',maxPrice:31616.5,benchmark:'historical'}:input.quote});
 await context.loadFutures();
 if(nodes['futures-price'].textContent==='—')throw Error('Weekend quote was hidden');
 if(!nodes['futures-time'].textContent.includes('20. 11. 2026 22:59'))throw Error('Original quote time lost');
 if(!nodes['futures-time'].textContent.includes('starší než 24 h'))throw Error('Stale quote not visibly labeled');
 if(!nodes['futures-time'].textContent.includes('Kontrola'))throw Error('Successful check time missing');
 if(nodes['futures-price'].attrs['data-freshness']!=='stale')throw Error('Stale metadata missing');
 input.quote.quotedAtUtc='2026-11-23T12:00:00Z';await context.loadFutures();
 if(nodes['futures-price'].textContent!=='—')throw Error('Future timestamp was accepted');
 console.log('PASS weekend last quote display and future timestamp rejection');
}).on('error',e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(["node", "-e", harness], input=json.dumps({"script": scripts, "quote": fixture}),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn("PASS weekend", result.stdout)


if __name__ == "__main__":
    unittest.main()

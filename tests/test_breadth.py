"""Regression tests for sourced Nasdaq-100 MA50 breadth (not a trade signal)."""
import json
import pathlib
import sys
import unittest
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import update_breadth as b

NOW=datetime(2026,11,21,8,tzinfo=timezone.utc)

class BreadthTest(unittest.TestCase):
    def test_no_external_github_data_sources(self):
        code=(ROOT/'scripts'/'update_breadth.py').read_text(encoding='utf-8')
        for domain in ('raw.githubusercontent.com', 'github.io', 'gist.github.com'):
            self.assertNotIn(domain,code)

    def test_stockcurry_named_columns_and_rounding(self):
        html = """<table><tr><th>Date</th><th>Total Stocks</th>
        <th>RSI_D &gt; 50</th><th>&gt; SMA50</th><th>&gt; SMA200</th></tr>
        <tr><td>2026-11-23</td><td>101</td><td>39.60%</td><td>43.56%</td><td>42.57%</td></tr>
        <tr><td>2026-11-20</td><td>101</td><td>37.62%</td><td>43.56%</td><td>41.58%</td></tr></table>"""
        now = datetime(2026,11,24,7,tzinfo=timezone.utc)
        d = b.stockcurry_snapshot(html, now)
        self.assertEqual(d["asOf"],"2026-11-23")
        self.assertEqual((d["aboveCount"], d["atOrBelowCount"]), (44,57))
        self.assertEqual((d["abovePct"], d["belowPct"]), (43.6,56.4))
        self.assertIsNone(d["sourceUpdatedAt"])
        self.assertTrue(d["sourceUrl"].startswith("https://stockcurry.com/"))
        with self.assertRaises(ValueError):
            b.stockcurry_snapshot(html.replace("&gt; SMA50","Unrelated"),now)
        with self.assertRaises(ValueError):
            b.stockcurry_snapshot(html.replace("43.56%","43.11%"),now)

    def test_stale_and_bad_coverage_rejected(self):
        html = """<table><tr><th>Date</th><th>Total Stocks</th><th>&gt; SMA50</th></tr>
        <tr><td>2026-11-23</td><td>101</td><td>43.56%</td></tr></table>"""
        with self.assertRaises(ValueError):
            b.stockcurry_snapshot(html, datetime(2026,12,2,12,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            b.stockcurry_snapshot(html.replace('101','50'), datetime(2026,11,24,7,tzinfo=timezone.utc))

    def test_published_baseline_matches_footnoted_source(self):
        out=json.loads((ROOT/"data/breadth.json").read_text(encoding="utf-8"))
        self.assertEqual(out["id"],"ndx-ma50-breadth")
        self.assertEqual(out["schemaVersion"],1)
        self.assertGreaterEqual(out["eligibleSecurities"],95)
        self.assertEqual(out["aboveCount"]+out["atOrBelowCount"],out["eligibleSecurities"])
        self.assertAlmostEqual(out["abovePct"]+out["belowPct"],100)
        self.assertIn("not point-in-time members",out["methodology"])

if __name__=="__main__":
    unittest.main()

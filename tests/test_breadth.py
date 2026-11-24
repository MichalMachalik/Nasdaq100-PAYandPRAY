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

def example(eligible=101, above=40, date="2026-11-19"):
    return {
        "updatedAt":"2026-11-20T04:01:24.203110+00:00",
        "cadence":"daily",
        "lines":[{"key":"above20"},{"key":"above50"},{"key":"above200"}],
        "series":[{"date":"2026-11-18","above50":42.574257,"eligible50":101},
                  {"date":date,"above50":100*above/eligible,"eligible50":eligible}],
    }

class BreadthTest(unittest.TestCase):
    def test_published_source_40_of_101_and_percentages_sum_to_100(self):
        x=b.make_snapshot(example(),NOW)
        self.assertEqual(x["asOf"],"2026-11-19")
        self.assertEqual(x["aboveCount"],40)
        self.assertEqual(x["atOrBelowCount"],61)
        self.assertEqual(x["eligibleSecurities"],101)
        self.assertEqual(x["abovePct"],39.6)
        self.assertEqual(x["belowPct"],60.4)
        self.assertAlmostEqual(x["abovePct"]+x["belowPct"],100)
        self.assertTrue(x["sourceDataUrl"].startswith("https://"))

    def test_source_is_order_independent_but_stale_is_rejected(self):
        x=example()
        x["series"].reverse()
        self.assertEqual(b.make_snapshot(x,NOW)["asOf"],"2026-11-19")
        with self.assertRaisesRegex(ValueError,"stale"):
            b.make_snapshot(x,datetime(2026,12,2,12,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            b.make_snapshot(x,datetime(2026,11,17,12,tzinfo=timezone.utc))

    def test_missing_and_wrong_source_rejected(self):
        for bad in ({"series":[]}, {"lines":[]}, {"cadence":"weekly"}, {"updatedAt":"unparsed"}):
            x=example()
            x.update(bad)
            with self.assertRaises((ValueError,TypeError)):
                b.make_snapshot(x,NOW)

    def test_bad_coverage_fraction_and_dates_rejected(self):
        for eligible,above in ((0,0),(50,25),(150,40)):
            with self.assertRaises(ValueError):
                b.make_snapshot(example(eligible=max(1,eligible),above=above),NOW)
        x=example()
        x["series"][-1]["above50"]=39.0
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            b.make_snapshot(x,NOW)
        x=example()
        x["series"].append(dict(x["series"][-1]))
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            b.make_snapshot(x,NOW)


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

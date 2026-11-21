"""Regression tests: RSI(14) is measured, not a buy/sell prediction."""
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import update_oversold as technical

class RsiTest(unittest.TestCase):
    def test_wilder_rsi_reference_extremes(self):
        self.assertEqual(technical.wilder_rsi(list(range(30)))[-1],100.0)
        self.assertEqual(technical.wilder_rsi(list(range(30,0,-1)))[-1],0.0)
        self.assertEqual(technical.wilder_rsi([100]*30)[-1],50.0)
        with self.assertRaises(ValueError):
            technical.wilder_rsi([100]*14)

    def test_alternating_changes_in_range(self):
        daily=[100+((i%2)*2) for i in range(70)]
        values=technical.wilder_rsi(daily)
        self.assertTrue(all(0 < v < 100 for v in values))
        self.assertGreater(len(values),50)

    def test_cash_index_only_and_fresh_completed_day(self):
        now=datetime(2026,11,21,9,tzinfo=timezone.utc)
        ny=ZoneInfo("America/New_York")
        start=datetime(2026,9,28,16,tzinfo=ny)
        timestamps=[int((start+timedelta(days=i)).timestamp()) for i in range(54)]
        prices=[26000-(i*19.0) for i in range(54)]
        def chart(symbol):
            return {"chart":{"result":[{"meta":{"symbol":symbol},"timestamp":timestamps,
                "indicators":{"quote":[{"close":prices}]}}]}}
        history=technical.parse_daily_closes(chart("^NDX"),now)
        snapshot=technical.build_snapshot(history)
        self.assertEqual(snapshot["asOf"],"2026-11-20")
        self.assertEqual(snapshot["instrument"],"^NDX")
        self.assertEqual(snapshot["value"],0)
        self.assertEqual(snapshot["rsiChangeFiveSessions"],0)
        self.assertLess(snapshot["ma20DistancePct"],0)
        with self.assertRaises(ValueError):
            technical.parse_daily_closes(chart("NQ=F"),now)
        with self.assertRaises(ValueError):
            technical.parse_daily_closes(chart("^NDX"),datetime(2026,12,20,12,tzinfo=timezone.utc))

    def test_unfinished_current_candle_excluded(self):
        ny=ZoneInfo("America/New_York")
        now=datetime(2026,11,20,15,0,tzinfo=ny)
        timestamps=[int(datetime(2026,9,26,16,tzinfo=ny).timestamp())+86400*i
                    for i in range(60)]
        prices=[25000+i for i in range(60)]
        data={"chart":{"result":[{"meta":{"symbol":"^NDX"},
            "timestamp":timestamps,"indicators":{"quote":[{"close":prices}]}}]}}
        series=technical.parse_daily_closes(data,now)
        self.assertLessEqual(series[-1][0],"2026-11-19")

    def test_lower_tail_percentiles_are_not_trade_probabilities(self):
        self.assertEqual(technical.inverted_percentile(1, [2,3,4,5]), 100)
        self.assertEqual(technical.inverted_percentile(9, [2,3,4,5]), 0)
        self.assertEqual(technical.inverted_percentile(3, [1,2,3,4]), 37.5)
        self.assertEqual(technical.inverted_percentile(5, [5,5,5,5]), 50)
        with self.assertRaises(ValueError):
            technical.inverted_percentile(0, [])

    def test_technical_intensity_uses_three_transparent_percentiles(self):
        # 320 sessions ensure 252 prior comparisons for all three measures.
        rising = [20000 + 25*i for i in range(320)]
        falling = [32000 - 25*i for i in range(320)]
        for closes in (rising, falling):
            result = technical.technical_extremity(closes, technical.wilder_rsi(closes))
            self.assertEqual(result["referenceSessions"], 252)
            self.assertTrue(0 <= result["score"] <= 100)
            self.assertEqual(set(result["percentiles"]),
                             {"rsi14", "priceToMA20", "return5Sessions"})
            expected = sum(result["percentiles"].values())/3
            self.assertAlmostEqual(result["score"], expected, delta=0.1)
        self.assertGreater(
            technical.technical_extremity(falling, technical.wilder_rsi(falling))["score"],
            technical.technical_extremity(rising, technical.wilder_rsi(rising))["score"],
        )
        short = [30000-i for i in range(60)]
        self.assertIsNone(technical.technical_extremity(short, technical.wilder_rsi(short)))

    def test_published_snapshot_has_source_and_a_date(self):
        d=json.loads((ROOT/"data/oversold.json").read_text(encoding="utf-8"))
        self.assertEqual(d["instrument"],"^NDX")
        self.assertEqual(d["indicator"],"RSI")
        self.assertEqual(d["period"],14)
        self.assertTrue(0<=d["value"]<=100)
        self.assertTrue(d["sourceUrl"].startswith("https://"))
        self.assertRegex(d["asOf"],r"^\d{4}-\d{2}-\d{2}$")

if __name__=="__main__":
    unittest.main()

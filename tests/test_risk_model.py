"""Offline regression tests for evidence-based NDX downside and dated source inputs."""
import json
import pathlib
import sys
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import update_risk_model as risk

class DownsideTest(unittest.TestCase):
    def test_vxn_quartile_is_monotonic_and_dated(self):
        one = risk.calculate_downside_pct(45.25, 1)
        three = risk.calculate_downside_pct(45.25, 3)
        self.assertAlmostEqual(one, 9.2114554973, places=5)
        self.assertAlmostEqual(three, 16.3223138506, places=5)
        self.assertLess(one, three)
        self.assertTrue(0 < one < 50)
        self.assertTrue(0 < three < 50)
        for volatility, months in ((0, 1), (120, 3), (45, 6)):
            with self.subTest(volatility=volatility, months=months), self.assertRaises(ValueError):
                risk.calculate_downside_pct(volatility, months)

    def test_only_timestamped_vxn_not_vix(self):
        now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        observed = int(datetime(2026, 11, 20, 15, tzinfo=timezone.utc).timestamp())
        def make(symbol, ticks, closes):
            return {"chart":{"result":[{"meta":{"symbol":symbol},
                    "timestamp":ticks,"indicators":{"quote":[{"close":closes}]}}]}}
        d, v = risk.parse_vxn(make("^VXN", [observed], [45.25]), now)
        self.assertEqual((d, v), ("2026-11-20", 45.25))
        with self.assertRaises(ValueError):
            risk.parse_vxn(make("^VIX", [observed], [45.25]), now)
        with self.assertRaises(ValueError):
            risk.parse_vxn(make("^VXN", [observed-10*86400], [45.25]), now)
        with self.assertRaises(ValueError):
            risk.parse_vxn(make("^VXN", [observed], [1.5]), now)

    def test_treasury_yields_not_news_timestamps(self):
        now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        csv = "Date,2-year,10-year,30-year\n11/19/2026,4.76,5.04,5.40\n11/20/2026,4.63,4.92,5.31\n"
        obs, values = risk.parse_treasury(csv, now)
        self.assertEqual(obs, "2026-11-20")
        self.assertEqual(values, [4.63, 4.92, 5.31])
        with self.assertRaises(ValueError):
            risk.parse_treasury("Date,2-year,10-year,30-year\n11/05/2026,1,2,3\n", now)

    def test_site_model_has_citations_and_no_hidden_sentiment_weight(self):
        model = json.loads((ROOT / "data/risk-model.json").read_text(encoding="utf-8"))
        self.assertEqual(model["schemaVersion"], 1)
        self.assertEqual(model["model"]["percentile"], 25)
        self.assertEqual(model["model"]["months"], [1, 3])
        self.assertGreater(model["market"]["vxnPct"], 8)
        self.assertTrue(model["market"]["vxnAsOf"])
        self.assertTrue(model["market"]["vxnSource"].startswith("https://"))
        self.assertEqual(len(model["earnings"]), 7)
        self.assertTrue(all(x.get("source", "").startswith("https://") for x in model["earnings"]))
        self.assertIn("NOT a forecast", model["model"]["numericScenarioIs"])

if __name__ == "__main__":
    unittest.main()

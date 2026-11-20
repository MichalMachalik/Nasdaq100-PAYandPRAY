"""Regression checks for provider outages and dated quote fallbacks."""
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import update_top10 as ranking


class QuoteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous = Path.cwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, previous)
        self.file = Path("data/futures.json")
        self.now = int(datetime.now(timezone.utc).timestamp()) - 60

    def update(self, *, market_time=None, timestamps=(), closes=(), price=26000, symbol="NQ=F"):
        meta = {"symbol": symbol, "regularMarketTime": market_time, "regularMarketPrice": price,
                "chartPreviousClose": 25000}
        result = {"meta": meta, "timestamp": timestamps, "indicators": {"quote": [{"close": closes}]}}
        response = io.BytesIO(json.dumps({"chart": {"result": [result]}}).encode())
        with patch("urllib.request.urlopen", return_value=response):
            runpy.run_path(str(SCRIPTS / "update_futures.py"))

    def test_timestamped_market_price_fills_missing_bars(self):
        self.update(market_time=self.now)
        row = json.loads(self.file.read_text())
        self.assertEqual((row["price"], row["changePercent"], row["quoteField"]), (26000, 4, "regularMarketPrice"))
        self.assertEqual(datetime.fromisoformat(row["quotedAtUtc"].replace("Z", "+00:00")).timestamp(), self.now)

    def test_invalid_or_older_metadata_preserves_last_quote(self):
        self.update(timestamps=[self.now], closes=[26100])
        before = self.file.read_bytes()
        for args in ({"market_time": self.now - 10}, {"price": 0, "market_time": self.now},
                     {"market_time": self.now - 90000}, {"market_time": self.now + 3600},
                     {"market_time": self.now, "symbol": "OTHER"}, {}):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.update(**args)
            self.assertEqual(self.file.read_bytes(), before)


class ConstituentsTests(unittest.TestCase):
    def test_only_recent_official_snapshot_can_substitute_for_unavailable_feed(self):
        now = datetime(2026, 4, 14, 16, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            members = Path(tmp) / "members.json"
            with patch.object(ranking, "MEMBERS_OUT", members), patch.object(ranking, "fetch", side_effect=URLError("offline")):
                for age, source, count, valid in [(7, ranking.MEMBERS_URL, 100, True),
                                                  (8, ranking.MEMBERS_URL, 100, False),
                                                  (1, "https://example.invalid/", 100, False),
                                                  (1, ranking.MEMBERS_URL, 3, False)]:
                    date = (now - timedelta(days=age)).date().isoformat()
                    record = {"sourceDate": date, "sourceUrl": source, "index": "NDX",
                              "symbols": [f"TEST{i}" for i in range(count)]}
                    members.write_text(json.dumps(record))
                    with self.subTest(age=age, source=source, count=count):
                        if valid:
                            symbols, actual, refreshed = ranking.current_members(now)
                            self.assertEqual((len(symbols), actual, refreshed), (count, date, False))
                        else:
                            with self.assertRaises(ValueError):
                                ranking.current_members(now)
                    self.assertEqual(json.loads(members.read_text()), record)

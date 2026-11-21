#!/usr/bin/env python3
"""Dated, reproducible daily RSI(14) for cash NASDAQ-100 ^NDX, not futures.

Data: unofficial Yahoo Finance daily index close candles. Calculations:
- Wilder RSI(14), seeded with a simple 14-session average then smoothed.
- 20-session simple moving average and % distance from it.
- 50-session simple moving average, % price deviation and 5-session MA50 slope.
  MA50 is a separate trend filter, NOT an extra term in the oversold score.
- RSI change across five trading sessions, NOT an oversold buy signal.

A source outage or stale price never overwrites the last verified observation.
"""
import json
import math
import pathlib
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

OUT = pathlib.Path("data/oversold.json")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?range=2y&interval=1d"
NY = ZoneInfo("America/New_York")

def fetch_history():
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PayAndPrayOversold/1.0)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def parse_daily_closes(chart, now):
    """Return ordered completed exchange-date daily closes, without partial today."""
    result = chart["chart"]["result"][0]
    symbol = result.get("meta", {}).get("symbol")
    if symbol != "^NDX":
        raise ValueError(f"Expected cash ^NDX, got {symbol!r}")
    timestamps = result.get("timestamp") or []
    quoted = result.get("indicators", {}).get("quote") or []
    closes = quoted[0].get("close") or [] if quoted else []
    by_day = {}
    now_ny = now.astimezone(NY)
    for ts, close in zip(timestamps, closes):
        if not isinstance(ts, (int, float)) or not isinstance(close, (int, float)):
            continue
        close = float(close)
        if not math.isfinite(close) or not 1000 < close < 100000:
            continue
        dt = datetime.fromtimestamp(int(ts), NY)
        if dt.date() > now_ny.date():
            continue
        if dt.date() == now_ny.date() and now_ny.hour < 16:
            continue
        by_day[dt.date().isoformat()] = close
    days = sorted(by_day)
    if len(days) < 55:
        raise ValueError("At least 55 completed NDX daily closes are required for MA50 trend")
    last_date = datetime.fromisoformat(days[-1]).date()
    days_old = (now_ny.date() - last_date).days
    if not 0 <= days_old <= 7:
        raise ValueError("Cash NDX daily quote is stale")
    return [(d, by_day[d]) for d in days]

def wilder_rsi(closes, period=14):
    if not isinstance(period, int) or period < 2 or len(closes) < period + 1:
        raise ValueError("Insufficient daily closes for Wilder RSI")
    deltas = [float(closes[i]) - float(closes[i-1]) for i in range(1, len(closes))]
    gain = sum(max(x, 0.0) for x in deltas[:period]) / period
    loss = sum(max(-x, 0.0) for x in deltas[:period]) / period
    def value(avg_gain, avg_loss):
        if avg_loss == 0 and avg_gain == 0:
            return 50.0
        if avg_loss == 0:
            return 100.0
        if avg_gain == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    series = [value(gain, loss)]
    for change in deltas[period:]:
        gain = (gain * (period-1) + max(change, 0.0)) / period
        loss = (loss * (period-1) + max(-change, 0.0)) / period
        series.append(value(gain, loss))
    return series

def inverted_percentile(current, previous):
    """Rank downside extremity against earlier observations, including half of ties.

    A return of 95 means the current measure is lower than approximately 95%
    of the historical sample. It does NOT mean 95% of a selloff is complete.
    """
    if not previous or not all(math.isfinite(x) for x in previous):
        raise ValueError("Empty or invalid comparison sample")
    if not math.isfinite(current):
        raise ValueError("Current observation is invalid")
    count = sum(x > current for x in previous)
    ties = sum(x == current for x in previous)
    return 100 * (count + 0.5 * ties) / len(previous)


def technical_extremity(closes, rsi_values, lookback=252):
    """Uncalibrated technical stretch: mean of three transparent percentiles.

    RSI(14), price deviation from MA20, and five-session return are correlated.
    Only bearish-side readings count; neutral and bullish readings contribute zero.
    This descriptive gauge NEVER claims to know the fraction of decline already
    completed, a turning-point probability, or future price direction.
    """
    n = len(closes)
    if len(rsi_values) != n - 14:
        raise ValueError("RSI alignment mismatch")
    if n < lookback + 20:
        return None
    rsi_by_day = [None] * 14 + rsi_values
    deviation_by_day = [None] * 19 + [
        (closes[i] / (sum(closes[i-19:i+1]) / 20) - 1) * 100
        for i in range(19, n)
    ]
    returns_by_day = [None] * 5 + [
        (closes[i] / closes[i-5] - 1) * 100 for i in range(5, n)
    ]
    start = n - lookback - 1
    end = n - 1  # exclude the current date from the reference distribution
    indicators = (rsi_by_day, deviation_by_day, returns_by_day)
    # Count only readings on the oversold side: a high RSI, positive
    # MA20 premium or positive five-day return cannot be 'oversold' even
    # if its historical rank is unusually low.
    is_downside = (rsi_by_day[-1] < 50,
                   deviation_by_day[-1] < 0,
                   returns_by_day[-1] < 0)
    ranks = [inverted_percentile(values[-1], values[start:end]) if weak else 0.0
             for values, weak in zip(indicators, is_downside)]
    return {
        "score": round(sum(ranks) / len(ranks), 1),
        "percentiles": {
            "rsi14": round(ranks[0], 1),
            "priceToMA20": round(ranks[1], 1),
            "return5Sessions": round(ranks[2], 1),
        },
        "referenceSessions": lookback,
        "return5SessionsPct": round(returns_by_day[-1], 2),
        "method": "Unweighted mean of three lower-tail ranks vs prior 252 sessions",
    }


def build_snapshot(history):
    values = [x[1] for x in history]
    if len(values) < 55:
        raise ValueError("At least 55 completed sessions are required for MA50 slope")
    rsi = wilder_rsi(values)
    if len(rsi) < 6:
        raise ValueError("Need at least six RSI observations to assess change")
    ma20 = sum(values[-20:]) / 20
    ma50 = sum(values[-50:]) / 50
    previous_ma50 = sum(values[-55:-5]) / 50
    ma50_change5 = 100 * (ma50 / previous_ma50 - 1)
    now_rsi = rsi[-1]
    five_day_change = now_rsi - rsi[-6]
    three_day_change = now_rsi - rsi[-4]
    if three_day_change >= 3 and values[-1] > values[-2]:
        momentum = "easing"
    elif three_day_change <= -3:
        momentum = "worsening"
    else:
        momentum = "unconfirmed"
    severity = technical_extremity(values, rsi)
    return {
        "schemaVersion": 1, "instrument": "^NDX", "instrumentType": "INDEX",
        "indicator": "RSI", "period": 14,
        "value": round(now_rsi, 2), "asOf": history[-1][0],
        "ndxClose": round(values[-1], 2),
        "ma20": round(ma20, 2),
        "ma20DistancePct": round(100*(values[-1]/ma20 - 1), 2),
        "ma50": round(ma50, 2),
        "ma50DistancePct": round(100*(values[-1]/ma50 - 1), 2),
        "ma50Change5SessionsPct": round(ma50_change5, 2),
        "ma50TrendRole": "separate_midterm_trend_filter_not_in_oversold_score",
        "rsiChangeFiveSessions": round(five_day_change, 2),
        "trendConfirmation": momentum,
        "technicalOversold": severity,
        "source": "Yahoo Finance cash ^NDX daily closes; Wilder RSI(14) calculated",
        "sourceUrl": "https://finance.yahoo.com/quote/%5ENDX/history/",
        "methodology": ("Cash NDX daily Wilder RSI(14): below 20 extremely oversold, "
                        "20–30 oversold. This indicates past selling pressure, "
                        "not a reversal guarantee, forecast or instruction to trade. "
                        "technicalOversold.score (0–100) is the average lower-tail "
                        "percentile for RSI14, MA20 gap, and 5d return over 252 "
                        "earlier sessions; not a percentage of decline completed. "
                        "MA50 level, NDX distance and 5-session MA50 slope are "
                        "an independent medium-term trend context, not scored twice."),
        "isProviderSnapshot": False,
    }

def main():
    now = datetime.now(timezone.utc)
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    snapshot = build_snapshot(parse_daily_closes(fetch_history(), now))
    if previous.get("asOf", "") > snapshot["asOf"]:
        raise ValueError("New history predates published RSI snapshot")
    snapshot["collectedAtUtc"] = now.isoformat().replace("+00:00", "Z")
    # Avoid rewriting an unchanged completed trading day every weekend.
    if (previous.get("asOf") == snapshot["asOf"] and
        previous.get("value") == snapshot["value"] and
        previous.get("ma20") == snapshot["ma20"] and
        previous.get("ma50") == snapshot["ma50"] and
        previous.get("ma50Change5SessionsPct") == snapshot["ma50Change5SessionsPct"] and
        previous.get("source") == snapshot["source"] and
        previous.get("technicalOversold") == snapshot["technicalOversold"]):
        print("RSI unchanged; retained dated snapshot", snapshot["asOf"])
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False)+"\n",
                   encoding="utf-8")
    print("Published NDX RSI(14)",snapshot["value"],"as of",snapshot["asOf"],
          "5d RSI change",snapshot["rsiChangeFiveSessions"])

if __name__ == "__main__":
    main()

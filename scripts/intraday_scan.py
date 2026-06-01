#!/usr/bin/env python3
"""
Intraday breakout scanner.
Uses FMP /v3/quote (free tier) to check real-time price + volume conditions.
Outputs JSON: {"alerts": [...], "scanned": N, "timestamp": "..."}

Usage:
  python3 intraday_scan.py TICKER1 TICKER2 ...
  python3 intraday_scan.py --screen   # auto-screen top candidates
"""
import sys, os, json, requests
from datetime import datetime

API_KEY = os.environ.get("FMP_API_KEY", "")
BASE = "https://financialmodelingprep.com/api/v3"


def fetch(path):
    sep = "&" if "?" in path else "?"
    url = f"{BASE}/{path}{sep}apikey={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def get_quotes(tickers):
    if not tickers:
        return []
    joined = ",".join(tickers)
    result = fetch(f"quote/{joined}")
    return result if isinstance(result, list) else []


def market_hours_progress():
    """Returns fraction of trading day elapsed (0.0 to 1.0). ET timezone."""
    now_utc = datetime.utcnow()
    # ET is UTC-4 (EDT summer) / UTC-5 (EST winter)
    # Use UTC-4 as approximation for market season
    et_hour = now_utc.hour - 4
    et_minute = now_utc.minute
    et_total_minutes = et_hour * 60 + et_minute

    market_open = 9 * 60 + 30   # 9:30 ET
    market_close = 16 * 60       # 16:00 ET
    total_minutes = market_close - market_open  # 390 minutes

    if et_total_minutes <= market_open:
        return 0.0
    if et_total_minutes >= market_close:
        return 1.0
    return (et_total_minutes - market_open) / total_minutes


def check_breakout(q):
    """
    Returns alert dict if breakout conditions met, else None.
    Conditions:
      - changesPercentage >= 2.0%  (strong intraday move)
      - volume pace >= 1.5x avg    (volume confirmation)
      - price within 5% below or above yearHigh (near/at breakout zone)
    """
    ticker = q.get("symbol", "")
    price = q.get("price") or 0
    pct_change = q.get("changesPercentage") or 0
    volume = q.get("volume") or 0
    avg_volume = q.get("avgVolume") or 1
    year_high = q.get("yearHigh") or price
    name = q.get("name", ticker)

    if price <= 0 or avg_volume <= 0:
        return None

    # Annualize current volume to full day
    progress = market_hours_progress()
    if progress < 0.05:
        return None
    projected_volume = volume / progress if progress > 0 else volume
    volume_ratio = projected_volume / avg_volume

    # Distance from 52-week high
    pct_from_high = (price - year_high) / year_high * 100 if year_high > 0 else -99

    # Breakout zone: within 5% below high OR above high (new high)
    near_high = pct_from_high >= -5.0

    if pct_change >= 2.0 and volume_ratio >= 1.5 and near_high:
        signal_type = "突破新高" if pct_from_high >= 0 else f"接近突破（距高点{abs(pct_from_high):.1f}%）"
        return {
            "ticker": ticker,
            "name": name,
            "price": round(price, 2),
            "change_pct": round(pct_change, 1),
            "volume_ratio": round(volume_ratio, 2),
            "pct_from_high": round(pct_from_high, 1),
            "signal": signal_type,
            "strength": "强" if (pct_change >= 4.0 and volume_ratio >= 2.0) else "中",
        }
    return None


def quick_screen():
    """Pull a broad set of high-momentum tickers via FMP screener."""
    result = fetch(
        "stock-screener?marketCapMoreThan=500000000"
        "&revenueMoreThan=50000000"
        "&volumeMoreThan=200000"
        "&country=US"
        "&exchange=NYSE,NASDAQ"
        "&limit=50"
    )
    if not isinstance(result, list):
        return []
    return [r["symbol"] for r in result if r.get("symbol")]


def scan(tickers):
    quotes = get_quotes(tickers)
    alerts = []
    for q in quotes:
        alert = check_breakout(q)
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda a: (a["volume_ratio"] * abs(a["change_pct"])), reverse=True)
    return alerts


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("tickers", nargs="*")
    p.add_argument("--screen", action="store_true", help="Auto-screen candidates")
    args = p.parse_args()

    tickers = args.tickers
    if args.screen or not tickers:
        screened = quick_screen()
        tickers = list(set(tickers + screened))

    alerts = scan(tickers)
    result = {
        "alerts": alerts,
        "alert_count": len(alerts),
        "scanned": len(tickers),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "market_progress_pct": round(market_hours_progress() * 100, 1),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

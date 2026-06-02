#!/usr/bin/env python3
"""
Intraday breakout scanner using yfinance (no API key, cloud-compatible).
Triggers when: today's gain ≥ 2% + projected volume ≥ 1.5x avg + within 5% of 52w high.
Usage: python3 intraday_scan.py [TICKER1 TICKER2 ...] [--screen]
"""
import sys, json
from datetime import datetime

GROWTH_UNIVERSE = [
    'NVDA','AMD','AVGO','ARM','SMCI','MRVL','CRDO',
    'NOW','WDAY','CRM','SNOW','MDB','DDOG','NET','ZS','PANW','CRWD',
    'HUBS','SHOP','TTD','OKTA','BILL','GTLB','MNDY','DUOL','APP','VEEV',
    'META','GOOGL','AMZN','MSFT','AAPL','TSLA','PLTR','RBLX','UBER',
    'RXRX','TMDX','RKLB','ACHR','SQ','AFRM','SOFI',
]


def market_hours_progress():
    now_utc  = datetime.utcnow()
    et_min   = (now_utc.hour - 4) * 60 + now_utc.minute  # EDT (UTC-4)
    open_min, close_min = 9 * 60 + 30, 16 * 60
    if et_min <= open_min:  return 0.0
    if et_min >= close_min: return 1.0
    return (et_min - open_min) / (close_min - open_min)


def scan(tickers):
    import yfinance as yf

    progress = market_hours_progress()
    if progress < 0.05:
        return []

    try:
        data = yf.download(
            ' '.join(tickers),
            period='3mo',
            interval='1d',
            group_by='ticker',
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception:
        return []

    alerts = []
    for ticker in tickers:
        try:
            df = data[ticker] if len(tickers) > 1 else data
            df = df.dropna(subset=['Close', 'Volume'])
            if len(df) < 30:
                continue

            price      = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            pct_change = (price - prev_close) / prev_close * 100
            today_vol  = float(df['Volume'].iloc[-1])
            avg_vol    = float(df['Volume'].iloc[-31:-1].mean())
            year_high  = float(df['High'].max())

            projected_vol = today_vol / progress if progress > 0 else today_vol
            vol_ratio     = projected_vol / avg_vol if avg_vol > 0 else 0
            pct_from_high = (price - year_high) / year_high * 100

            if pct_change >= 2.0 and vol_ratio >= 1.5 and pct_from_high >= -5.0:
                alerts.append({
                    'ticker':       ticker,
                    'name':         ticker,
                    'price':        round(price, 2),
                    'change_pct':   round(pct_change, 1),
                    'volume_ratio': round(vol_ratio, 2),
                    'pct_from_high': round(pct_from_high, 1),
                    'signal':       '突破新高' if pct_from_high >= 0 else f'接近突破（距高点{abs(pct_from_high):.1f}%）',
                    'strength':     '强' if (pct_change >= 4.0 and vol_ratio >= 2.0) else '中',
                })
        except Exception:
            continue

    alerts.sort(key=lambda a: a['volume_ratio'] * abs(a['change_pct']), reverse=True)
    return alerts


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('tickers', nargs='*')
    p.add_argument('--screen', action='store_true')
    args = p.parse_args()

    tickers = list(set(args.tickers + GROWTH_UNIVERSE)) if (args.screen or not args.tickers) else args.tickers

    alerts = scan(tickers)
    result = {
        'alerts':               alerts,
        'alert_count':          len(alerts),
        'scanned':              len(tickers),
        'timestamp':            datetime.utcnow().isoformat() + 'Z',
        'market_progress_pct':  round(market_hours_progress() * 100, 1),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

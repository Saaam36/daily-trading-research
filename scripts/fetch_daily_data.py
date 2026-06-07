#!/usr/bin/env python3
"""
Pre-fetch fundamental + technical data for all universe stocks.
Runs on GitHub Actions (has internet access); saves JSON files to data/stocks/.
CCR reads these files instead of calling APIs directly.
Usage: python3 fetch_daily_data.py
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path

UNIVERSE = [
    'NVDA','AMD','AVGO','ARM','SMCI','MRVL','CRDO',
    'NOW','WDAY','CRM','SNOW','MDB','DDOG','NET','ZS','PANW','CRWD',
    'HUBS','SHOP','TTD','OKTA','BILL','GTLB','MNDY','DUOL','APP','VEEV',
    'META','GOOGL','AMZN','MSFT','AAPL','TSLA','PLTR','RBLX','UBER',
    'RXRX','TMDX','RKLB','ACHR','SQ','AFRM','SOFI',
]

OUT_DIR = Path(__file__).parent.parent / 'data' / 'stocks'
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
import fundamental_snapshot
import deep_technical


def fetch_all():
    results = {'timestamp': datetime.utcnow().isoformat() + 'Z', 'tickers': {}, 'errors': {}}

    for i, ticker in enumerate(UNIVERSE):
        print(f"[{i+1}/{len(UNIVERSE)}] {ticker}", flush=True)
        try:
            fund = fundamental_snapshot.analyze(ticker)
            with open(OUT_DIR / f'{ticker}_fund.json', 'w') as f:
                json.dump(fund, f)
        except Exception as e:
            results['errors'][f'{ticker}_fund'] = str(e)
            print(f"  fund error: {e}", flush=True)

        try:
            tech = deep_technical.analyze(ticker)
            with open(OUT_DIR / f'{ticker}_tech.json', 'w') as f:
                json.dump(tech, f)
        except Exception as e:
            results['errors'][f'{ticker}_tech'] = str(e)
            print(f"  tech error: {e}", flush=True)

        results['tickers'][ticker] = 'ok'
        time.sleep(0.5)

    # Also run screener and save
    try:
        import yf_screener
        screener_result = yf_screener.screen(max_candidates=20)
        with open(OUT_DIR.parent / 'screener.json', 'w') as f:
            json.dump(screener_result, f)
        print("Screener saved.", flush=True)
    except Exception as e:
        results['errors']['screener'] = str(e)
        print(f"Screener error: {e}", flush=True)

    # Fetch data for Serenity watchlist tickers not already in UNIVERSE
    try:
        import serenity_scan
        serenity_extras = [t for t in serenity_scan.SERENITY_UNIVERSE if t not in UNIVERSE]
        for ticker in serenity_extras:
            print(f"[Serenity extra] {ticker}", flush=True)
            try:
                fund = fundamental_snapshot.analyze(ticker)
                with open(OUT_DIR / f'{ticker}_fund.json', 'w') as f:
                    json.dump(fund, f)
            except Exception as e:
                results['errors'][f'{ticker}_fund'] = str(e)
            try:
                tech = deep_technical.analyze(ticker)
                with open(OUT_DIR / f'{ticker}_tech.json', 'w') as f:
                    json.dump(tech, f)
            except Exception as e:
                results['errors'][f'{ticker}_tech'] = str(e)
            time.sleep(0.5)
        # Run Serenity scan and save
        serenity_result = serenity_scan.scan()
        print(f"Serenity scan saved ({len(serenity_result['results'])} stocks).", flush=True)
    except Exception as e:
        results['errors']['serenity'] = str(e)
        print(f"Serenity scan error: {e}", flush=True)

    results['fetched'] = len([v for v in results['tickers'].values() if v == 'ok'])
    results['error_count'] = len(results['errors'])

    with open(OUT_DIR.parent / 'fetch_status.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nDone: {results['fetched']} tickers, {results['error_count']} errors", flush=True)
    return results


if __name__ == '__main__':
    fetch_all()

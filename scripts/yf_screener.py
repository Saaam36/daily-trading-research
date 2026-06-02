#!/usr/bin/env python3
"""
Growth stock screener using yfinance (no API key, cloud-compatible).
Scans a predefined universe of growth/momentum stocks and scores on CANSLIM criteria.
Usage: python3 yf_screener.py [--max-candidates N]
Output: JSON list of top candidates with scores
"""
import sys, json, time
from datetime import datetime

UNIVERSE = [
    # AI / Semiconductors
    'NVDA','AMD','AVGO','ARM','SMCI','AEHR','MRVL','CRDO',
    # Cloud / SaaS
    'NOW','WDAY','CRM','SNOW','MDB','DDOG','NET','ZS','PANW','CRWD',
    'HUBS','SHOP','TTD','OKTA','BILL','GTLB','MNDY','DUOL','APP',
    'VEEV','RCM','ASAN','PATH','AI','SMAR',
    # Platforms / Consumer Tech
    'META','GOOGL','AMZN','MSFT','AAPL','TSLA','PLTR','RBLX','UBER',
    # Biotech / Healthcare
    'RXRX','TMDX','INSP','AXSM','IRTC',
    # Defense / Space
    'RKLB','LUNR','ACHR','JOBY',
    # Fintech / Other Growth
    'SQ','AFRM','SOFI','HOOD',
]

def sma(series, n):
    if len(series) < n:
        return None
    return sum(series[:n]) / n


def score_candidate(ticker, info, closes, volumes):
    score = 0
    details = {}

    # C: Current quarterly earnings growth (earningsGrowth proxy)
    eps_g = info.get('earningsGrowth') or info.get('earningsQuarterlyGrowth') or 0
    details['eps_growth_pct'] = round(float(eps_g) * 100, 1)
    if eps_g > 0.25: score += 25
    elif eps_g > 0.10: score += 12

    # A: Annual earnings growth (revenueGrowth as proxy)
    rev_g = info.get('revenueGrowth') or 0
    details['rev_growth_pct'] = round(float(rev_g) * 100, 1)
    if rev_g > 0.25: score += 20
    elif rev_g > 0.10: score += 10

    # N: New highs / near 52w high
    if closes:
        price   = closes[0]
        high52  = max(closes)
        pct_fh  = (price - high52) / high52 * 100
        details['pct_from_52w_high'] = round(pct_fh, 1)
        details['price'] = round(price, 2)
        if pct_fh >= -5:  score += 20
        elif pct_fh >= -15: score += 10

        # Stage 2 check (simplified: price above 50MA and 200MA)
        ma50  = sma(closes, 50)
        ma200 = sma(closes, 200)
        if ma50 and ma200 and price > ma50 and price > ma200 and ma50 > ma200:
            score += 15
            details['stage2'] = True
        else:
            details['stage2'] = False

    # S: Supply/demand — volume contraction (proxy for accumulation)
    if len(volumes) >= 30:
        avg_base   = sum(volumes[5:30]) / 25
        avg_recent = sum(volumes[:5]) / 5
        vol_ratio  = avg_recent / max(avg_base, 1)
        details['vol_ratio'] = round(vol_ratio, 2)
        if vol_ratio < 0.8: score += 10

    # L: Leader — high gross margin
    gm = info.get('grossMargins') or 0
    details['gross_margin_pct'] = round(float(gm) * 100, 1)
    if gm > 0.60: score += 10
    elif gm > 0.40: score += 5

    details['canslim_score'] = score
    return score, details


def screen(max_candidates=20):
    import yfinance as yf

    candidates = []

    # Batch download price history for all tickers at once
    try:
        raw = yf.download(
            ' '.join(UNIVERSE),
            period='1y',
            interval='1d',
            group_by='ticker',
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as e:
        return {'error': str(e), 'candidates': []}

    # Fetch info one-by-one (needed for fundamentals)
    for ticker in UNIVERSE:
        try:
            # Get price data
            df = raw[ticker] if len(UNIVERSE) > 1 else raw
            df = df.dropna(subset=['Close'])
            if len(df) < 50:
                continue
            closes  = list(reversed(df['Close'].tolist()))
            volumes = list(reversed(df['Volume'].tolist()))

            # Get fundamentals
            info = yf.Ticker(ticker).info
            if not info or info.get('quoteType') not in ('EQUITY', 'ETF', None):
                continue

            score, details = score_candidate(ticker, info, closes, volumes)

            if score >= 40:
                candidates.append({
                    'ticker':    ticker,
                    'name':      info.get('longName', ticker),
                    'sector':    info.get('sector', ''),
                    **details,
                })

            time.sleep(0.1)
        except Exception:
            continue

    candidates.sort(key=lambda x: x['canslim_score'], reverse=True)
    top = candidates[:max_candidates]

    return {
        'timestamp':  datetime.now().isoformat(),
        'scanned':    len(UNIVERSE),
        'qualified':  len(candidates),
        'candidates': top,
    }


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--max-candidates', type=int, default=20)
    args = p.parse_args()
    result = screen(args.max_candidates)
    print(json.dumps(result, ensure_ascii=False, indent=2))

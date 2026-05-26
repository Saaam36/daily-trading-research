#!/usr/bin/env python3
"""
Deep technical analysis for a single stock using FMP API.
Checks Minervini Trend Template, base quality, RS vs SPY, volume pattern.
Usage: python3 deep_technical.py TICKER
Output: JSON with technical metrics + score + conclusion
"""
import sys, os, json, requests
from datetime import datetime

API_KEY = os.environ.get('FMP_API_KEY', '')
BASE = 'https://financialmodelingprep.com/api/v3'

def fetch_history(ticker, days=252):
    url = f"{BASE}/historical-price-full/{ticker}?timeseries={days}&apikey={API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get('historical', [])
    except Exception:
        pass
    return []

def sma(series, n):
    if len(series) < n:
        return None
    return sum(series[:n]) / n

def analyze(ticker):
    history     = fetch_history(ticker, 252)
    spy_history = fetch_history('SPY', 252)

    if not history:
        return {'ticker': ticker, 'error': 'No price data available'}

    closes  = [d['close']  for d in history]
    volumes = [d['volume'] for d in history]
    result  = {'ticker': ticker, 'timestamp': datetime.now().isoformat(), 'price': closes[0]}

    # 52-week range
    result['52w_high'] = max(closes[:252]) if len(closes) >= 252 else max(closes)
    result['52w_low']  = min(closes[:252]) if len(closes) >= 252 else min(closes)

    # Moving averages
    for n, label in [(21,'ma21'),(50,'ma50'),(150,'ma150'),(200,'ma200')]:
        v = sma(closes, n)
        result[label] = round(v, 2) if v else None

    price  = closes[0]
    ma50   = result['ma50']
    ma150  = result['ma150']
    ma200  = result['ma200']

    # Minervini Trend Template (7 criteria)
    tt = {}
    if ma150 and ma200:
        tt['price_above_150_200ma'] = price > ma150 and price > ma200
        tt['ma150_above_ma200']     = ma150 > ma200
    if ma200 and len(closes) >= 221:
        ma200_month_ago = sma(closes[21:], 200)
        tt['ma200_trending_up'] = ma200 > ma200_month_ago if ma200_month_ago else False
    if ma50 and ma150 and ma200:
        tt['ma50_above_ma150_200'] = ma50 > ma150 and ma50 > ma200
    if ma50:
        tt['price_above_ma50'] = price > ma50
    low52, high52 = result['52w_low'], result['52w_high']
    tt['price_25pct_above_52w_low']      = price >= low52 * 1.25 if low52 else False
    tt['price_within_25pct_of_52w_high'] = price >= high52 * 0.75 if high52 else False

    result['trend_template']       = tt
    result['trend_template_score'] = sum(tt.values())
    result['stage2_confirmed']     = result['trend_template_score'] >= 6

    # Distance from 52w high (proxy for pivot proximity)
    result['pct_from_52w_high'] = round((price - high52) / high52 * 100, 1) if high52 else None

    # Volume pattern: base (days 6-30) vs recent (days 1-5)
    if len(volumes) >= 30:
        avg_base   = sum(volumes[5:30]) / 25
        avg_recent = sum(volumes[:5])   / 5
        result['vol_base_avg']     = int(avg_base)
        result['vol_recent_avg']   = int(avg_recent)
        result['vol_contraction']  = avg_recent < avg_base
        result['vol_ratio']        = round(avg_recent / max(avg_base, 1), 2)

    # Base tightness: max drawdown over last 30 days
    if len(closes) >= 30:
        base_window = closes[:30]
        base_peak   = max(base_window)
        base_trough = min(base_window)
        result['base_depth_pct'] = round((base_peak - base_trough) / base_peak * 100, 1)
        result['base_tight']     = result['base_depth_pct'] < 15

    # Relative strength vs SPY
    if spy_history:
        spy_closes = [d['close'] for d in spy_history]
        for label, days_back in [('rs_1m', 21), ('rs_3m', 63), ('rs_6m', 126)]:
            if len(closes) > days_back and len(spy_closes) > days_back:
                sr  = (closes[0] - closes[days_back]) / closes[days_back]
                spr = (spy_closes[0] - spy_closes[days_back]) / spy_closes[days_back]
                result[label] = round((sr - spr) * 100, 1)

    # Score
    score, positives, warnings = 0, [], []

    tt_score = result.get('trend_template_score', 0)
    if result.get('stage2_confirmed'):
        score += 30; positives.append(f"Minervini趋势模板 {tt_score}/7 全部达标")
    elif tt_score >= 5:
        score += 18; positives.append(f"趋势模板 {tt_score}/7（接近达标）")
    else:
        warnings.append(f"趋势模板仅 {tt_score}/7（Stage 2 未确认）")

    if result.get('vol_contraction'):
        score += 15; positives.append(f"整理期成交量收缩（近期/均值={result.get('vol_ratio')}x）")
    else:
        warnings.append("成交量未收缩（整理质量存疑）")

    if result.get('base_tight'):
        score += 15; positives.append(f"底部整理紧密（最大回撤 {result.get('base_depth_pct')}%）")
    else:
        bd = result.get('base_depth_pct')
        if bd: warnings.append(f"底部较宽松（回撤 {bd}%）")

    pfh = result.get('pct_from_52w_high', -999)
    if pfh is not None:
        if pfh >= -5:
            score += 20; positives.append(f"距52周高点仅 {abs(pfh)}%（突破前夕）")
        elif pfh >= -10:
            score += 10; positives.append(f"距52周高点 {abs(pfh)}%（接近）")
        else:
            warnings.append(f"距52周高点 {abs(pfh)}%（偏远）")

    rs3m = result.get('rs_3m')
    if rs3m is not None:
        if rs3m > 15:
            score += 15; positives.append(f"3个月RS超跑标普 +{rs3m}%（领涨）")
        elif rs3m > 5:
            score += 8;  positives.append(f"3个月RS超跑标普 +{rs3m}%")
        elif rs3m < -10:
            warnings.append(f"3个月RS跑输标普 {rs3m}%（相对弱势）")

    rs1m = result.get('rs_1m')
    if rs1m and rs1m > 10:
        score += 5; positives.append(f"近一个月RS强势 +{rs1m}%")

    result['technical_score']     = score
    result['technical_grade']     = '突破候选' if score >= 70 else ('需等待' if score >= 45 else '回避')
    result['technical_positives'] = positives
    result['technical_warnings']  = warnings

    return result

if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'
    print(json.dumps(analyze(ticker), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""
Fundamental snapshot using yfinance (no API key, cloud-compatible).
Usage: python3 fundamental_snapshot.py TICKER
"""
import sys, json, os
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / 'data' / 'stocks'
CACHE_MAX_AGE_HOURS = 20


def _load_cache(ticker):
    path = CACHE_DIR / f'{ticker}_fund.json'
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_hours = (datetime.now(tz=timezone.utc) - mtime).total_seconds() / 3600
    if age_hours > CACHE_MAX_AGE_HOURS:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def analyze(ticker):
    cached = _load_cache(ticker)
    if cached:
        return cached

    import yfinance as yf

    stock = yf.Ticker(ticker)
    info  = stock.info
    result = {'ticker': ticker, 'timestamp': datetime.now().isoformat()}

    # Revenue growth
    rev_growth = info.get('revenueGrowth')
    if rev_growth is not None:
        result['revenue_yoy_pct'] = round(float(rev_growth) * 100, 1)
    else:
        try:
            q = getattr(stock, 'quarterly_income_stmt', None) or stock.quarterly_financials
            for key in ('Total Revenue', 'Revenue'):
                if key in q.index and q.shape[1] >= 5:
                    r_now = float(q.loc[key].iloc[0])
                    r_ago = float(q.loc[key].iloc[4])
                    if abs(r_ago) > 0:
                        result['revenue_yoy_pct'] = round((r_now - r_ago) / abs(r_ago) * 100, 1)
                    break
        except Exception:
            pass

    # EPS growth
    eps_growth = info.get('earningsGrowth')
    if eps_growth is not None:
        result['eps_yoy_pct'] = round(float(eps_growth) * 100, 1)

    # EPS trend from quarterly data
    try:
        q = getattr(stock, 'quarterly_income_stmt', None) or stock.quarterly_financials
        for key in ('Basic EPS', 'Diluted EPS', 'EPS'):
            if key in q.index:
                vals = q.loc[key].dropna()
                if len(vals) >= 3:
                    v = [float(vals.iloc[i]) for i in range(min(5, len(vals)))]
                    result['eps_latest'] = round(v[0], 2)
                    result['eps_trend']  = 'accelerating' if v[0] > v[1] > v[2] else 'mixed'
                    if result.get('eps_yoy_pct') is None and len(v) >= 5 and v[4] != 0:
                        result['eps_yoy_pct'] = round((v[0] - v[4]) / abs(v[4]) * 100, 1)
                break
    except Exception:
        result.setdefault('eps_trend', 'mixed')

    # Margins
    result['gross_margin_pct'] = round((info.get('grossMargins') or 0) * 100, 1)
    result['net_margin_pct']   = round((info.get('profitMargins') or 0) * 100, 1)

    # Balance sheet
    de_raw = float(info.get('debtToEquity') or 0)
    result['debt_to_equity']    = round(de_raw / 100, 2) if de_raw > 5 else round(de_raw, 2)
    total_cash = info.get('totalCash') or 0
    total_debt = info.get('totalDebt') or 0
    result['cash_usd_m']        = round(total_cash / 1e6, 1)
    result['net_cash_positive'] = total_cash > total_debt

    # Free cash flow
    fcf = info.get('freeCashflow') or 0
    ni  = info.get('netIncomeToCommon') or 1
    result['fcf_usd_m']       = round(fcf / 1e6, 1)
    result['fcf_to_ni_ratio'] = round(fcf / max(abs(ni), 1), 2)

    # Valuation & ROE
    ps  = info.get('priceToSalesTrailing12Months')
    pe  = info.get('trailingPE')
    roe = info.get('returnOnEquity') or 0
    result['ps_ratio'] = round(float(ps), 1) if ps else None
    result['pe_ratio'] = round(float(pe), 1) if pe else None
    result['roe_pct']  = round(float(roe) * 100, 1)

    # Score
    score, positives, warnings = 0, [], []

    rev_yoy = result.get('revenue_yoy_pct') or 0
    if rev_yoy > 25:   score += 25; positives.append(f"营收同比 +{rev_yoy}%（强劲）")
    elif rev_yoy > 10: score += 12; positives.append(f"营收同比 +{rev_yoy}%")
    else: warnings.append(f"营收增速偏低 {rev_yoy}%")

    eps_yoy = result.get('eps_yoy_pct') or 0
    if eps_yoy > 25:   score += 25; positives.append(f"EPS同比 +{eps_yoy}%（强劲）")
    elif eps_yoy > 10: score += 12; positives.append(f"EPS同比 +{eps_yoy}%")
    else: warnings.append(f"EPS增速偏低 {eps_yoy}%")

    if result.get('eps_trend') == 'accelerating':
        score += 15; positives.append("EPS连续三季加速")

    nm = result.get('net_margin_pct') or 0
    if nm > 15:   score += 10; positives.append(f"净利率 {nm}%（优秀）")
    elif nm > 5:  score += 5
    else: warnings.append(f"净利率仅 {nm}%")

    if result.get('net_cash_positive'):
        score += 10; positives.append("净现金（无债务压力）")
    else:
        de = result.get('debt_to_equity') or 0
        if de > 2: warnings.append(f"负债率偏高 D/E={de}")

    fcf_ratio = result.get('fcf_to_ni_ratio') or 0
    if fcf_ratio > 0.8:  score += 10; positives.append(f"自由现金流质量高 FCF/NI={fcf_ratio}")
    elif fcf_ratio < 0:  warnings.append("自由现金流为负")

    roe_v = result.get('roe_pct') or 0
    if roe_v > 20: score += 5; positives.append(f"ROE {roe_v}%")

    result['fundamental_score']     = score
    result['fundamental_grade']     = '强' if score >= 65 else ('中' if score >= 40 else '弱')
    result['fundamental_positives'] = positives
    result['fundamental_warnings']  = warnings

    return result


if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'
    print(json.dumps(analyze(ticker), ensure_ascii=False, indent=2))

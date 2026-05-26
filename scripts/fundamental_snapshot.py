#!/usr/bin/env python3
"""
Fundamental snapshot for a single stock using FMP API.
Usage: python3 fundamental_snapshot.py TICKER
Output: JSON with key metrics + score + conclusion
"""
import sys, os, json, requests
from datetime import datetime

API_KEY = os.environ.get('FMP_API_KEY', '')
BASE = 'https://financialmodelingprep.com/api/v3'

def fetch(path):
    sep = '&' if '?' in path else '?'
    url = f"{BASE}/{path}{sep}apikey={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def analyze(ticker):
    income_q  = fetch(f"income-statement/{ticker}?period=quarter&limit=8")
    balance_q = fetch(f"balance-sheet-statement/{ticker}?period=quarter&limit=4")
    cashflow_q= fetch(f"cash-flow-statement/{ticker}?period=quarter&limit=4")
    metrics_a = fetch(f"key-metrics/{ticker}?period=annual&limit=1")

    result = {'ticker': ticker, 'timestamp': datetime.now().isoformat()}

    # Revenue & EPS growth
    if len(income_q) >= 5:
        rev_now      = income_q[0].get('revenue', 0) or 0
        rev_year_ago = income_q[4].get('revenue', 0) or 0
        eps_series   = [q.get('eps', 0) or 0 for q in income_q]

        result['revenue_yoy_pct'] = round((rev_now - rev_year_ago) / max(abs(rev_year_ago), 1) * 100, 1)
        result['eps_latest']      = eps_series[0]
        result['eps_yoy_pct']     = round((eps_series[0] - eps_series[4]) / max(abs(eps_series[4]), 0.01) * 100, 1) if eps_series[4] != 0 else None
        result['eps_trend']       = 'accelerating' if eps_series[0] > eps_series[1] > eps_series[2] else 'mixed'
        result['gross_margin_pct']= round((income_q[0].get('grossProfitRatio') or 0) * 100, 1)
        result['net_margin_pct']  = round((income_q[0].get('netIncomeRatio')   or 0) * 100, 1)

    # Balance sheet
    if balance_q:
        total_debt = balance_q[0].get('totalDebt', 0) or 0
        cash       = balance_q[0].get('cashAndCashEquivalents', 0) or 0
        equity     = balance_q[0].get('totalStockholdersEquity', 1) or 1
        result['debt_to_equity']   = round(total_debt / max(equity, 1), 2)
        result['cash_usd_m']       = round(cash / 1e6, 1)
        result['net_cash_positive']= cash > total_debt

    # Free cash flow
    if cashflow_q and income_q:
        fcf = cashflow_q[0].get('freeCashFlow', 0) or 0
        ni  = income_q[0].get('netIncome', 1) or 1
        result['fcf_usd_m']        = round(fcf / 1e6, 1)
        result['fcf_to_ni_ratio']  = round(fcf / max(abs(ni), 1), 2)

    # Valuation & ROE
    if metrics_a:
        result['ps_ratio'] = metrics_a[0].get('priceToSalesRatio')
        result['pe_ratio'] = metrics_a[0].get('peRatio')
        result['roe_pct']  = round((metrics_a[0].get('roe') or 0) * 100, 1)

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

    roe = result.get('roe_pct') or 0
    if roe > 20: score += 5; positives.append(f"ROE {roe}%")

    result['fundamental_score']  = score
    result['fundamental_grade']  = '强' if score >= 65 else ('中' if score >= 40 else '弱')
    result['fundamental_positives'] = positives
    result['fundamental_warnings']  = warnings

    return result

if __name__ == '__main__':
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'NVDA'
    print(json.dumps(analyze(ticker), ensure_ascii=False, indent=2))

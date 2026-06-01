#!/usr/bin/env python3
"""
Investor Perspectives — Path A integration of AI Hedge Fund logic.
Fetches supplementary data (profile, insider trades, news, R&D) via FMP
and scores 4 investor personas + risk assessment.

Usage:
  python3 investor_perspectives.py TICKER [--fundamental path.json] [--technical path.json]
Output:
  JSON with per-persona signal / confidence / score_breakdown / key_points
"""
import sys, os, json, requests, re
from datetime import datetime, timedelta

API_KEY = os.environ.get("FMP_API_KEY", "")
BASE = "https://financialmodelingprep.com/api/v3"


def fetch(path):
    sep = "&" if "?" in path else "?"
    url = f"{BASE}/{path}{sep}apikey={API_KEY}"
    try:
        r = requests.get(url, timeout=12)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def fetch_list(path):
    result = fetch(path)
    return result if isinstance(result, list) else []


# ── helpers ──────────────────────────────────────────────────────────────────

def safe(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d if d is not None else default


def clamp(v, lo=0, hi=10):
    return max(lo, min(hi, v))


# ── data fetchers ─────────────────────────────────────────────────────────────

def get_profile(ticker):
    data = fetch_list(f"profile/{ticker}")
    return data[0] if data else {}


def get_insider_trades(ticker, days=90):
    since = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    trades = fetch_list(f"insider-trading?symbol={ticker}&limit=50")
    recent = [t for t in trades if t.get("transactionDate", "") >= since]
    bought = sum(t.get("securitiesTransacted", 0) for t in recent
                 if t.get("transactionType", "").upper() in ("P-PURCHASE", "BUY"))
    sold   = sum(t.get("securitiesTransacted", 0) for t in recent
                 if t.get("transactionType", "").upper() in ("S-SALE", "SELL"))
    return {"bought_shares": bought, "sold_shares": sold,
            "net_buying": bought - sold, "trade_count": len(recent)}


def get_news_sentiment(ticker, limit=20):
    articles = fetch_list(f"stock_news?tickers={ticker}&limit={limit}")
    if not articles:
        return {"score": 5, "bullish_count": 0, "bearish_count": 0, "total": 0}
    bull_words = {"beat", "surge", "rally", "growth", "record", "upgrade",
                  "bullish", "profit", "revenue", "strong", "positive", "gain"}
    bear_words = {"miss", "decline", "fall", "cut", "downgrade", "loss",
                  "bearish", "weak", "disappoint", "risk", "concern", "drop"}
    bull, bear = 0, 0
    for a in articles:
        text = (a.get("title", "") + " " + a.get("text", "")).lower()
        words = set(re.findall(r"\b\w+\b", text))
        bull += len(words & bull_words)
        bear += len(words & bear_words)
    total = bull + bear or 1
    score = clamp(5 + (bull - bear) / total * 5)
    return {"score": round(score, 1), "bullish_count": bull,
            "bearish_count": bear, "total": len(articles)}


def get_rd_ratio(ticker):
    income = fetch_list(f"income-statement/{ticker}?period=annual&limit=3")
    if not income:
        return None
    rd  = income[0].get("researchAndDevelopmentExpenses", 0) or 0
    rev = income[0].get("revenue", 1) or 1
    return round(rd / rev * 100, 1) if rev > 0 else None


def get_margin_trend(ticker):
    income = fetch_list(f"income-statement/{ticker}?period=annual&limit=3")
    if len(income) < 2:
        return "unknown"
    margins = [(i.get("grossProfitRatio") or 0) for i in income[:3]]
    if margins[0] > margins[1]:
        return "expanding"
    elif margins[0] < margins[1]:
        return "contracting"
    return "stable"


# ── scoring engines ───────────────────────────────────────────────────────────

def score_druckenmiller(fund, tech, news, insider):
    score = 0.0
    points, warnings = [], []

    # Growth & Momentum (35% = 3.5 pts)
    rev = fund.get("revenue_yoy_pct") or 0
    eps = fund.get("eps_yoy_pct") or 0
    rs3 = tech.get("rs_3m") or 0
    if rev > 30:   score += 2.0; points.append(f"营收同比+{rev}%（强劲动量）")
    elif rev > 15: score += 1.3; points.append(f"营收同比+{rev}%")
    elif rev > 0:  score += 0.7
    else:          warnings.append(f"营收增速负增长{rev}%")
    if fund.get("eps_trend") == "accelerating":
        score += 0.8; points.append("EPS加速增长")
    if rs3 > 15: score += 0.7; points.append(f"3M RS超跑标普+{rs3}%")
    elif rs3 > 5: score += 0.4

    # Risk-Reward (20% = 2.0 pts)
    pfh = tech.get("pct_from_52w_high") or -50
    if pfh >= -5:  score += 1.2; points.append(f"距52周高点{abs(pfh)}%（接近突破）")
    elif pfh >= -15: score += 0.8
    else: warnings.append(f"距高点{abs(pfh)}%（偏离较大）")
    if tech.get("stage2_confirmed"): score += 0.8; points.append("Stage 2趋势确认")
    else: score += 0.2

    # Valuation (20% = 2.0 pts)
    ps = fund.get("ps_ratio") or 99
    pe = fund.get("pe_ratio") or 99
    if rev > 20:  # growth company — use PS
        if ps < 8:   score += 2.0; points.append(f"P/S={ps}x（成长股中低估）")
        elif ps < 15: score += 1.3; points.append(f"P/S={ps}x（合理）")
        elif ps < 25: score += 0.7
        else: warnings.append(f"P/S={ps}x（估值偏贵）")
    else:
        if pe and pe < 20:  score += 2.0
        elif pe and pe < 30: score += 1.3
        else: score += 0.5

    # Sentiment (15% = 1.5 pts)
    nscore = news.get("score", 5)
    if nscore >= 7:   score += 1.5; points.append("新闻情绪积极")
    elif nscore >= 5: score += 0.8
    else: warnings.append("新闻情绪偏负面")

    # Insider (10% = 1.0 pt)
    net = insider.get("net_buying", 0)
    if net > 0:   score += 1.0; points.append("内部人净买入")
    elif net == 0: score += 0.5
    else: warnings.append("内部人净卖出")

    score = clamp(score)
    signal = "bullish" if score >= 7.0 else ("bearish" if score <= 4.0 else "neutral")
    confidence = int(min(95, max(30, score / 10 * 100)))
    return {"signal": signal, "confidence": confidence,
            "score": round(score, 1), "key_points": points, "warnings": warnings}


def score_cathie_wood(fund, tech, profile, rd_ratio):
    score = 0.0
    points, warnings = [], []

    disruption_sectors = {"technology", "healthcare", "communication services",
                          "consumer discretionary", "financials"}
    sector = (profile.get("sector") or "").lower()
    industry = (profile.get("industry") or "").lower()
    disruptive_keywords = {"software", "semiconductor", "biotech", "genomic",
                           "artificial intelligence", "cloud", "fintech",
                           "electric", "renewable", "platform", "saas", "ai"}

    is_disruption = (sector in disruption_sectors or
                     any(k in industry for k in disruptive_keywords))
    if is_disruption:
        score += 2.5; points.append(f"颠覆性赛道（{profile.get('sector','未知')}）")
    else:
        warnings.append("非颠覆性核心赛道")

    # Revenue growth — Cathie likes >30%
    rev = fund.get("revenue_yoy_pct") or 0
    if rev > 40:   score += 2.5; points.append(f"营收高速增长+{rev}%（ARK风格）")
    elif rev > 25: score += 1.8; points.append(f"营收增长+{rev}%")
    elif rev > 15: score += 1.0
    else: warnings.append(f"增速{rev}%低于Cathie标准（需>25%）")

    # Gross margin — software/platform has high margins
    gm = fund.get("gross_margin_pct") or 0
    if gm > 65:   score += 2.0; points.append(f"毛利率{gm}%（平台型商业模式）")
    elif gm > 45: score += 1.3; points.append(f"毛利率{gm}%")
    elif gm > 30: score += 0.7
    else: warnings.append(f"毛利率{gm}%偏低（Cathie偏好轻资产）")

    # R&D investment
    if rd_ratio is not None:
        if rd_ratio > 15:  score += 2.0; points.append(f"研发投入{rd_ratio}%（创新驱动）")
        elif rd_ratio > 8: score += 1.3; points.append(f"研发投入{rd_ratio}%")
        elif rd_ratio > 3: score += 0.7
    else:
        score += 0.5

    # Momentum — Cathie holds through volatility but likes momentum entry
    rs3 = tech.get("rs_3m") or 0
    if rs3 > 10: score += 1.0; points.append(f"近期强势超跑标普+{rs3}%")

    score = clamp(score)
    signal = "bullish" if score >= 6.5 else ("bearish" if score <= 3.5 else "neutral")
    confidence = int(min(90, max(30, score / 10 * 100)))
    return {"signal": signal, "confidence": confidence,
            "score": round(score, 1), "key_points": points, "warnings": warnings}


def score_peter_lynch(fund, tech, insider):
    score = 0.0
    points, warnings = [], []

    # PEG ratio (most important)
    pe  = fund.get("pe_ratio") or 0
    eps = fund.get("eps_yoy_pct") or 0
    if pe > 0 and eps > 0:
        peg = pe / eps
        if peg < 0.5:   score += 4.0; points.append(f"PEG={round(peg,2)}（极度低估）")
        elif peg < 1.0: score += 3.0; points.append(f"PEG={round(peg,2)}（低估）")
        elif peg < 1.5: score += 2.0; points.append(f"PEG={round(peg,2)}（合理）")
        elif peg < 2.0: score += 1.0
        else: warnings.append(f"PEG={round(peg,2)}（偏高，林奇偏好<1.5）")
    else:
        score += 1.0
        warnings.append("PEG无法计算（PE或EPS增速为负）")

    # Revenue consistency
    rev = fund.get("revenue_yoy_pct") or 0
    if rev > 20:   score += 2.0; points.append(f"营收增长+{rev}%（十倍股特征）")
    elif rev > 10: score += 1.3
    elif rev > 0:  score += 0.7
    else: warnings.append("营收负增长，林奇回避")

    # Debt — Lynch hates leverage
    de = fund.get("debt_to_equity") or 0
    nc = fund.get("net_cash_positive", False)
    if nc:         score += 1.5; points.append("净现金状态（林奇偏爱无债公司）")
    elif de < 0.5: score += 1.0; points.append(f"低负债D/E={de}")
    elif de > 2.0: score -= 0.5; warnings.append(f"高负债D/E={de}（林奇警示）")

    # Insider buying
    net = insider.get("net_buying", 0)
    if net > 0: score += 1.0; points.append("高管买入（林奇重视内部信号）")
    elif net < 0: warnings.append("高管减持")

    # Business clarity — proxy via margin
    nm = fund.get("net_margin_pct") or 0
    if nm > 10: score += 0.5; points.append(f"净利率{nm}%（盈利清晰）")

    score = clamp(score)
    signal = "bullish" if score >= 6.5 else ("bearish" if score <= 3.5 else "neutral")
    confidence = int(min(90, max(30, score / 10 * 100)))
    return {"signal": signal, "confidence": confidence,
            "score": round(score, 1), "key_points": points, "warnings": warnings}


def score_phil_fisher(fund, rd_ratio, margin_trend, insider):
    score = 0.0
    points, warnings = [], []

    # R&D intensity (Fisher loves companies that invest in future)
    if rd_ratio is not None:
        if rd_ratio > 15:   score += 2.5; points.append(f"研发占收入{rd_ratio}%（费雪标准：创新护城河）")
        elif rd_ratio > 8:  score += 1.8; points.append(f"研发占收入{rd_ratio}%")
        elif rd_ratio > 3:  score += 1.0
        else: warnings.append(f"研发投入{rd_ratio}%偏低（费雪重视R&D）")
    else:
        score += 0.8

    # Margin trend (Fisher: quality companies expand margins)
    if margin_trend == "expanding":
        score += 2.0; points.append("毛利率持续扩张（管理层执行力强）")
    elif margin_trend == "stable":
        score += 1.0; points.append("毛利率稳定")
    else:
        warnings.append("毛利率收缩（费雪警示）")

    # FCF quality (Fisher: free cash is evidence of real earnings)
    fcf_ratio = fund.get("fcf_to_ni_ratio") or 0
    if fcf_ratio > 1.0:   score += 2.0; points.append(f"FCF/净利={fcf_ratio}（盈利质量极高）")
    elif fcf_ratio > 0.7: score += 1.5; points.append(f"FCF/净利={fcf_ratio}（盈利质量好）")
    elif fcf_ratio > 0:   score += 0.8
    else: warnings.append("自由现金流为负（费雪警示）")

    # ROE (management efficiency)
    roe = fund.get("roe_pct") or 0
    if roe > 25:   score += 2.0; points.append(f"ROE={roe}%（卓越资本效率）")
    elif roe > 15: score += 1.3; points.append(f"ROE={roe}%（优秀）")
    elif roe > 10: score += 0.7
    else: warnings.append(f"ROE={roe}%偏低（费雪要求资本高效）")

    # Insider signal (secondary)
    net = insider.get("net_buying", 0)
    if net > 0: score += 0.5; points.append("管理层增持（费雪：利益一致）")

    # Revenue growth consistency
    rev = fund.get("revenue_yoy_pct") or 0
    if rev > 20: score += 1.0; points.append(f"营收增长+{rev}%（长期成长可信）")
    elif rev > 10: score += 0.5

    score = clamp(score)
    signal = "bullish" if score >= 6.5 else ("bearish" if score <= 3.5 else "neutral")
    confidence = int(min(90, max(30, score / 10 * 100)))
    return {"signal": signal, "confidence": confidence,
            "score": round(score, 1), "key_points": points, "warnings": warnings}


def score_risk(fund, tech, profile):
    beta = float(profile.get("beta") or 1.0)
    de   = fund.get("debt_to_equity") or 0
    nc   = fund.get("net_cash_positive", False)
    pfh  = tech.get("pct_from_52w_high") or -50
    bd   = tech.get("base_depth_pct") or 30

    risk_points = []
    risk_score = 0  # higher = more risk

    if beta > 1.5:   risk_score += 2; risk_points.append(f"Beta={beta}（高波动）")
    elif beta > 1.2: risk_score += 1; risk_points.append(f"Beta={beta}（中等波动）")

    if de > 2.0:     risk_score += 2; risk_points.append(f"负债率D/E={de}（高杠杆）")
    elif de > 1.0:   risk_score += 1

    if not nc and de > 1: risk_score += 1; risk_points.append("无净现金保护")

    if pfh < -20:    risk_score += 1; risk_points.append(f"距高点{abs(pfh)}%（回撤较深）")
    if bd > 20:      risk_score += 1; risk_points.append(f"底部宽松{bd}%（整理质量差）")

    if risk_score >= 4:   level = "高"
    elif risk_score >= 2: level = "中"
    else:                 level = "低"

    max_position = {"高": 5, "中": 8, "低": 12}[level]
    return {"risk_level": level, "risk_score": risk_score,
            "max_position_pct": max_position, "risk_factors": risk_points}


# ── consensus ─────────────────────────────────────────────────────────────────

def consensus(personas):
    signals = [p["signal"] for p in personas.values()]
    bull = signals.count("bullish")
    bear = signals.count("bearish")
    total = len(signals)
    if bull >= total * 0.75:   verdict = "强力看多"
    elif bull >= total * 0.5:  verdict = "看多"
    elif bear >= total * 0.5:  verdict = "看空"
    elif bear >= total * 0.75: verdict = "强力看空"
    else:                       verdict = "分歧中性"
    avg_conf = int(sum(p["confidence"] for p in personas.values()) / total)
    return {"verdict": verdict, "bullish": bull, "bearish": bear,
            "neutral": total - bull - bear, "total": total,
            "avg_confidence": avg_conf}


# ── main ──────────────────────────────────────────────────────────────────────

def analyze(ticker, fund_path=None, tech_path=None):
    fund, tech = {}, {}
    if fund_path:
        with open(fund_path) as f: fund = json.load(f)
    if tech_path:
        with open(tech_path) as f: tech = json.load(f)

    profile   = get_profile(ticker)
    insider   = get_insider_trades(ticker)
    news      = get_news_sentiment(ticker)
    rd_ratio  = get_rd_ratio(ticker)
    margin_tr = get_margin_trend(ticker)

    personas = {
        "druckenmiller": score_druckenmiller(fund, tech, news, insider),
        "cathie_wood":   score_cathie_wood(fund, tech, profile, rd_ratio),
        "peter_lynch":   score_peter_lynch(fund, tech, insider),
        "phil_fisher":   score_phil_fisher(fund, rd_ratio, margin_tr, insider),
    }
    risk = score_risk(fund, tech, profile)
    con  = consensus(personas)

    return {
        "ticker":    ticker,
        "timestamp": datetime.now().isoformat(),
        "company":   profile.get("companyName", ticker),
        "sector":    profile.get("sector", ""),
        "industry":  profile.get("industry", ""),
        "rd_ratio":  rd_ratio,
        "margin_trend": margin_tr,
        "insider":   insider,
        "news_sentiment": news,
        "personas":  personas,
        "risk":      risk,
        "consensus": con,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("--fundamental", default=None)
    p.add_argument("--technical",   default=None)
    args = p.parse_args()
    result = analyze(args.ticker, args.fundamental, args.technical)
    print(json.dumps(result, ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""
Serenity 卡点雷达 — supply-chain chokepoint scanner.
Combines manually-annotated chokepoint scores with cached fundamental/technical data.
Output: ranked list of stocks where chokepoint strength + technical setup both signal opportunity.
Usage: python3 serenity_scan.py
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
CACHE_DIR = DATA_DIR / 'stocks'
OUT_FILE  = DATA_DIR / 'serenity_scan.json'

# Pre-curated watchlist: manually assessed chokepoint quality + thesis
# chokepoint_score: 1-5 (how strong/unpriced the supply chain bottleneck is)
# red_flags: known disqualifiers (don't auto-filter, just surface them)
SERENITY_UNIVERSE = {
    # AI Optical / CPO
    'CRDO': {
        'theme': 'AI Networking',
        'thesis': 'SerDes/connectivity chips for AI switches; 认证壁垒高、多客户design-win',
        'chokepoint_score': 4,
        'red_flags': ['已re-rate至高估值'],
    },
    'SIVE': {
        'theme': 'AI Optical / CPO',
        'thesis': 'CW激光源卡点 for Co-Packaged Optics; 单点失效、认证周期长',
        'chokepoint_score': 4,
        'red_flags': ['已re-rate', 'Q1营收-22%', '内部人近高位清仓', '烧钱'],
    },
    'MTSI': {
        'theme': 'AI Compound Semi',
        'thesis': 'GaN/GaAs/InP化合物半导体; AI光驱动+电力管理双用途',
        'chokepoint_score': 3,
        'red_flags': [],
    },
    'MRVL': {
        'theme': 'AI Networking / Custom Silicon',
        'thesis': 'ASIC定制芯片+PCIe switch; 多超大云厂design-win',
        'chokepoint_score': 3,
        'red_flags': ['大市值($60B+)', '已被充分发现'],
    },
    # SpaceX supply chain
    'CRS': {
        'theme': 'SpaceX Supply Chain',
        'thesis': '碳纤维复合材料结构件; 认证+唯一供应商地位、SpaceX放量即受益',
        'chokepoint_score': 4,
        'red_flags': [],
    },
    'HXL': {
        'theme': 'SpaceX Supply Chain',
        'thesis': '航空航天复合材料; Falcon 9/Starship结构材料供应商',
        'chokepoint_score': 3,
        'red_flags': ['大市值($4B+)', '非纯标的'],
    },
    'LUNR': {
        'theme': 'SpaceX Ecosystem',
        'thesis': '月球着陆器; SpaceX客户(Falcon 9发射), NASA合同背书',
        'chokepoint_score': 2,
        'red_flags': ['零营收', '纯期权期票', '高投机性'],
    },
    # AI semiconductor tools/testing
    'AEHR': {
        'theme': 'SiC Wafer Testing',
        'thesis': 'Wafer级老化测试; SiC功率芯片唯一量产测试方案',
        'chokepoint_score': 3,
        'red_flags': ['客户高度集中', 'EV周期依赖'],
    },
    # AI infrastructure
    'SMCI': {
        'theme': 'AI Server',
        'thesis': 'GPU服务器整合; 液冷技术领先、直接受益AI capex',
        'chokepoint_score': 2,
        'red_flags': ['财务重述风险', '已大幅波动', '非上游卡点'],
    },
    'ARM': {
        'theme': 'CPU IP',
        'thesis': 'AI芯片IP授权; 收费站模式、几乎所有AI芯片都用ARM架构',
        'chokepoint_score': 3,
        'red_flags': ['大市值($130B+)', '估值极高'],
    },
}


def _load_fund(ticker):
    p = CACHE_DIR / f'{ticker}_fund.json'
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_tech(ticker):
    p = CACHE_DIR / f'{ticker}_tech.json'
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_screener():
    p = DATA_DIR / 'screener.json'
    if not p.exists():
        return set()
    try:
        with open(p) as f:
            data = json.load(f)
        return {c['ticker'] for c in data.get('candidates', [])}
    except Exception:
        return set()


def score_stock(ticker, meta, fund, tech, canslim_tickers):
    score = 0
    signals = []
    warnings = list(meta['red_flags'])

    # --- Serenity chokepoint layer (static, manually assessed) ---
    cp = meta['chokepoint_score']
    score += cp * 8  # max 40 pts
    if cp >= 4:
        signals.append(f'卡点强度 {cp}/5 (强)')
    elif cp >= 3:
        signals.append(f'卡点强度 {cp}/5 (中)')
    else:
        signals.append(f'卡点强度 {cp}/5 (弱)')

    # --- Market cap: smaller = more unpriced upside ---
    mkt_cap = fund.get('market_cap') or fund.get('marketCap') or 0
    if mkt_cap and mkt_cap < 2e9:
        score += 20
        signals.append(f'市值 ${mkt_cap/1e9:.1f}B (Sub-$2B 卡点甜区)')
    elif mkt_cap and mkt_cap < 5e9:
        score += 10
        signals.append(f'市值 ${mkt_cap/1e9:.1f}B (小盘)')
    elif mkt_cap and mkt_cap < 15e9:
        score += 3
        signals.append(f'市值 ${mkt_cap/1e9:.1f}B (中盘)')
    elif mkt_cap:
        warnings.append(f'大市值 ${mkt_cap/1e9:.0f}B (框架判断力弱)')

    # --- Revenue growth: demand pull signal ---
    rev_g = fund.get('revenue_growth') or fund.get('revenueGrowth') or 0
    if rev_g > 0.5:
        score += 15
        signals.append(f'营收增长 {rev_g*100:.0f}% (强需求拉动)')
    elif rev_g > 0.25:
        score += 8
        signals.append(f'营收增长 {rev_g*100:.0f}%')
    elif rev_g < 0:
        score -= 5
        warnings.append(f'营收下滑 {rev_g*100:.0f}%')

    # --- Gross margin: pricing power ---
    gm = fund.get('gross_margins') or fund.get('grossMargins') or 0
    if gm > 0.6:
        score += 10
        signals.append(f'毛利率 {gm*100:.0f}% (高定价权)')
    elif gm > 0.4:
        score += 5
        signals.append(f'毛利率 {gm*100:.0f}%')

    # --- Technical readiness (Minervini stage 2 + volume) ---
    if tech.get('stage2_confirmed'):
        score += 15
        signals.append('Stage 2 确认 (Minervini趋势模板 ≥6/7)')
    elif tech.get('trend_template_score', 0) >= 5:
        score += 8
        signals.append(f'趋势模板 {tech.get("trend_template_score")}/7 (接近Stage 2)')
    else:
        tt = tech.get('trend_template_score', 0)
        if tt is not None:
            warnings.append(f'趋势模板 {tt}/7 (技术未就绪)')

    if tech.get('vol_contraction'):
        score += 10
        signals.append(f'成交量收缩 (vol_ratio={tech.get("vol_ratio")}x, 待突破)')

    pfh = tech.get('pct_from_52w_high')
    if pfh is not None:
        if pfh >= -5:
            score += 10
            signals.append(f'距52周高点 {abs(pfh):.1f}% (突破前夕)')
        elif pfh >= -15:
            score += 5
            signals.append(f'距52周高点 {abs(pfh):.1f}%')
        elif pfh < -40:
            warnings.append(f'距52周高点 {abs(pfh):.1f}% (深度回调)')

    # --- CANSLIM cross-confirmation ---
    if ticker in canslim_tickers:
        score += 15
        signals.append('CANSLIM 双重确认 ✓ (同时命中成长股筛选器)')

    # --- Grade ---
    if score >= 90:
        grade = '🔥 卡点+技术双就绪'
    elif score >= 70:
        grade = '✅ 值得深挖'
    elif score >= 50:
        grade = '⏳ 等待催化剂'
    else:
        grade = '👀 观察名单'

    return {
        'ticker': ticker,
        'theme': meta['theme'],
        'thesis': meta['thesis'],
        'chokepoint_score': cp,
        'total_score': score,
        'grade': grade,
        'signals': signals,
        'warnings': warnings,
        'price': tech.get('price'),
        'market_cap_b': round(mkt_cap / 1e9, 2) if mkt_cap else None,
        'stage2': tech.get('stage2_confirmed'),
        'pct_from_52w_high': pfh,
        'canslim_confirmed': ticker in canslim_tickers,
    }


def scan():
    canslim_tickers = _load_screener()
    results = []

    for ticker, meta in SERENITY_UNIVERSE.items():
        fund = _load_fund(ticker)
        tech = _load_tech(ticker)
        result = score_stock(ticker, meta, fund, tech, canslim_tickers)
        results.append(result)

    results.sort(key=lambda x: x['total_score'], reverse=True)

    output = {
        'timestamp': datetime.now(tz=timezone.utc).isoformat(),
        'universe_count': len(SERENITY_UNIVERSE),
        'results': results,
    }

    with open(OUT_FILE, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output


if __name__ == '__main__':
    out = scan()
    for r in out['results']:
        flags = '  ⚠️ ' + ' | '.join(r['warnings']) if r['warnings'] else ''
        print(f"{r['grade']}  {r['ticker']:6s} [{r['theme']}]  score={r['total_score']}{flags}")

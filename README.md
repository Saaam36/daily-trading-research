# Daily Trading Research Agent

A systematic growth-stock research agent for a ~45-name US growth/momentum
universe, built as a set of Claude Code skills plus supporting Python
scripts. Covers screening, technical and fundamental analysis, multi-persona
scoring, and risk-based position sizing.

## Pipeline

A GitHub Actions workflow fetches fundamental and technical data for the full
universe after each US market close (`yfinance`, no API key required) and
commits it to `data/`. A daily routine then reads the cache and runs the
skills below to produce a Chinese-language HTML report, delivered by email.

## Skills (`.claude/skills/`)

| Skill | What it scores |
|---|---|
| `vcp-screener` | Minervini Volatility Contraction Pattern setups |
| `canslim-screener` | O'Neil CANSLIM growth criteria (FMP data) |
| `breakout-trade-planner` | Entry/stop/target levels from VCP output, with position sizing |
| `position-sizer` | Risk-based share count from account size + stop distance |
| `market-breadth-analyzer`, `uptrend-analyzer` | Market-wide participation and breadth health |
| `exposure-coach` | Net exposure recommendation from breadth + regime signals |
| `theme-detector` | Sector and thematic rotation across the universe |
| `technical-analyst` | Weekly chart reads: trend, support/resistance, scenarios |

`scripts/investor_perspectives.py` adds a separate layer: four investor-persona
scores (signal, confidence, key points) computed from FMP fundamentals,
insider trades, and news.

## Testing

45 unit test files across the skills' `scripts/tests/` directories.

## Config

`config.json` sets account size and risk-per-trade; `FMP_API_KEY` is required
for the CANSLIM and VCP data sources.

## Stack

Python, yfinance, FMP API, GitHub Actions, Claude Code skills architecture.

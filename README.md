# StockAI — Self-Evolving Algorithmic Trading Agent

A production-grade, multi-agent trading system for the Indian Stock Market (NSE/BSE). SEBI 2026 compliant architecture. Built with Rust (execution), Go (orchestration), and Python (cognition + LLM).

```
        ┌──────────────────────────────────────────┐
        │              ORCHESTRATOR (Go)            │
        │   Redis pub/sub · Telegram 2FA · Relay    │
        └──────┬──────────────────────────┬─────────┘
               │                          │
    ┌──────────▼──────────┐    ┌─────────▼──────────┐
    │   ENGINE (Rust)      │    │  MEMORY (Python)   │
    │   <1ms latency       │    │  DeepSeek LLM      │
    │   Market feed (WS)   │    │  LanceDB (vectors) │
    │   2FA gate + rate lim │    │  YFinance (data)   │
    │   Redis persist pos   │    │  Dashboard + UI    │
    └──────────────────────┘    └────────────────────┘
```

## Quick Install

**Local (macOS, Linux):**
```bash
curl -sSL https://raw.githubusercontent.com/UmairBaig8/StockAI/main/install.sh | bash
```

**AWS EC2 (one command):**
```bash
aws login
MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh
```
Creates t2.small, security group, deploys via user-data. Prints dashboard URL.

See [aws_env.md](aws_env.md) for deployment status + commands. See [production_ready.md](production_ready.md) for going live (broker keys only).

## Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| **Cockpit** | `/` | Real-time trading dashboard — equity curve, positions, watchlist, signals, AI recommendations |
| **Report** | `/report` | Daily performance analytics — 5 tabs: Daily, Tickers, Timing, Strategies, Weekly |
| **History** | `/history` | Persistent trade history from PostgreSQL — filter by ticker, export CSV |
| **Research** | `/research` | LLM research: fundamental/sentiment analysis per ticker |
| **News** | `/news` | Live NSE news feed scraped from Moneycontrol/Economic Times |
| **Backtest** | `/backtest` | Strategy backtesting engine |
| **Settings** | `/settings` | All strategy params hot-reloadable — LLM provider, RSI thresholds, position sizing |
| **LLM** | `/llm` | LLM provider health + call traces — real-time token usage, latency per agent |

## How It Works

### Auto-Trading Strategy

| Feature | Detail |
|---------|--------|
| **Market hours** | 09:15–15:30 IST, Mon–Fri aware |
| **Auto-discovery** | LLM scans trending NSE tickers at 09:00 IST + hourly |
| **Signal engine** | Multi-timeframe RSI (1m/5m/15m) + MACD + Bollinger Bands every 15s |
| **Volume filter** | Z-score > 1.0 on price range — avoids low-momentum traps |
| **Min hold time** | 300s minimum before BB overbought exit (stops oscillator loops) |
| **Price delta guard** | Requires ≥0.1% price movement before BB exit |
| **Short selling** | Opt-in via `short_enabled` config (BB overbought + volume confirmed) |
| **Position rotation** | Sells weakest holding when full, rotates into best opportunity |
| **Quality filters** | Skips dead stocks (activity <0.3%), skips overbought (RSI > 70) |
| **Configurable** | All params editable live at `/settings` UI |

### Risk Controls (Production Hardening)

| Control | Detail |
|---------|--------|
| **Daily loss limit** | 2% of capital — auto-halts trading if breached |
| **Consecutive loss cooldown** | 3 consecutive losses → 10-minute pause |
| **Stop-loss** | 0.5% per trade (configurable) |
| **Engine position persistence** | Positions stored in Redis — survive engine restarts |
| **Orphaned sell rejection** | Engine rejects SELL signals with no matching position |
| **Suspect trade detection** | Flags trades where entry≈exit (<0.1% delta) |
| **Postmortem threshold** | Only fires on losses ≥0.1% (was 0.01% — noise filtering) |

### AI Agents

| Agent | Role | Trigger |
|-------|------|---------|
| **Strategy** | RSI + momentum scanner, auto-discovery, position rotation, pre-trade filters | Every 15s |
| **Critic** | Analyzes losing trades, generates evolutionary correction rules | Post-trade LOSS |
| **Devil's Advocate** | LLM risk review before each BUY signal | Pre-execution |
| **Researcher** | Ticker sentiment + trending stock discovery (LLM) — pre-trade filter | On-demand + scheduled |
| **Sentiment** | Fear & Greed Index — blocks BUY if FGI < 30 (extreme fear) | Pre-execution |
| **Macro Analyst** | Macro-economic context — blocks BUY if risk=HIGH | Pre-execution |
| **Optimizer** | Weekly AI parameter tuning with Approve/Reject UI | Hourly + on-demand |

### AI Recommendations (Approve/Reject UI)

1. Optimizer analyzes last 7 days of trades
2. Suggestions appear on dashboard with **Approve** / **Reject** buttons
3. **Approve** → parameter applied instantly to live strategy (hot-reload)
4. **Reject** → dismissed, no change
5. **Approve All** → bulk-apply all pending recommendations
6. Strategy auto-reloads with new parameters without restart

### LLM Observability (Traces)

- Every LLM call recorded: agent name, provider, model, estimated tokens, latency, success/error
- Circular buffer of last 200 calls
- Live trace table at `/llm` page — auto-refreshes every 15s
- Per-agent stats: call count, avg latency, error rate

### Daily Performance Report (`/report`)

5-tab analytics page:
- **Daily** — Equity curve with drawdown overlay, daily P&L history table
- **Tickers** — Per-ticker P&L ranking, win rate, avg win/loss, best/worst trade
- **Timing** — Hourly P&L heatmap (when does the strategy perform best?)
- **Strategies** — Signal effectiveness by type (MTF RSI / Bollinger / Forced / Stop Loss)
- **Weekly** — 12-week rollup with P&L, win rate, avg win/loss

### Self-Evolution (Feedback Loop, not code rewriting)

1. Trade executes → result published to Redis
2. Losing trades → **Critic Agent** (DeepSeek) analyzes root cause
3. Generates **Evolutionary Overlay** (e.g. "Block breakout buys if RSI > 70")
4. Stored in **LanceDB** vector database (6-dim market state embedding)
5. Next trade → **pre-trade vector lookup** → blocks trade if similar past failure exists

### SEBI Compliance

| Requirement | Implementation |
|-------------|---------------|
| Daily manual 2FA | Telegram relay + Redis `2fa:active` gate (engine checks before every trade) |
| <10 orders/sec | Token bucket rate limiter in Rust engine (10 burst, 1/sec refill) |
| Audit trail | LanceDB `audit_trail` table (append-only, persistent) + event log |
| White-box strategy | Explicit RSI rules + evolutionary overlays (no black-box code rewrite) |
| Static IP | AWS Elastic IP + broker-side IP whitelisting |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Real-time dashboard (WCAG 2, responsive, mobile-friendly) |
| `/report` | GET | Daily performance report — 5-tab analytics |
| `/settings` | GET | Settings UI — all strategy params, LLM, tickers configurable |
| `/llm` | GET | LLM provider health + call traces (token usage, latency) |
| `/api/v1/health` | GET | Service health + LanceDB entry count |
| `/api/v1/services` | GET | All service statuses (Memory, Engine, Orch, Redis, LLM) |
| `/api/v1/dash` | GET | Dashboard data (trades, portfolio, events, postmortems) |
| `/api/v1/dash/trade` | POST | Log executed trade → updates wallet + audit trail |
| `/api/v1/postmortem` | POST | Critic analysis of losing trade → stores evolution rule |
| `/api/v1/pretrade` | POST | Vector similarity lookup against past failures |
| `/api/v1/research` | POST | LLM research/sentiment for a ticker |
| `/api/v1/advocate` | POST | Devil's Advocate pre-trade risk check |
| `/api/v1/sentiment` | POST | Market sentiment + Fear & Greed Index |
| `/api/v1/macro` | POST | Macro-economic context analysis |
| `/api/v1/optimize` | POST | AI strategy parameter optimization |
| `/api/v1/wallet` | GET | Portfolio snapshot (capital, positions, P&L) |
| `/api/v1/wallet/reset` | POST | Reset wallet to initial capital |
| `/api/v1/settings` | GET/POST | Read/write strategy config (hot-reload) |
| `/api/v1/tickers/discover` | POST | LLM-powered NSE ticker discovery |
| `/api/v1/quote/{ticker}` | GET | Live yfinance quote |
| `/api/v1/llm/check` | GET | LLM provider config health |
| `/api/v1/llm/traces` | GET | LLM call history — tokens, latency, per-agent stats |
| `/api/v1/report/daily` | GET | Daily analytics: P&L, drawdown, tickers, hourly, strategies, weekly |
| `/api/v1/recommendations` | GET | Pending optimizer recommendations |
| `/api/v1/recommendations/approve` | POST | Approve + apply a recommendation |
| `/api/v1/recommendations/reject` | POST | Reject a recommendation |
| `/api/v1/recommendations/approve-all` | POST | Bulk-approve all pending |
| `/api/v1/history` | GET | Persistent trade history (PostgreSQL) with CSV export |
| `/ws/market` | WebSocket | Real-time NSE quotes (yfinance, 2s poll) |

## Architecture

| Layer | Language | Role | Key Tech |
|-------|----------|------|----------|
| Execution | Rust | Order placement, 2FA gate, rate limiter, position tracking, real P&L, Redis persistence | Tokio, Axum, Redis |
| Orchestration | Go | Redis pub/sub bridge, Telegram 2FA scheduler, postmortem orchestration | Redis, net/http |
| Memory | Python | LLM agents, LanceDB vectors, market data, dashboard + report + settings UI | FastAPI, yfinance, LanceDB, PostgreSQL |
| Storage | PostgreSQL | Persistent trade history, wallet state, positions | asyncpg |
| Vectors | LanceDB | Evolution memory (6-dim vectors) + SEBI audit trail | Embedded, zero-cost |
| Queue | Redis 7 | Trade signals (`trade:signal`), results (`trade:result`), 2FA flag, engine positions | Docker, Alpine |

## Paper Trading (Current Mode)

Full pipeline operational on AWS EC2. Trades execute against mock broker (no real money).

**Real components:**
- Live NSE market data (yfinance, dynamic ticker list via LLM discovery)
- Real P&L from actual market prices between entry and exit
- LLM-powered agents (DeepSeek): Critic, Researcher, Devil's Advocate, Sentiment, Macro, Optimizer
- LanceDB evolution memory + PostgreSQL trade history (persistent)
- Wallet position tracking with take-profit/stop-loss + daily loss limit
- Engine position persistence in Redis (survive restarts)
- Real-time WebSocket dashboard + daily report analytics
- LLM call traces with token usage and latency per agent
- AI recommendations with Approve/Reject workflow
- Telegram 2FA relay with Redis gate
- SEBI rate limiter and audit trail

**Simulated:** Broker connection (mock API — replace with Zerodha/Upstox/Angel One keys to go live).

To go production: see [production_ready.md](production_ready.md).

## Project Structure

```
StockAI/
├── cmd/
│   ├── orchestrator/main.go     # Central hub (Redis pub/sub, 2FA, postmortem)
│   └── relay/main.go            # Standalone 2FA Telegram relay
├── internal/                    # Go shared libraries
│   ├── broker/                  # Broker API interface (mock → real)
│   ├── handler/                 # TOTP HTTP form + Redis 2fa:active
│   ├── scheduler/               # IST-aware daily task scheduler
│   ├── telegram/                # Telegram Bot API client
│   └── token/                   # Session token manager
├── execution/                   # Rust engine
│   ├── src/main.rs              # Redis signal subscriber, 2FA gate, rate limiter, position persistence, suspect trades
│   ├── src/broker/              # REST + WebSocket broker client
│   ├── src/engine/              # Order lifecycle, risk checks
│   ├── src/market/              # Market feed processor + price map
│   └── src/orderbook/           # BTreeMap bid/ask book
├── app/                         # Python memory + agents + UI
│   ├── main.py                  # FastAPI entry, WebSocket market feed, page routes
│   ├── strategy.py              # Auto-trading: RSI, MACD, BB, volume, loss limits, advisor gates
│   ├── market_data.py           # yfinance→WebSocket bridge, dynamic tickers
│   ├── router.py                # All API routes + audit logging + recommendations
│   ├── settings_store.py        # Hot-reloadable config (JSON + env fallback)
│   ├── config.py                # Pydantic Settings (all env vars typed)
│   ├── optimizer.py             # AI parameter tuning (weekly analysis)
│   ├── critic.py                # Post-mortem LLM analysis
│   ├── researcher.py            # LLM research + ticker discovery
│   ├── devils_advocate.py       # Pre-trade risk review (production prompt)
│   ├── sentiment_agent.py       # Market sentiment + Fear & Greed Index
│   ├── macro_analyst.py         # Macro-economic analysis
│   ├── vector_store.py          # LanceDB: evolution memory + audit trail
│   ├── wallet.py                # Portfolio tracking (configurable capital)
│   ├── events.py                # In-memory event store
│   ├── db.py                    # PostgreSQL: trades, wallet, daily/weekly/hourly/stats queries
│   ├── models.py                # Pydantic models for all API responses
│   ├── llm/providers.py         # Multi-provider with trace recording: DeepSeek, OpenAI, Gemini, Anthropic, Bedrock, Ollama
│   └── templates/
│       ├── dashboard.html       # Real-time responsive dashboard with AI recommendations
│       ├── report.html          # Daily performance analytics (5 tabs)
│       ├── history.html         # Persistent trade history + CSV export
│       ├── research.html        # LLM research per ticker
│       ├── news.html            # Live NSE news feed
│       ├── backtest.html        # Strategy backtesting UI
│       ├── settings.html        # Config UI (all params hot-reloadable)
│       ├── llm.html             # LLM provider health + real-time traces
│       └── base.css             # Shared dark theme CSS
├── docker-compose.yml           # 5 services: redis, postgres, memory, orchestrator, engine
├── .env.example                 # All config vars with docs
├── install.sh                   # One-line bootstrap
├── aws-deploy.sh                # AWS EC2 one-command deploy
├── aws_env.md                   # AWS deployment reference
└── production_ready.md          # What's needed to go live
```

## Env Variables

See `.env.example` for full list. Key vars:

| Variable | Description |
|----------|-------------|
| `MEMORY_DEEPSEEK_API_KEY` | DeepSeek API key (required) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for 2FA relay |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `STRATEGY_TICKERS` | Comma-separated NSE tickers (default: top 5) |
| `STRATEGY_MAX_POSITIONS` | Max simultaneous open positions |
| `STRATEGY_INITIAL_CAPITAL` | Starting wallet capital (paper) |
| `DATABASE_URL` | PostgreSQL connection string |

All strategy params editable at `/settings` — no restart needed.

## Budget

| Component | Monthly Cost |
|-----------|-------------|
| LLM (DeepSeek) | $0.50–$3 (agents + discovery) |
| AWS EC2 t2.small | ~$12 (free tier eligible) |
| PostgreSQL | $0 (Docker) |
| LanceDB | $0 (embedded) |
| Redis | $0 (Docker) |
| yfinance | $0 (free) |
| **Total** | **$13–$16/month** |

## License

MIT

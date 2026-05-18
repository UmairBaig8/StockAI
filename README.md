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
    │   Position tracking   │    │  Dashboard + UI    │
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

## How It Works

### Auto-Trading Strategy

| Feature | Detail |
|---------|--------|
| **Market hours** | 09:15–15:30 IST, Mon–Fri aware |
| **Auto-discovery** | LLM scans trending NSE tickers at 09:00 IST + hourly |
| **Signal engine** | RSI oversold detection every 15s across all tickers |
| **Position rotation** | Sells weakest holding when full, rotates into best opportunity |
| **Quality filters** | Skips dead stocks (no movement), skips overbought (RSI > 70) |
| **Best-opportunity** | Ranks all tickers by momentum + RSI + activity score |
| **Configurable** | All params editable live at `/settings` UI |

### AI Agents

| Agent | Role | Trigger |
|-------|------|---------|
| **Strategy** | RSI + momentum scanner, auto-discovery, position rotation | Every 15s |
| **Critic** | Analyzes losing trades, generates evolutionary correction rules | Post-trade LOSS |
| **Devil's Advocate** | LLM risk review before each natural signal | Pre-execution |
| **Researcher** | Ticker sentiment + trending stock discovery (LLM) | On-demand + scheduled |
| **Sentiment** | Market sentiment analysis (LLM) | On-demand |
| **Macro Analyst** | Macro-economic context (LLM) | On-demand |

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
| `/settings` | GET | Settings UI — all strategy params, LLM, tickers configurable |
| `/api/v1/health` | GET | Service health + LanceDB entry count |
| `/api/v1/services` | GET | All service statuses (Memory, Engine, Orch, Redis, LLM) |
| `/api/v1/dash` | GET | Dashboard data (trades, portfolio, events, postmortems) |
| `/api/v1/dash/trade` | POST | Log executed trade → updates wallet + audit trail |
| `/api/v1/postmortem` | POST | Critic analysis of losing trade → stores evolution rule |
| `/api/v1/pretrade` | POST | Vector similarity lookup against past failures |
| `/api/v1/research` | POST | LLM research/sentiment for a ticker |
| `/api/v1/advocate` | POST | Devil's Advocate pre-trade risk check |
| `/api/v1/sentiment` | POST | Market sentiment analysis |
| `/api/v1/macro` | POST | Macro-economic context analysis |
| `/api/v1/wallet` | GET | Portfolio snapshot (capital, positions, P&L) |
| `/api/v1/wallet/reset` | POST | Reset wallet to initial capital |
| `/api/v1/settings` | GET/POST | Read/write strategy config (hot-reload) |
| `/api/v1/tickers/discover` | POST | LLM-powered NSE ticker discovery |
| `/api/v1/quote/{ticker}` | GET | Live yfinance quote |
| `/ws/market` | WebSocket | Real-time NSE quotes (yfinance, 2s poll) |

## Architecture

| Layer | Language | Role | Key Tech |
|-------|----------|------|----------|
| Execution | Rust | Order placement, 2FA gate, rate limiter, position tracking, real P&L | Tokio, Axum, Redis |
| Orchestration | Go | Redis pub/sub bridge, Telegram 2FA scheduler, postmortem orchestration | Redis, net/http |
| Memory | Python | LLM agents, LanceDB vectors, market data, dashboard + settings UI | FastAPI, yfinance, LanceDB |
| Storage | LanceDB | Evolution memory (6-dim vectors) + SEBI audit trail | Embedded, zero-cost |
| Queue | Redis 7 | Trade signals (`trade:signal`), results (`trade:result`), 2FA flag | Docker, Alpine |

## Paper Trading (Current Mode)

Full pipeline operational on AWS EC2. Trades execute against mock broker (no real money).

**Real components:**
- Live NSE market data (yfinance, dynamic ticker list via LLM discovery)
- Real P&L from actual market prices between entry and exit
- LLM-powered agents (DeepSeek): Critic, Researcher, Devil's Advocate, Sentiment, Macro
- LanceDB evolution memory + audit trail (persistent)
- Wallet position tracking with take-profit/stop-loss
- Real-time WebSocket dashboard
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
│   ├── src/main.rs              # Redis signal subscriber, 2FA gate, rate limiter
│   ├── src/broker/              # REST + WebSocket broker client
│   ├── src/engine/              # Order lifecycle, risk checks
│   ├── src/market/              # Market feed processor + price map
│   └── src/orderbook/           # BTreeMap bid/ask book
├── app/                         # Python memory + agents + UI
│   ├── main.py                  # FastAPI entry, WebSocket market feed
│   ├── strategy.py              # Auto-trading: RSI, momentum, discovery, rotation
│   ├── market_data.py           # yfinance→WebSocket bridge, dynamic tickers
│   ├── router.py                # All API routes + audit logging
│   ├── settings_store.py        # Hot-reloadable config (JSON + env fallback)
│   ├── critic.py                # Post-mortem LLM analysis
│   ├── researcher.py            # LLM research + ticker discovery
│   ├── devils_advocate.py       # Pre-trade risk review
│   ├── sentiment_agent.py       # Market sentiment analysis
│   ├── macro_analyst.py         # Macro-economic analysis
│   ├── vector_store.py          # LanceDB: evolution memory + audit trail
│   ├── wallet.py                # Portfolio tracking (configurable capital)
│   ├── events.py                # In-memory event store
│   ├── llm/providers.py         # Multi-provider: DeepSeek, OpenAI, Gemini, Anthropic, Bedrock, Ollama
│   └── templates/
│       ├── dashboard.html       # Real-time responsive dashboard
│       └── settings.html        # Config UI (all params hot-reloadable)
├── docker-compose.yml           # 4 services: redis, memory, orchestrator, engine
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

All strategy params editable at `/settings` — no restart needed.

## Budget

| Component | Monthly Cost |
|-----------|-------------|
| LLM (DeepSeek) | $0.50–$3 (agents + discovery) |
| AWS EC2 t2.small | ~$12 (free tier eligible) |
| LanceDB | $0 (embedded) |
| Redis | $0 (Docker) |
| yfinance | $0 (free) |
| **Total** | **$13–$16/month** |

## License

MIT

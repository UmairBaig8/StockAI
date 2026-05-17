# StockAI — Self-Evolving Algorithmic Trading Agent

A production-grade, multi-agent trading system for the Indian Stock Market (NSE/BSE). SEBI 2026 compliant. Built with Rust (execution), Go (orchestration), and Python (cognition).

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
    │   Risk checks        │    │  YFinance (data)   │
    └──────────────────────┘    └────────────────────┘
```

## Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/UmairBaig8/StockAI/main/install.sh | bash
```

## Architecture

| Layer | Language | Role | Tech |
|-------|----------|------|------|
| Execution | Rust | Order placement, market feed, risk checks | Tokio, Axum, Redis |
| Orchestration | Go | Redis pub/sub bridge, 2FA relay, scheduling | Gin, Redis |
| Memory | Python | LLM critic, vector DB, market data, dashboard | FastAPI, LanceDB, yfinance |

## AI Agents

| Agent | Role | When |
|-------|------|------|
| **Critic** | Analyzes losing trades, generates correction rules | After-market (3:30 PM) |
| **Researcher** | Scans news/sentiment for a ticker | On-demand / pre-market |
| **Devil's Advocate** | Argues against every trade, risk scoring | Pre-execution |
| **Actor** | Places trades after all checks pass | Market hours |

## Self-Evolution

The agent doesn't rewrite its code. It learns via a **Feedback Loop**:

1. Trade executes → result published to Redis
2. Losing trades → **Critic Agent** (DeepSeek) analyzes root cause
3. Generates **Evolutionary Overlay** (e.g., "Block breakout buys if RSI > 70")
4. Stored in **LanceDB** vector database (keyed by market state embedding)
5. Next trade → **pre-trade vector lookup** → block trade if similar past failure exists

## SEBI 2026 Compliance

- <10 orders/second (retail algo category — no exchange registration)
- Daily manual 2FA via Telegram relay (SEBI mandate)
- Static IP requirement (for live trading with a broker)
- Full audit logging of every decision and evolution
- Core strategy logic remains explainable ("white box" — no black-box evolution)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Live monitoring dashboard |
| `/api/v1/health` | GET | Service health + memory entries |
| `/api/v1/services` | GET | All service statuses (Memory, Engine, Orch, Redis, LLM) |
| `/api/v1/postmortem` | POST | Analyze losing trade → store correction rule |
| `/api/v1/pretrade` | POST | Vector lookup: check if current setup matches past failure |
| `/api/v1/research` | POST | News/sentiment analysis for a ticker |
| `/api/v1/advocate` | POST | Devil's Advocate risk check before trade |
| `/api/v1/wallet` | GET | Portfolio snapshot (capital, invested, positions, P&L) |
| `/api/v1/wallet/reset` | POST | Reset wallet to initial capital |
| `/api/v1/dash` | GET | Dashboard aggregated data |
| `/api/v1/dash/trade` | POST | Log executed trade to dashboard |
| `/ws/market` | WebSocket | Real-time NSE quotes (yfinance, 2s poll) |

## Env Variables

| Variable | Required | Default |
|----------|----------|---------|
| `MEMORY_LLM_PROVIDER` | Yes | `deepseek` |
| `MEMORY_DEEPSEEK_API_KEY` | Yes | — |
| `MEMORY_DEEPSEEK_MODEL` | No | `deepseek-chat` |
| `TELEGRAM_BOT_TOKEN` | For 2FA | — |
| `TELEGRAM_CHAT_ID` | For 2FA | — |
| `RELAY_URL` | For 2FA | `http://localhost:8080` |

### Other LLM Providers

Set `MEMORY_LLM_PROVIDER` to: `gemini`, `openai`, `anthropic`, `deepseek`, `bedrock`, or `ollama`. Add the corresponding API key env vars (see `.env.example`).

## Running Locally

```bash
# With Docker (recommended)
cp .env.example .env  # edit .env with your DeepSeek key
docker compose up -d

# Without Docker (dev mode)
make run-memory    # Python FastAPI on :8000
make run-engine    # Rust execution on :9001
make run-orchestrator  # Go hub on :8080
```

## Deploy to AWS EC2

```bash
EC2_IP=<your-ec2-ip> MEMORY_DEEPSEEK_API_KEY=sk-... bash deploy.sh
```

## Push a Test Trade

```bash
# Send trade signal through the full pipeline:
docker compose exec redis redis-cli publish trade:signal \
  '{"ticker":"TATAPOWER","exchange":"NSE","direction":"BUY","quantity":100,"price":407.0,"reason":"test","timestamp":"2026-05-18T09:15:00+05:30"}'

# Watch the flow:
docker compose logs -f
```

## Project Structure

```
StockAI/
├── cmd/
│   ├── relay/main.go            # 2FA Telegram relay
│   └── orchestrator/main.go     # Central hub (Redis pub/sub + HTTP bridge)
├── internal/                    # Go shared libraries
├── execution/                   # Rust engine
│   ├── src/main.rs              # Redis subscriber → executor
│   ├── src/broker/              # REST + WebSocket client
│   ├── src/engine/              # Order lifecycle, risk checks
│   ├── src/market/              # Market feed processor
│   ├── src/orderbook/           # BTreeMap bid/ask book
│   └── src/mock/                # Mock broker server
├── app/                         # Python memory + agents
│   ├── main.py                  # FastAPI entry + WebSocket
│   ├── config.py                # Settings (env-based)
│   ├── models.py                # Pydantic schemas
│   ├── router.py                # API routes
│   ├── critic.py                # Post-mortem LLM agent
│   ├── researcher.py            # News/sentiment agent
│   ├── devils_advocate.py       # Pre-trade risk checker
│   ├── vector_store.py          # LanceDB interface
│   ├── market_data.py           # yfinance → WebSocket bridge
│   ├── wallet.py                # Portfolio tracking
│   ├── events.py                # In-memory event store
│   └── llm/                     # Multi-provider LLM adapters
├── templates/dashboard.html     # Monitoring dashboard
├── docker-compose.yml
├── install.sh                   # One-line bootstrap
├── deploy.sh                    # AWS EC2 deploy
├── Makefile
└── .env.example
```

## Budget

| Component | Monthly Cost |
|-----------|-------------|
| LLM (DeepSeek) | $0.50–$2 (postmortem + advocate) |
| VPS (for live trading) | $6–$14 (DigitalOcean/GigaNodes) |
| LanceDB | $0 (embedded, local) |
| Redis | $0 (Docker, local) |
| yfinance | $0 (free) |
| **Total** | **$7–$16/month** |

## License

MIT

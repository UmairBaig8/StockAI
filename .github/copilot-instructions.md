# StockAI — Copilot Instructions

> Auto-generated from `.opencode/skills/` for GitHub Copilot compatibility.

## Project Overview

StockAI is an algorithmic trading system for NSE (Indian Stock Market) running paper trading on AWS. Multi-language: Python (FastAPI), Go (orchestrator), Rust (execution engine).

**Deployment**: `devserver/terraform/` — single `terraform apply` → EC2 with all services.  
**Current instance**: `100.28.190.112` (Elastic IP). Dashboard: `http://100.28.190.112:8000`.

## Architecture

```
Python (FastAPI, :8000) → Redis pub/sub → Go (Orchestrator, :8080) → Rust (Engine, :9001)
                              ↕                         ↕
                         PostgreSQL :5432          Telegram Bot
```

| Service | Language | Port | Purpose |
|---------|----------|------|---------|
| memory | Python 3.12 | 8000 | Strategy, market data, LLM agents, dashboard |
| orchestrator | Go 1.24 | 8080 | Redis bridge, Telegram app bot, TOTP |
| engine | Rust | 9001 | Trade execution, mock broker |
| redis | — | 6379 | Pub/sub, persistence, paper mode |
| postgres | — | 5432 | Trades, wallet, events, LLM traces |

## Pipeline

```
yfinance (2s poll) → StrategyAgent (RSI/MACD/BB) → Pre-trade checks (5 LLM guards)
→ Redis trade:signal → Engine (mock execution) → Redis trade:result
→ Strategy tracks P&L → Losses trigger Critic postmortem → LanceDB memory
```

## Key Files

| File | Role |
|------|------|
| `app/main.py` | FastAPI entry, WebSocket, templates |
| `app/strategy.py` | RSI/MACD/BB signals, forced trades, risk gates |
| `app/llm/providers.py` | Multi-provider: DeepSeek→Gemini→OpenAI→Bedrock |
| `app/db.py` | PostgreSQL via asyncpg |
| `app/critic.py` | Post-mortem LLM analysis on losses |
| `app/researcher.py` | LLM research + ticker discovery |
| `app/wallet.py` | Balance, P&L, position tracking |
| `app/market_data.py` | yfinance → WebSocket bridge |
| `app/settings_store.py` | Hot-reloadable params with guardrails |
| `cmd/orchestrator/main.go` | Go orchestrator entry |
| `execution/src/main.rs` | Rust engine entry |
| `devserver/` | AWS deployment (Terraform + Docker + Bot) |

## Coding Conventions

### Python
- Use `uv` for package management (`uv sync`, `uv run`)
- Config via `MEMORY_*` env vars, validated at startup (Pydantic)
- New agents: create `app/new_agent.py`, wire in `strategy.py` pre-trade checks
- New endpoints: add to `app/router.py`, use Pydantic models from `app/models.py`
- LLM calls: use `create_llm_for_agent(settings, "agent_name")`, provider auto-fallback
- DB: `asyncpg` pool, migrations in `_migrate()`, new tables added there
- Logging: `logging.getLogger(__name__)`, structured messages
- Format: `ruff check app/ && ruff format app/`

### Go
- `go build ./cmd/orchestrator`, `go vet ./...`, `go test ./...`
- New handlers: `internal/handler/`, register in `internal/broker/`
- Telegram: `internal/telegram/bot.go`
- Redis: subscribe `trade:signal`, publish `trade:result`

### Rust
- `cargo build --release`, `cargo clippy`, `cargo test`
- New brokers: implement `Broker` trait in `execution/src/broker/`
- Redis: `tokio` + `redis` crate for pub/sub
- WebSocket: `tokio-tungstenite` for market data

### Infrastructure
- Deploy: `cd devserver/terraform && terraform apply`
- Update: `git push` → SSH into EC2 → `git pull` → `docker compose up -d --build`
- Secrets: `.env` and `terraform.tfvars` are gitignored, never commit
- Ports: 8000 (memory), 8080 (orchestrator), 8443 (code-server), 22 (SSH)

## Strategy Parameters

| Setting | Default | Guardrails | Description |
|---------|---------|------------|-------------|
| `position_size_pct` | 5% | 2-15% | Per-trade position size |
| `max_positions` | 3 | 1-8 | Max concurrent positions |
| `stop_loss_pct` | 0.8% | 0.5-2% | Stop loss threshold |
| `take_profit_pct` | 1.5% | — | Take profit target |
| `force_trade_sec` | 600s | — | Max idle before forced trade |

All editable at `/settings` UI. Guardrails enforced in `app/settings_store.py`.

## Risk Controls

- **Daily loss limit**: 2% of equity → halts trading
- **Consecutive losses**: 3+ → 10min cooldown
- **Per-ticker circuit breaker**: 3 consecutive losses on same ticker → 30min cooldown
- **Kill-switch**: Redis key `trading:halt` checked every 30s by strategy
- **Trailing stop**: breakeven at +2%, trail at -3% after +5%

## LLM Agents

| Agent | File | Role |
|-------|------|------|
| Critic | `app/critic.py` | Post-mortem analysis on losses |
| Researcher | `app/researcher.py` | Deep analysis, ticker discovery |
| Devil's Advocate | `app/devils_advocate.py` | Contrarian pre-trade review |
| Sentiment | `app/sentiment_agent.py` | Fear & Greed Index |
| Macro | `app/macro_analyst.py` | Macro-economic context |
| Optimizer | `app/optimizer.py` | Strategy parameter suggestions |

## Testing

```bash
# Python
uv run pytest tests/ -v

# Rust
cd execution && cargo test

# Go
go test ./... -v
```

Priority: Strategy signals → API endpoints → Wallet → Order execution → LLM fallback chain.

## Common Tasks

### Add new agent
1. `app/new_agent.py` — async class using `create_llm_for_agent`
2. Wire into `strategy.py` `_run_pre_trade_checks()`
3. Add endpoint in `router.py` if needed
4. Add env vars to `config.py`

### Add new LLM provider
1. `app/llm/providers.py` — new adapter class extending `LLMAdapter`
2. Add to `create_llm_for_agent()` switch
3. Add env vars to `config.py` Settings
4. Update `.env.example`

### Deploy to AWS
1. `git add . && git commit -m "..." && git push`
2. SSH: `ssh -i devserver/terraform/devserver-key.pem ubuntu@100.28.190.112`
3. Pull: `cd /opt/stockai && git pull`
4. Rebuild: `cd devserver && sudo docker compose -f docker-compose.yml up -d --build memory`

### Emergency halt
Send `/halt` to dev Telegram bot. Sets Redis flag, strategy stops all trading. `/resume` to re-enable.

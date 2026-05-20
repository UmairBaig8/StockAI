# Python Memory Service

FastAPI + DeepSeek/Gemini/OpenAI/Anthropic/Bedrock multi-agent trading system.

## Triggers

- "python", "memory service", "fastapi", "uvicorn"
- "strategy", "critic", "researcher", "sentiment", "macro"
- "LLM provider", "deepseek", "gemini", "openai", "bedrock"
- "lancedb", "vector store", "evolution memory"
- "market data", "yfinance", "websocket feed"
- "dashboard", "templates", "jinja2", "frontend"
- "add feature to memory", "fix python bug", "python test"

## Architecture

```
app/
├── main.py              # FastAPI entry, WS feeds, template serving, gzip compression
├── config.py            # Pydantic settings, env vars, LLM provider config
├── models.py            # Pydantic models: TradePayload, MarketState, CriticResponse
├── router.py            # API routes: /api/v1/health, /wallet, /dash, /quote, /services
├── strategy.py          # StrategyAgent: RSI/MACD/BB signals, forced trades, pre-trade checks
├── critic.py            # CriticAgent: postmortems on losses, correction rules
├── devils_advocate.py   # Devil's Advocate: contrarian analysis before trades
├── researcher.py        # ResearchAgent: deep analysis, news context enrichment
├── sentiment_agent.py   # SentimentAgent: market sentiment from news/feeds
├── macro_analyst.py     # MacroAnalyst: macroeconomic context
├── market_data.py       # MarketDataBridge: yfinance polling, WS broadcasting
├── news_scraper.py      # RSS scrapers: Moneycontrol, NSE announcements
├── options_flow.py      # OptionsFlowScanner: PCR, unusual volume detection
├── vector_store.py      # LanceDB: evolution memory + audit trail
├── wallet.py            # Wallet: balance, P&L, position tracking
├── db.py                # PostgreSQL: asyncpg, trade history, wallet persistence
├── events.py            # Event system: trade events, dashboard push
├── settings_store.py    # Hot-reloadable strategy params via UI
├── optimizer.py         # Strategy optimization suggestions
├── optimizer_bridge.py  # Bridge for optimizer UI
├── backtest.py          # Backtesting engine (WIP)
├── dashboard_bridge.py  # Dashboard data aggregation
└── llm/
    └── providers.py     # Multi-provider routing: DeepSeek → Gemini → OpenAI → Anthropic → Bedrock
```

## Pipeline Flow

1. **Market Data** polls yfinance every 2s → pushes quotes via WebSocket
2. **Strategy Agent** scans for RSI/MACD/BB signals → forced trade every 5 min if no signal
3. Pre-trade checks: memory (LanceDB), sentiment, advocate, researcher, macro
4. Signal published to Redis `trade:signal`
5. **Engine** (Rust) receives signal → mock execution → publishes `trade:result`
6. **Strategy** listens to `trade:result` → tracks consecutive losses
7. Losses trigger **Critic** postmortem → stored in LanceDB with correction rules

## LLM Provider Chain

```
MEMORY_LLM_PROVIDER=deepseek (primary)
  ↓ fallback
MEMORY_GEMINI_API_KEY (gemini-2.5-flash)
  ↓ fallback
MEMORY_OPENAI_API_KEY (gpt-4o-mini)
  ↓ fallback
MEMORY_ANTHROPIC_API_KEY
  ↓ fallback
MEMORY_AWS_ACCESS_KEY_ID (Bedrock: claude-sonnet-4)
```

## Commands

### Local Dev

```bash
# Install deps
uv sync

# Run memory service
uv run uvicorn app.main:app --port 8000 --reload

# Run with specific provider
MEMORY_LLM_PROVIDER=gemini uv run uvicorn app.main:app --port 8000 --reload
```

### Test

```bash
# Quick import check
make test-memory

# Full test (when tests exist)
uv run pytest tests/ -v
```

### Lint/Format

```bash
uv run ruff check app/
uv run ruff format app/
```

### Docker

```bash
# Build
docker build -f Dockerfile.memory -t stockai-memory .

# Run
docker run -p 8000:8000 --env-file .env stockai-memory
```

## Key Patterns

### Adding a New Agent

1. Create `app/new_agent.py` with async class
2. Import in `main.py`, instantiate in lifespan
3. Wire into strategy pre-trade checks
4. Add endpoint in `router.py` if needed

### Adding LLM Provider

1. Add to `app/llm/providers.py` provider registry
2. Add env vars to `config.py` Settings class
3. Add fallback chain in `LLMProvider.__init__`
4. Update `.env.example`

### Adding API Endpoint

1. Add route in `app/router.py`
2. Use Pydantic models from `app/models.py`
3. Add WebSocket broadcast in `events.py` if real-time
4. Update dashboard template if UI needed

### LanceDB Schema

```python
# vector_store.py
# Tables: trading_memory, audit_trail
# Fields: id, timestamp, query, response, context, metadata
# Used for: evolution memory, critic postmortems, correction rules
```

### PostgreSQL Schema

```python
# db.py
# Tables: wallet, positions, trades
# Async via asyncpg
# Used for: persistent state, trade history, analytics
```

## File Locations

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI entry, WS, templates |
| `app/strategy.py` | Trading signals, forced trades |
| `app/critic.py` | Postmortems, correction rules |
| `app/llm/providers.py` | Multi-provider routing |
| `app/vector_store.py` | LanceDB memory |
| `app/db.py` | PostgreSQL persistence |
| `app/config.py` | Settings, env vars |
| `app/models.py` | Pydantic models |
| `pyproject.toml` | Python dependencies |
| `Dockerfile.memory` | Docker build |

## Dependencies

```
fastapi, uvicorn, pydantic, pydantic-settings
google-genai, openai, anthropic, boto3 (LLM providers)
lancedb (vector store)
yfinance (market data)
redis (pub/sub)
asyncpg (PostgreSQL)
httpx, feedparser, numpy
```

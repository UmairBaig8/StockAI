# Production Readiness Checklist

## What's Already Done

- Full multi-agent pipeline (Strategy → Advocate → Memory → Execution → Postmortem)
- Real-time NSE market data (yfinance, 5 tickers)
- Dashboard with live WebSocket market feed + trade history
- Wallet with position tracking + P&L calculation
- LanceDB vector store for evolution memory (6-dim market vectors)
- LLM-powered agents (DeepSeek): Critic, Researcher, Devil's Advocate, Sentiment, Macro
- Rust execution engine (<1ms latency)
- Go orchestrator (Redis pub/sub, scheduler, Telegram bot)
- Docker Compose deployment
- AWS EC2 one-command deploy (`aws-deploy.sh`)
- SEBI 2026 compliant architecture (paper trail, 2FA, risk checks)

## What's Needed for Production

### 1. Broker API Keys (THE ONLY BLOCKER)

Replace mock broker with real API:

| Broker | API | Python Client | Docs |
|--------|-----|---------------|------|
| **Zerodha Kite** | Kite Connect | `kiteconnect` | https://kite.trade |
| **Upstox** | Upstox API v2 | `upstox-python-sdk` | https://upstox.com/developer |
| **Angel One** | SmartAPI | `smartapi-python` | https://smartapi.angelone.in |

**Files to modify:**
- `app/router.py` — replace paper `/orders` endpoint with real broker calls
- `execution/src/broker/client.rs` — replace mock broker URL with real broker API
- `internal/broker/broker.go` — replace `MockAPI` with real broker `Authenticate()`

**Env vars to add:**
```env
BROKER_API_KEY=...
BROKER_API_SECRET=...
BROKER_ACCESS_TOKEN=...
BROKER_PROVIDER=zerodha  # or upstox, angelone
```

### 2. Execution Engine — Real exit logic

Current: Engine returns synthetic `TradeResult` immediately after order placement.

Need: Track open positions, receive market quotes, exit on take-profit / stop-loss or strategy signal.

**File:** `execution/src/main.rs` — `signal_loop()` function
- Store open positions in a `HashMap`
- Subscribe to market quotes from the broker feed
- Check exit conditions (TP/SL) on each quote
- Publish real `TradeResult` with actual P&L

### 3. Wallet Persistence

Current: Wallet resets on restart (in-memory dataclass).

**Option A (Simple):** JSON file snapshot on every trade
**Option B (Production):** PostgreSQL/SQLite for positions + trade history

**File:** `app/wallet.py` — add `save()` / `load()` methods

### 4. Event Store Persistence

**File:** `app/events.py` — same as wallet, persist to disk

### 5. Real Telegram Bot

Current: bot token = `"test"`, all messages fail with 404.

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`
3. Bot will:
   - Send daily 2FA prompt (currently at 08:45 IST)
   - Notify on auth attempts
   - Send trade alerts on large P&L swings

### 6. Researcher — Live Data Scraping

Current: LLM-only research (uses training data, not live news).

**Add:**
- NSE/BSE RSS feed scraping
- Google News API or NewsAPI integration
- SEBI regulatory filing check (via BSE/NSE corporate announcements)

**File:** `app/researcher.py` — add `_scrape_news()` method

### 7. Redis Password

Current: No password on Redis (open to anyone on the instance).

Set `REDIS_PASSWORD` env var and update `docker-compose.yml`.

### 8. HTTPS / Domain

Current: HTTP only. For production:
- Set up Route53 domain → EC2 Elastic IP
- Add nginx reverse proxy with Let's Encrypt SSL
- Or use Cloudflare Tunnel

### 9. Monitoring

- Add health check alerts (UptimeRobot or AWS CloudWatch)
- Set up Docker log rotation
- Add `/api/v1/metrics` endpoint for Prometheus

### 10. VPS Alternative (Recommended)

For lower latency to NSE (Mumbai):
- AWS Mumbai region (`ap-south-1`) or
- DigitalOcean Bangalore or
- Linode Mumbai

## Quick Start: From Paper → Production

```bash
# 1. Add broker credentials
cp .env.example .env
# Edit .env: add BROKER_API_KEY, BROKER_API_SECRET, TELEGRAM_BOT_TOKEN

# 2. Update broker client (replace MockAPI)
# Edit: internal/broker/broker.go

# 3. Rebuild & deploy
MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh
```

## Current Paper Trading Pipeline

```
Market Data (yfinance, 2s poll)
        │
        ▼
┌─ Strategy Agent (15s loop) ───┐
│  RSI calculation              │
│  BUY: RSI<55 & drop>0.2%      │
│  SELL: TP+2% or SL-3%         │
│  Forced trade if idle >5min    │
└───────────┬───────────────────┘
            │ trade:signal
            ▼
┌─ Rust Engine ────────────────┐
│  Risk checks (<5% per pos)   │
│  Executes via mock broker    │
│  Synthetic P&L (±2% jitter)  │
└───────────┬───────────────────┘
            │ trade:result
            ▼
┌─ Go Orchestrator ────────────┐
│  Loss → Postmortem (Critic)  │
│  All → Push to Dashboard     │
│  Fetches live market state   │
└───────────┬───────────────────┘
            │
            ▼
┌─ Python Memory ──────────────┐
│  LanceDB vector store        │
│  Wallet position tracking    │
│  Event/trade history         │
│  Evolution rules learned     │
└──────────────────────────────┘
```

**To go production:** Replace "Executes via mock broker" with "Executes via Zerodha/Upstox API" — that's the only real change needed.

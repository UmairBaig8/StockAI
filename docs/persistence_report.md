# StockAI Persistence Report — May 21, 2026

## ✅ All 5 Persistence Fixes Deployed

**Commit**: `c99450b` — `feat: persist all runtime state`  
**Deployed to**: `52.70.58.6` (i-0845fd29ea0f8b328)  

---

## 📊 Gap Analysis Summary

| # | Component | Data Lost Before | Persistence After |
|---|-----------|-----------------|-------------------|
| **P0** | Price history | All ticker prices (200 per ticker) | ✅ Redis sorted sets |
| **P1** | Risk gates | Loss counters, cooldowns, trailing stops | ✅ Redis hash |
| **P2** | Event store | Last 50 trades/events, 10 rules | ✅ PostgreSQL `events` table |
| **P2** | LLM traces | Last 200 call records | ✅ PostgreSQL `llm_traces` table |
| **P2** | Optimizer recs | Pending suggestions | ✅ JSON file `data/optimizer.json` |
| **N/A** | LanceDB | ✅ Already persisted (Docker volume) | File-based, survives restarts |
| **N/A** | Wallet | ✅ Already persisted (PostgreSQL) | Full round-trip save/load |
| **N/A** | Trades | ✅ Already persisted (PostgreSQL) | Full trade history |
| **N/A** | Settings | ✅ Already persisted (JSON file) | `data/settings.json` |

---

## 🔧 Implementation Details

### P0: Price History → Redis
**File**: `app/strategy.py`

- **Save**: `_save_price_history(ticker, prices)` — Redis sorted set `ph:{ticker}` with 24h TTL
- **Load**: `_load_price_history()` — restores all `ph:*` keys on startup
- **Trigger**: Every 5 min in heartbeat loop + on shutdown
- **Impact**: After restart, RSI/MACD/BB signals fire immediately instead of waiting 7 min

### P1: Risk Gates → Redis
**File**: `app/strategy.py`

- **Save**: `_save_risk_state()` — Redis hash `strategy:risk` with 24h TTL
  - `_consecutive_losses`
  - `_loss_cooldown_until`
  - `_daily_loss` / `_daily_loss_date`
  - `_ticker_losses` (JSON)
  - `_ticker_cooldown_until` (JSON)
  - `_highest_price` (trailing stops, JSON)
- **Load**: `_load_risk_state()` — restores all fields on startup
- **Impact**: Safety brakes survive restarts; no more overtrading after crash

### P2: Event Store → PostgreSQL
**Files**: `app/events.py`, `app/db.py`

- **New table**: `events` (msg, level, ticker, timestamp)
- **Save**: `save_event()`, `save_postmortem()` — fire-and-forget on every add
- **Load**: `load_events(50)`, `load_recent_rules(10)` — called in `EventStore.load_from_db()`
- **Impact**: Dashboard shows full event history after restart

### P2: LLM Traces → PostgreSQL
**Files**: `app/llm/providers.py`, `app/db.py`, `app/router.py`

- **New table**: `llm_traces` (agent, provider, model, tokens, latency, success, error, prompt, response)
- **Save**: `_persist_trace()` — fire-and-forget on every LLM call
- **Load**: `get_traces_with_db()` — merges in-memory buffer + DB, deduplicates
- **Endpoint**: `/api/v1/llm/traces` now async, returns full history
- **Impact**: LLM observability survives restarts; full audit trail

### P2: Optimizer Recommendations → JSON File
**File**: `app/optimizer_bridge.py`

- **Save**: `_save()` — writes `data/optimizer.json` on every push
- **Load**: `_load()` — reads on bridge initialization
- **Impact**: Pending suggestions survive restarts

---

## 🗄️ New Database Tables

```sql
-- Events (dashboard activity log)
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    msg TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    ticker TEXT DEFAULT '',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- LLM Traces (observability)
CREATE TABLE llm_traces (
    id SERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens_est INTEGER NOT NULL DEFAULT 0,
    response_tokens_est INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT DEFAULT '',
    prompt TEXT DEFAULT '',
    response TEXT DEFAULT '',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Strategy State (PostgreSQL fallback)
CREATE TABLE strategy_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 🔄 Startup/Shutdown Flow

### On Startup (`lifespan`)
1. Load wallet from PostgreSQL
2. Load events from PostgreSQL → restore dashboard history
3. Restore strategy state from Redis → price history + risk gates
4. Start all background tasks

### On Shutdown (`lifespan` yield exit)
1. Stop market data bridge
2. Persist strategy state to Redis → price history + risk gates

### Periodic (every 5 min)
1. Persist strategy state to Redis

---

## 🧪 Verification

**Tables created**: ✅ events, llm_traces, strategy_state  
**LanceDB data**: ✅ Persisted via Docker volume (`memory_data:/data`)  
**Health check**: ✅ `{"status":"ok","entries":8}`  
**All services**: ✅ Running

---

## 📋 Remaining Items

| Item | Status | Notes |
|------|--------|-------|
| Telegram bot token | ✅ Fixed | Updated `.env` on AWS |
| Asyncio task error | ⚠️ Partial | Still showing on restart — needs deeper fix |
| First live test | ⏳ Tomorrow | Monitor tomorrow's session |

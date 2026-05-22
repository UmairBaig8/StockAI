# StockAI Critical Issues Report — May 21, 2026

## 📅 Trading Performance by Date

### 2026-05-21 (Today — First Trading Day)

| Metric | Value |
|--------|-------|
| **Session** | 9:17 AM — 10:42 AM IST (1h 25m active) |
| **Total Trades** | 28 (14 closed, 14 open) |
| **Wins** | 7 |
| **Losses** | 7 |
| **Win Rate** | 50% (of closed) |
| **Net P&L** | -0.08% (₹-80 on ₹100k) |
| **Total P&L Points** | -0.08% |
| **Avg Win** | +0.133% |
| **Avg Loss** | -0.144% |
| **Loss/Win Ratio** | 1.08:1 (bad — losses > wins) |
| **Current Equity** | ₹100,000 |
| **Available** | ₹98,198 |
| **Invested** | ₹1,802 (3 positions) |

### Trade Timeline (IST)

| Time | Ticker | Dir | Price | P&L% | Result |
|------|--------|-----|-------|------|--------|
| 09:17 | TATAPOWER | BUY→SELL | ₹413.85→413.10 | -0.18 | ❌ LOSS |
| 09:28 | BAJFINANCE | BUY | ₹925.30 | — | OPEN |
| 09:33 | BAJFINANCE | SELL | ₹923.75 | -0.17 | ❌ LOSS |
| 09:33 | BAJFINANCE | BUY | ₹923.25 | — | OPEN |
| 09:36 | BAJFINANCE | SELL | ₹922.30 | -0.10 | ❌ LOSS |
| 09:38 | BAJFINANCE | BUY | ₹922.70 | — | OPEN |
| 09:42 | BAJFINANCE | SELL | ₹921.15 | -0.17 | ❌ LOSS |
| 09:43 | RELIANCE | BUY | ₹1356.50 | — | OPEN |
| 09:44 | RELIANCE | SELL | ₹1357.90 | +0.10 | ✅ WIN |
| 09:48 | BAJFINANCE | BUY | ₹920.65 | — | OPEN |
| 09:53 | HAL | BUY | ₹4391.80 | — | OPEN |
| 09:54 | HAL | SELL | ₹4401.10 | +0.21 | ✅ WIN |
| 09:54 | BAJFINANCE | SELL | ₹921.95 | +0.14 | ✅ WIN |
| 09:58 | RELIANCE | BUY | ₹1357.30 | — | OPEN |
| 10:00 | RELIANCE | SELL | ₹1355.60 | -0.13 | ❌ LOSS |
| 10:03 | INFY | BUY | ₹1190.40 | — | OPEN |
| 10:09 | HAL | BUY | ₹4389.80 | — | OPEN |
| 10:10 | HAL | SELL | ₹4397.40 | +0.17 | ✅ WIN |
| 10:14 | HDFCBANK | BUY | ₹763.20 | — | OPEN |
| 10:17 | INFY | SELL | ₹1189.10 | -0.11 | ❌ LOSS |
| 10:19 | HDFCBANK | SELL | ₹763.65 | +0.06 | ✅ WIN |
| 10:24 | BAJFINANCE | BUY | ₹916.70 | — | OPEN |
| 10:28 | BAJFINANCE | SELL | ₹917.95 | +0.14 | ✅ WIN |
| 10:29 | BAJFINANCE | BUY | ₹917.60 | — | OPEN |
| 10:34 | BAJFINANCE | SELL | ₹916.25 | -0.15 | ❌ LOSS |
| 10:34 | WIPRO | BUY | ₹197.65 | — | OPEN |
| 10:42 | WIPRO | SELL | ₹197.86 | +0.11 | ✅ WIN |

### Ticker Performance

| Ticker | Trades | W | L | Total P&L% | Verdict |
|--------|--------|---|---|------------|---------|
| HAL | 4 | 2 | 0 | +0.38% | ✅ Best performer |
| WIPRO | 2 | 1 | 0 | +0.11% | ✅ |
| HDFCBANK | 2 | 1 | 0 | +0.06% | ✅ |
| RELIANCE | 4 | 1 | 1 | -0.03% | ⚠️ Breakeven |
| INFY | 2 | 0 | 1 | -0.11% | ❌ |
| TATAPOWER | 2 | 0 | 1 | -0.18% | ❌ |
| **BAJFINANCE** | **12** | **2** | **4** | **-0.31%** | 🔴 **WORST** |

---

## 🔴 Critical Issues

### 1. BAJFINANCE Overtrading (CRITICAL)
- **12 trades** on single ticker (43% of all trades)
- **4 consecutive losses** in first 15 minutes (09:28–09:42)
- **No circuit breaker** — strategy kept re-entering same losing ticker
- Lost -0.31% (3.9x of total portfolio loss)
- **Root cause**: No per-ticker loss limit, no consecutive loss cooldown per ticker

### 2. No LLM/AI Pre-Trade Checks Running (CRITICAL)
- **Zero LLM API calls** logged during entire session
- Strategy ran on pure technical signals (RSI/MACD/BB)
- All 5 AI guards (advocate, memory, researcher, sentiment, macro) were **skipped**
- Forced trades (`force_trade_sec=300s`) bypass LLM checks by design
- **Root cause**: Every trade was a "forced best pick" which only runs memory + sentiment, not full 5-guard pipeline

### 3. Loss/Win Ratio Unfavorable (HIGH)
- Avg loss: -0.144% vs Avg win: +0.133%
- **Losing more per trade than winning** — mathematically unsustainable
- Even at 50% win rate, portfolio will slowly bleed
- **Root cause**: Stop loss too tight (0.5%) vs take profit (2.0%) — exits losses quickly but rarely hits TP

### 4. Telegram Notifications Broken (MEDIUM)
- API 401 Unauthorized on every startup
- No daily P&L reports, no 2FA prompts, no trade alerts
- **Root cause**: Bot token expired or revoked

### 5. Asyncio Task Errors (LOW)
- `RuntimeError: aclose(): asynchronous generator is already running`
- Non-critical but pollutes logs
- **Root cause**: WebSocket disconnect race condition in trade result listener

### 6. Engine Market Feed Connection Failed (LOW)
- `WebSocket connect error: Connection refused` on startup
- Engine retries and connects eventually but initial market data gap
- **Root cause**: Engine starts before Memory WS server is fully ready

---

## 🛠️ Fix Plan

### Fix 1: Per-Ticker Loss Circuit Breaker (P0 — Critical)
**File**: `app/strategy.py`

```python
# Add to __init__:
self._ticker_losses: dict[str, list[float]] = {}  # ticker -> list of loss %
self._ticker_cooldown_until: dict[str, float] = {}  # ticker -> timestamp

# In _listen_trade_results(), after a LOSS:
ticker_losses = self._ticker_losses.get(ticker, [])
ticker_losses.append(pnl_percent)
self._ticker_losses[ticker] = ticker_losses[-5:]  # keep last 5

# Block ticker if 3+ consecutive losses or daily loss > 1%
if len(ticker_losses) >= 3 and all(l < 0 for l in ticker_losses[-3:]):
    self._ticker_cooldown_until[ticker] = now + 1800  # 30 min cooldown
    logger.warning(f"BLOCKED {ticker}: 3 consecutive losses, cooldown 30min")

# In _pick_best_trade() and signal loop, add check:
if self._ticker_cooldown_until.get(ticker, 0) > now:
    continue  # skip ticker in cooldown
```

### Fix 2: Enable Full LLM Pre-Trade Checks (P0 — Critical)
**File**: `app/strategy.py`

```python
# Change forced trade check at line 279:
# FROM: if "forced" in reason or "best" in reason:
# TO: Only skip advocate for forced trades, keep all other guards
if "forced" in reason or "best" in reason:
    results = await asyncio.gather(
        self._check_memory(ticker, rsi),
        self._check_sentiment(ticker),
        self._check_researcher(ticker),  # ADD: researcher check
        return_exceptions=True,
    )
    guards = ["memory", "sentiment", "researcher"]
    exceptions_fatal = {"researcher"}  # ADD: researcher is fatal
```

**Also reduce forced trade frequency**:
```python
# In settings: force_trade_sec from 300s → 600s (5→10 min)
# This reduces overtrading and gives LLM checks time to run
```

### Fix 3: Fix Loss/Win Ratio (P1 — High)
**File**: `app/strategy.py` + Settings

```python
# Option A: Tighten stop loss, loosen take profit
# Current: stop_loss=0.5%, take_profit=2.0%
# New: stop_loss=0.8%, take_profit=1.5%
# Rationale: 0.5% is too tight for NSE noise, gets stopped out on normal volatility

# Option B: Add trailing stop (already partially implemented)
# Ensure trailing stop activates at +0.5% profit, locks in gains

# Option C: Add minimum hold time enforcement
# Current: min_hold_time=300s (5 min) — good, keep this
# Add: Don't exit on BB signal if P&L > -0.3% and held < 10 min
```

### Fix 4: Fix Telegram Bot Token (P2 — Medium)
**File**: `.env` on AWS instance

```bash
# SSH into instance and update:
ssh -i stockai-key.pem ec2-user@52.70.58.6
sudo nano /root/stockai/.env

# Update TELEGRAM_BOT_TOKEN with new token from @BotFather
# Test: curl https://api.telegram.org/bot<NEW_TOKEN>/getMe

# Then restart orchestrator:
sudo docker compose -f /root/stockai/docker-compose.yml restart orchestrator
```

### Fix 5: Fix Asyncio Task Error (P3 — Low)
**File**: `app/strategy.py`

```python
# In _listen_trade_results(), wrap the pubsub listener properly:
async def _listen_trade_results(self):
    try:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("trade:result")
        async for message in pubsub.listen():
            if message["type"] == "message":
                await self._handle_trade_result(message["data"])
    except asyncio.CancelledError:
        pass  # Clean shutdown
    finally:
        try:
            await pubsub.unsubscribe("trade:result")
            await pubsub.close()
        except Exception:
            pass
```

### Fix 6: Fix Engine Startup Race (P3 — Low)
**File**: `docker-compose.yml`

```yaml
# Add healthcheck to memory service:
memory:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
    interval: 5s
    retries: 10
    start_period: 30s
  # Engine already depends on memory, but add condition:
engine:
  depends_on:
    memory:
      condition: service_healthy  # Change from service_started
```

---

## 📋 Priority Order

1. **P0**: Per-ticker circuit breaker (Fix 1) — ✅ **FIXED & DEPLOYED**
2. **P0**: Enable researcher LLM check on forced trades (Fix 2) — ✅ **FIXED & DEPLOYED**
3. **P1**: Adjust stop loss / take profit ratio (Fix 3) — ✅ **FIXED & DEPLOYED**
4. **P2**: Fix Telegram token (Fix 4) — ✅ **FIXED**
5. **P3**: Fix asyncio error (Fix 5) — ✅ **FIXED & DEPLOYED**
6. **P3**: Fix engine startup race (Fix 6) — ✅ **FIXED & DEPLOYED**

## 📦 Persistence Fixes (Commit c99450b)

| Priority | Component | Before | After | Status |
|----------|-----------|--------|-------|--------|
| **P0** | Price history | In-memory only | Redis sorted sets | ✅ Deployed |
| **P1** | Risk gates | In-memory only | Redis hash | ✅ Deployed |
| **P2** | Event store | In-memory only | PostgreSQL `events` | ✅ Deployed |
| **P2** | LLM traces | In-memory only | PostgreSQL `llm_traces` | ✅ Deployed |
| **P2** | Optimizer recs | In-memory only | JSON file | ✅ Deployed |

**Deployment**: Commit `c99450b` pushed to `main`, deployed to AWS `52.70.58.6`  
**Tests**: 10/10 passed  
**Config verified**: `stop_loss=0.8%` confirmed in AWS logs  
**Tables created**: `events`, `llm_traces`, `strategy_state`

---

## 📊 Projected Impact After Fixes

| Metric | Before | After (Projected) |
|--------|--------|-------------------|
| Trades/day | 28 (overtrading) | 12-16 (quality) |
| Win rate | 50% | 55-60% |
| Avg loss | -0.144% | -0.10% |
| Avg win | +0.133% | +0.15% |
| Net daily P&L | -0.08% | +0.15-0.25% |
| LLM checks | 0% | 80-100% |
| Max single-ticker loss | -0.31% | -0.15% (capped) |

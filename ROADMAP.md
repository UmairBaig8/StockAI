# StockAI Roadmap

> **Status:** Paper trading live on AWS · Auto start/stop scheduled · SEBI compliant

## Already Done

- [x] Multi-agent pipeline (Strategy, Critic, Devil's Advocate, Researcher, Sentiment, Macro)
- [x] Rust execution engine with 2FA gate + SEBI rate limiter
- [x] Go orchestrator with Redis pub/sub + Telegram 2FA relay
- [x] LanceDB evolution memory + audit trail (persistent)
- [x] LLM-powered ticker discovery (auto, hourly during market hours)
- [x] Best-opportunity selection with momentum/activity filters
- [x] Real P&L from live market prices between entry and exit
- [x] Market-hours aware (09:15–15:30 IST, Mon–Fri)
- [x] Responsive WCAG 2 dashboard + settings UI
- [x] All strategy params hot-reloadable via UI
- [x] Docker Compose + AWS EC2 one-command deploy
- [x] AWS auto start/stop (Lambda + EventBridge, Mon-Fri 9 AM - 3:30 PM IST)
- [x] Elastic IP (static, never changes)
- [x] EBS snapshots daily with 30-day retention (SEBI audit)
- [x] AI agent skills (opencode automation for dev workflows)

---

## Quick Wins (hours)

### 1. Real News Scraper
Scrape NSE/BSE news from RSS feeds (Moneycontrol, Economic Times, NSE announcements). Feed into researcher LLM for real-time sentiment instead of stale training data.

- [x] Moneycontrol RSS scraper
- [x] NSE corporate announcements feed
- [x] Extract ticker names from headlines
- [x] Feed into researcher agent for enriched context
- [x] Auto-refresh every 15 min

### 2. Telegram Trade Alerts
Send instant Telegram message on every trade execution with direction, price, quantity, and reason.

- [x] BUY/SELL alerts with emoji indicators
- [x] P&L summary on position close
- [x] Postmortem summary on losses

### 3. Trailing Stop-Loss
Replace fixed -3% stop with dynamic trailing stop that locks in profits as price rises.

- [x] Trail stop at `max(entry - 3%, price - 2%)` — never widens
- [x] Breakeven shift: once +2% profit, move stop to entry
- [x] Lock-in: once +5% profit, trail at current -3%

### 4. Daily P&L Report
Auto-generate and send to Telegram at 15:30 IST summarizing the day.

- [x] Total trades, wins, losses, win rate
- [x] Net P&L (₹ and %)
- [x] Best/worst trade
- [x] Evolution rules learned today
- [x] Auto-sent at market close

---

## Medium Effort (days)

### 5. PostgreSQL Persistence
Replace in-memory wallet + events with PostgreSQL. Survives restarts. Queryable trade history.

- [ ] Wallet state persisted
- [ ] Full trade history with filters
- [ ] Analytics queries (Sharpe, drawdown, monthly returns)

### 6. Multi-Timeframe Confirmation
Confirm RSI signals across 1m, 5m, 15m before entry. Reduces false signals.

- [ ] Track multiple timeframe price feeds
- [ ] Signal only when all timeframes agree

### 7. MACD + Bollinger Bands
Add second/third indicator layers for confirmation beyond RSI alone.

- [ ] MACD histogram calculation
- [ ] Bollinger Band width for volatility filter
- [ ] Signal quality scoring across all indicators

### 8. Market Regime Detection
Detect whether market is trending, ranging, or volatile. Switch strategy per regime.

- [ ] ADX for trend strength
- [ ] ATR for volatility measurement
- [ ] Regime-based parameter adjustment

---

## Big Lifts (weeks)

### 9. Backtesting Engine
Run strategy on 2 years of historical NSE data. Measure Sharpe ratio, max drawdown, win rate before live trading.

- [ ] Historical yfinance data loader
- [ ] Simulation engine with realistic fills
- [ ] Performance metrics (Sharpe, Sortino, Calmar)
- [ ] Parameter optimization

### 10. Real Broker Integration
Connect to Zerodha Kite / Upstox / Angel One. Replace mock broker with real execution.

- [ ] Broker adapter pattern (Kite, Upstox, SmartAPI)
- [ ] Real order placement + position sync
- [ ] Broker-side 2FA integration
- [ ] Live P&L from actual fills

### 11. Options Flow Scanner
Track unusual options activity as leading indicator for stock direction.

- [ ] NSE options chain scraper
- [ ] PCR (Put-Call Ratio) tracking
- [ ] Unusual volume detection

### 12. AI Strategy Optimization
Use LLM to analyze weekly performance and suggest parameter adjustments.

- [ ] Weekly strategy review report
- [ ] Parameter suggestion based on recent performance
- [ ] A/B strategy testing (run two param sets)

---

## Nice to Have

- Dark/light theme toggle
- Export trade history to CSV
- Webhook notifications (Slack, Discord)
- Mobile PWA (install as app)
- NIFTY/SENSEX index overlay on dashboard
- Correlation matrix between held positions
- Tax-loss harvesting (for real trading)

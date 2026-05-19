
## 2026-05-19 — Production Hardening Session

[Root Cause] Zero-profit death loop: BB oversold BUY → 2min later BB overbought SELL at identical price. Engine's orphaned-sell fallback computed (price-price)/price=0. Optimizer crashed on dict-vs-Settings type mismatch.

[Surgical Fix] 8 files changed across 3 languages:
- `app/strategy.py`: min_hold_time(300s) gate on BB exits + min_price_delta(0.1%) + volume_z_score filter + rsi_oversold 55→40 + stop_loss 3%→0.5% + daily loss limit(2%) + consecutive loss cooldown(3 losses→10min) + background trade:result listener + short_enabled flag
- `app/config.py`: Added min_hold_time, min_price_delta_pct, daily_loss_limit_pct, postmortem_min_loss_pct, short_enabled
- `execution/src/main.rs`: Orphaned SELL → REJECTED status, no bogus P&L published
- `app/router.py`: Optimizer injection fixed (direct get_settings() instead of Depends)
- `app/optimizer.py`: Dict fallback for robustness
- `app/devils_advocate.py`: Production prompt (BLOCK >60 risk_score, default BLOCK)
- `cmd/orchestrator/main.go`: Postmortem threshold 0.1%+, fixed hardcoded strategy_intent, REJECTED status handling
- `internal/scheduler/scheduler.go`: lastRun map prevents double-fire within same minute

[Gotchas to Avoid]
- Short selling (short_enabled=False) uses SELL direction; when enabled, Rust engine must distinguish SHORT-entry from SELL-exit
- Strategy's _listen_trade_results creates a separate Redis connection; connection leaks could occur on rapid reconnect failures
- Daily loss limit uses wallet.total_equity — make sure wallet is correctly tracking realized P&L
- Postmortem threshold 0.1% should match postmortem_min_loss_pct in config

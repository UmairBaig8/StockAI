import asyncpg
import logging
import os
import json
from datetime import datetime, timezone, date

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://stockai:stockai@localhost:5432/stockai")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        await _migrate()
        logger.info("PostgreSQL connected")
    return _pool


async def _migrate():
    pool = _pool
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                id SERIAL PRIMARY KEY,
                initial_capital DOUBLE PRECISION NOT NULL DEFAULT 100000,
                available DOUBLE PRECISION NOT NULL DEFAULT 100000,
                invested DOUBLE PRECISION NOT NULL DEFAULT 0,
                realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                ticker TEXT PRIMARY KEY,
                qty INTEGER NOT NULL,
                avg_price DOUBLE PRECISION NOT NULL,
                side TEXT NOT NULL DEFAULT 'LONG',
                opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                ticker TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL,
                exit_price DOUBLE PRECISION NOT NULL DEFAULT 0,
                pnl_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'OPEN',
                reason TEXT DEFAULT '',
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                msg TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                ticker TEXT DEFAULT '',
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_traces (
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
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_traces_timestamp ON llm_traces(timestamp DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        # Ensure wallet has a row
        await conn.execute("""
            INSERT INTO wallet (id, initial_capital, available)
            VALUES (1, 100000, 100000)
            ON CONFLICT (id) DO NOTHING
        """)
        logger.info("Database migrated")


# ── Wallet persistence ──

async def load_wallet() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        w = await conn.fetchrow("SELECT * FROM wallet WHERE id = 1")
        positions = await conn.fetch("SELECT * FROM positions")
        return {
            "initial_capital": w["initial_capital"] if w else 100000.0,
            "available": w["available"] if w else 100000.0,
            "invested": w["invested"] if w else 0.0,
            "realized_pnl": w["realized_pnl"] if w else 0.0,
            "positions": {
                p["ticker"]: {
                    "ticker": p["ticker"],
                    "qty": p["qty"],
                    "avg_price": p["avg_price"],
                    "side": p["side"],
                }
                for p in positions
            },
        }


async def save_wallet(initial_capital: float, available: float, invested: float, realized_pnl: float, positions: dict):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE wallet SET initial_capital=$1, available=$2, invested=$3, realized_pnl=$4, updated_at=NOW()
            WHERE id = 1
        """, initial_capital, available, invested, realized_pnl)
        await conn.execute("DELETE FROM positions")
        for ticker, pos in positions.items():
            await conn.execute("""
                INSERT INTO positions (ticker, qty, avg_price, side)
                VALUES ($1, $2, $3, $4)
            """, ticker, pos.get("qty", 0), pos.get("avg_price", 0), pos.get("side", "LONG"))


# ── Trade history ──

async def log_trade(ticker: str, direction: str, qty: int, entry_price: float,
                    exit_price: float, pnl_percent: float, status: str, reason: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO trades (ticker, direction, quantity, entry_price, exit_price, pnl_percent, status, reason)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, ticker, direction, qty, entry_price, exit_price, pnl_percent, status, reason)


async def get_trades(limit: int = 50, ticker: str = "") -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if ticker:
            rows = await conn.fetch(
                "SELECT * FROM trades WHERE ticker = $1 ORDER BY timestamp DESC LIMIT $2",
                ticker.upper(), limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT $1", limit
            )
        return [
            {
                "time": r["timestamp"].isoformat() if r["timestamp"] else "",
                "ticker": r["ticker"],
                "dir": r["direction"],
                "qty": r["quantity"],
                "entry_price": r["entry_price"],
                "exit_price": r["exit_price"],
                "pnl": r["pnl_percent"],
                "status": r["status"],
            }
            for r in rows
        ]


async def get_summary(ticker: str = "") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "WHERE ticker = $1" if ticker else ""
        args = [ticker.upper()] if ticker else []
        row = await conn.fetchrow(
            f"SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE pnl_percent > 0) as wins, "
            f"COUNT(*) FILTER (WHERE pnl_percent < 0) as losses, "
            f"COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl "
            f"FROM trades {where}",
            *args,
        )
        total = row["total"]
        wins = row["wins"]
        losses = row["losses"]
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "pnl": float(row["total_pnl"]),
        }


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Daily report ──

async def get_daily_summaries(days: int = 30) -> list[dict]:
    """Group trades by IST date, return daily performance summaries."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                DATE(timestamp AT TIME ZONE 'Asia/Kolkata') as trade_date,
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE pnl_percent > 0) as wins,
                COUNT(*) FILTER (WHERE pnl_percent < 0) as losses,
                COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl,
                COALESCE(SUM(entry_price * quantity), 0) as total_volume,
                MAX(pnl_percent) as best_pnl,
                MIN(pnl_percent) as worst_pnl,
                COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent > 0), 0) as avg_win,
                COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent < 0), 0) as avg_loss,
                STRING_AGG(DISTINCT ticker, ',' ORDER BY ticker) as tickers_traded
            FROM trades
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT $1
        """, days)
        result = []
        for r in rows:
            total = r["total_trades"]
            wins = r["wins"]
            losses = r["losses"]
            profit_factor = abs(0) if losses == 0 else (
                abs(float(r["total_pnl"])) if losses == 0 else 0
            )
            # Profit factor = gross_profit / gross_loss
            gross_profit_row = await conn.fetchrow(
                "SELECT COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) FROM trades "
                "WHERE DATE(timestamp AT TIME ZONE 'Asia/Kolkata') = $1 AND pnl_percent > 0",
                r["trade_date"],
            )
            gross_loss_row = await conn.fetchrow(
                "SELECT COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) FROM trades "
                "WHERE DATE(timestamp AT TIME ZONE 'Asia/Kolkata') = $1 AND pnl_percent < 0",
                r["trade_date"],
            )
            gross_profit = float(gross_profit_row[0]) if gross_profit_row else 0
            gross_loss = float(gross_loss_row[0]) if gross_loss_row else 0
            pf = abs(gross_profit / gross_loss) if gross_loss != 0 else (999 if gross_profit > 0 else 0)

            result.append({
                "date": str(r["trade_date"]),
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
                "pnl": round(float(r["total_pnl"]), 2),
                "volume": round(float(r["total_volume"]), 2),
                "best_pnl": round(float(r["best_pnl"]), 2),
                "worst_pnl": round(float(r["worst_pnl"]), 2),
                "avg_win": round(float(r["avg_win"]), 2),
                "avg_loss": round(float(r["avg_loss"]), 2),
                "profit_factor": round(pf, 2),
                "tickers": r["tickers_traded"] or "",
            })
        return result


async def get_daily_equity_curve(days: int = 30) -> list[dict]:
    """Cumulative P&L by day for equity curve chart."""
    summaries = await get_daily_summaries(days)
    summaries.reverse()  # chronological order
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    curve = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        w = await conn.fetchrow("SELECT initial_capital FROM wallet WHERE id = 1")
        initial = float(w["initial_capital"]) if w else 100000.0
    for s in summaries:
        cumulative += s["pnl"]
        equity = initial + cumulative
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd
        curve.append({
            "date": s["date"],
            "daily_pnl": s["pnl"],
            "cumulative_pnl": round(cumulative, 2),
            "equity": round(equity, 2),
            "drawdown_pct": round(dd, 2),
        })
    return curve


async def get_ticker_stats(days: int = 30) -> list[dict]:
    """Per-ticker performance over N days."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ticker,
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE pnl_percent > 0) as wins,
                COUNT(*) FILTER (WHERE pnl_percent < 0) as losses,
                COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl,
                ROUND(COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent > 0), 0)::numeric, 2) as avg_win,
                ROUND(COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent < 0), 0)::numeric, 2) as avg_loss,
                ROUND(MAX(pnl_percent)::numeric, 2) as best_pnl,
                ROUND(MIN(pnl_percent)::numeric, 2) as worst_pnl,
                COALESCE(SUM(entry_price * quantity), 0) as volume
            FROM trades
            WHERE timestamp >= NOW() - ($1 || ' days')::INTERVAL
            GROUP BY ticker
            ORDER BY total_pnl DESC
        """, str(days))
        result = []
        for r in rows:
            total = r["total_trades"]
            wins = r["wins"]
            result.append({
                "ticker": r["ticker"],
                "total_trades": total,
                "wins": wins,
                "losses": r["losses"],
                "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
                "pnl": round(float(r["total_pnl"]), 2),
                "avg_win": float(r["avg_win"]),
                "avg_loss": float(r["avg_loss"]),
                "best_pnl": float(r["best_pnl"]),
                "worst_pnl": float(r["worst_pnl"]),
                "volume": round(float(r["volume"]), 2),
            })
        return result


async def get_hourly_stats(days: int = 30) -> list[dict]:
    """P&L by hour of day (IST) for timing analysis."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Asia/Kolkata')::int as hour,
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE pnl_percent > 0) as wins,
                COUNT(*) FILTER (WHERE pnl_percent < 0) as losses,
                COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl,
                COALESCE(SUM(entry_price * quantity), 0) as volume
            FROM trades
            WHERE timestamp >= NOW() - ($1 || ' days')::INTERVAL
            GROUP BY hour
            ORDER BY hour
        """, str(days))
        return [
            {
                "hour": r["hour"],
                "label": f"{r['hour']:02d}:00",
                "total_trades": r["total_trades"],
                "wins": r["wins"],
                "losses": r["losses"],
                "pnl": round(float(r["total_pnl"]), 2),
                "volume": round(float(r["volume"]), 2),
            }
            for r in rows
        ]


async def get_strategy_stats(days: int = 30) -> list[dict]:
    """Performance by strategy signal type (parsed from reason field)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                reason,
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE pnl_percent > 0) as wins,
                COUNT(*) FILTER (WHERE pnl_percent < 0) as losses,
                COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl
            FROM trades
            WHERE timestamp >= NOW() - ($1 || ' days')::INTERVAL AND reason != ''
            GROUP BY reason
            ORDER BY total_pnl DESC
        """, str(days))
        result = []
        for r in rows:
            total = r["total_trades"]
            wins = r["wins"]
            reason = r["reason"].strip()
            # Categorize strategy type
            if "MTF" in reason or "MACD" in reason:
                cat = "MTF RSI + MACD"
            elif "BB" in reason or "bounce" in reason or "overbought" in reason:
                cat = "Bollinger Bands"
            elif "Best opportunity" in reason or "best pick" in reason:
                cat = "Forced (Best Pick)"
            elif "Rotating" in reason or "weakest" in reason:
                cat = "Forced (Rotate)"
            elif "Take profit" in reason:
                cat = "Take Profit"
            elif "Stop loss" in reason:
                cat = "Stop Loss"
            elif "Trailing" in reason:
                cat = "Trailing Stop"
            else:
                cat = "Other"
            result.append({
                "strategy": cat,
                "reason": reason,
                "total_trades": total,
                "wins": wins,
                "losses": r["losses"],
                "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
                "pnl": round(float(r["total_pnl"]), 2),
            })
        return result


async def get_day_detail(date_str: str) -> dict:
    """Full breakdown for a specific day: trades, tickers, hourly, strategies."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        target_date = date.fromisoformat(date_str) if isinstance(date_str, str) else date_str
        rows = await conn.fetch("""
            SELECT
                ticker, direction, quantity, entry_price, exit_price,
                pnl_percent, status, reason,
                EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Asia/Kolkata')::int as hour,
                EXTRACT(MINUTE FROM timestamp AT TIME ZONE 'Asia/Kolkata')::int as minute,
                timestamp AT TIME ZONE 'Asia/Kolkata' as ist_time
            FROM trades
            WHERE DATE(timestamp AT TIME ZONE 'Asia/Kolkata') = $1
            ORDER BY timestamp
        """, target_date)
        if not rows:
            return {"date": str(target_date), "trades": [], "summary": None}

        trades = []
        for r in rows:
            trades.append({
                "ticker": r["ticker"],
                "direction": r["direction"],
                "qty": r["quantity"],
                "entry_price": round(float(r["entry_price"]), 2),
                "exit_price": round(float(r["exit_price"]), 2),
                "pnl_percent": round(float(r["pnl_percent"]), 2),
                "status": r["status"],
                "reason": r["reason"] or "",
                "time": r["ist_time"].strftime("%H:%M") if r["ist_time"] else "",
            })

        total = len(trades)
        wins = sum(1 for t in trades if t["pnl_percent"] > 0)
        losses = sum(1 for t in trades if t["pnl_percent"] < 0)
        gross_profit = sum(t["pnl_percent"] * t["entry_price"] * t["qty"] / 100 for t in trades if t["pnl_percent"] > 0)
        gross_loss = sum(abs(t["pnl_percent"] * t["entry_price"] * t["qty"] / 100) for t in trades if t["pnl_percent"] < 0)
        pf = abs(gross_profit / gross_loss) if gross_loss != 0 else (999 if gross_profit > 0 else 0)

        summary = {
            "date": str(target_date),
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total * 100) if total > 0 else 0, 1),
            "pnl": round(sum(t["pnl_percent"] * t["entry_price"] * t["qty"] / 100 for t in trades), 2),
            "profit_factor": round(pf, 2),
            "best_trade": max(trades, key=lambda t: t["pnl_percent"]) if trades else None,
            "worst_trade": min(trades, key=lambda t: t["pnl_percent"]) if trades else None,
        }

        # Per-ticker for this day
        ticker_map = {}
        for t in trades:
            k = t["ticker"]
            if k not in ticker_map:
                ticker_map[k] = {"ticker": k, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            ticker_map[k]["trades"] += 1
            if t["pnl_percent"] > 0:
                ticker_map[k]["wins"] += 1
            elif t["pnl_percent"] < 0:
                ticker_map[k]["losses"] += 1
            ticker_map[k]["pnl"] += t["pnl_percent"] * t["entry_price"] * t["qty"] / 100
        tickers = sorted(ticker_map.values(), key=lambda x: x["pnl"], reverse=True)

        # Per-hour for this day
        hour_map = {}
        for t in trades:
            k = t["time"][:2] + ":00"
            if k not in hour_map:
                hour_map[k] = {"hour": k, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            hour_map[k]["trades"] += 1
            if t["pnl_percent"] > 0:
                hour_map[k]["wins"] += 1
            elif t["pnl_percent"] < 0:
                hour_map[k]["losses"] += 1
            hour_map[k]["pnl"] += t["pnl_percent"] * t["entry_price"] * t["qty"] / 100
        hourly = sorted(hour_map.values(), key=lambda x: x["hour"])

        # Per-strategy for this day
        strat_map = {}
        for t in trades:
            reason = t["reason"]
            if "MTF" in reason or "MACD" in reason:
                cat = "MTF RSI + MACD"
            elif "BB" in reason or "bounce" in reason or "overbought" in reason:
                cat = "Bollinger Bands"
            elif "Best opportunity" in reason or "best pick" in reason:
                cat = "Forced (Best Pick)"
            elif "Rotating" in reason or "weakest" in reason:
                cat = "Forced (Rotate)"
            elif "Take profit" in reason:
                cat = "Take Profit"
            elif "Stop loss" in reason:
                cat = "Stop Loss"
            elif "Trailing" in reason:
                cat = "Trailing Stop"
            else:
                cat = "Other"
            if cat not in strat_map:
                strat_map[cat] = {"strategy": cat, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "signals": []}
            strat_map[cat]["trades"] += 1
            if t["pnl_percent"] > 0:
                strat_map[cat]["wins"] += 1
            elif t["pnl_percent"] < 0:
                strat_map[cat]["losses"] += 1
            strat_map[cat]["pnl"] += t["pnl_percent"] * t["entry_price"] * t["qty"] / 100
            strat_map[cat]["signals"].append(reason)
        strategies = sorted(strat_map.values(), key=lambda x: x["pnl"], reverse=True)

        return {
            "date": str(target_date),
            "trades": trades,
            "summary": summary,
            "tickers": tickers,
            "hourly": hourly,
            "strategies": strategies,
        }


async def get_weekly_summary(weeks: int = 12) -> list[dict]:
    """Weekly aggregated performance."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                DATE_TRUNC('week', timestamp AT TIME ZONE 'Asia/Kolkata') as week_start,
                COUNT(*) as total_trades,
                COUNT(*) FILTER (WHERE pnl_percent > 0) as wins,
                COUNT(*) FILTER (WHERE pnl_percent < 0) as losses,
                COALESCE(SUM(pnl_percent * entry_price * quantity / 100), 0) as total_pnl,
                ROUND(COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent > 0), 0)::numeric, 2) as avg_win,
                ROUND(COALESCE(AVG(pnl_percent) FILTER (WHERE pnl_percent < 0), 0)::numeric, 2) as avg_loss
            FROM trades
            WHERE timestamp >= NOW() - ($1 || ' weeks')::INTERVAL
            GROUP BY week_start
            ORDER BY week_start DESC
        """, str(weeks))
        return [
            {
                "week": str(r["week_start"])[:10],
                "total_trades": r["total_trades"],
                "wins": r["wins"],
                "losses": r["losses"],
                "win_rate": round((r["wins"] / r["total_trades"] * 100) if r["total_trades"] > 0 else 0, 1),
                "pnl": round(float(r["total_pnl"]), 2),
                "avg_win": float(r["avg_win"]),
                "avg_loss": float(r["avg_loss"]),
            }
            for r in rows
        ]


# ── Event store persistence ──

async def save_event(msg: str, level: str = "info", ticker: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO events (msg, level, ticker) VALUES ($1, $2, $3)",
            msg, level, ticker,
        )


async def load_events(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT msg, level, ticker, timestamp FROM events ORDER BY timestamp DESC LIMIT $1",
            limit,
        )
        return [
            {"msg": r["msg"], "level": r["level"], "ticker": r["ticker"] or "", "timestamp": r["timestamp"]}
            for r in rows
        ]


async def save_postmortem(rule: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO events (msg, level, ticker) VALUES ($1, 'postmortem', '')",
            f"RULE: {rule}",
        )


async def load_recent_rules(limit: int = 10) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT msg FROM events WHERE level = 'postmortem' ORDER BY timestamp DESC LIMIT $1",
            limit,
        )
        return [r["msg"].replace("RULE: ", "") for r in rows]


# ── LLM trace persistence ──

async def save_llm_trace(trace: dict):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO llm_traces
               (agent, provider, model, prompt_tokens_est, response_tokens_est,
                latency_ms, success, error, prompt, response)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            trace["agent"], trace["provider"], trace["model"],
            trace["prompt_tokens_est"], trace["response_tokens_est"],
            trace["latency_ms"], trace["success"], trace.get("error", ""),
            trace.get("prompt", ""), trace.get("response", ""),
        )


async def load_llm_traces(limit: int = 200) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT agent, provider, model, prompt_tokens_est, response_tokens_est,
                      latency_ms, success, error, prompt, response, timestamp
               FROM llm_traces ORDER BY timestamp DESC LIMIT $1""",
            limit,
        )
        return [
            {
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else "",
                "agent": r["agent"],
                "provider": r["provider"],
                "model": r["model"],
                "prompt_tokens_est": r["prompt_tokens_est"],
                "response_tokens_est": r["response_tokens_est"],
                "latency_ms": r["latency_ms"],
                "success": r["success"],
                "error": r["error"] or "",
                "prompt": r["prompt"] or "",
                "response": r["response"] or "",
            }
            for r in rows
        ]


# ── Strategy state persistence ──

async def save_strategy_state(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO strategy_state (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()",
            key, value,
        )


async def load_strategy_state() -> dict[str, str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM strategy_state")
        return {r["key"]: r["value"] for r in rows}

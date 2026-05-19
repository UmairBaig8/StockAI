import asyncpg
import logging
import os
import json
from datetime import datetime, timezone

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

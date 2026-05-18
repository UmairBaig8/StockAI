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

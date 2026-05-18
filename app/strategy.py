import asyncio
import json
import logging
import os
from collections import deque

import httpx
from .wallet import wallet as wallet_instance

logger = logging.getLogger(__name__)


class StrategyAgent:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.price_history: dict[str, deque[float]] = {}
        self.last_signal: dict[str, float] = {}
        self.signal_cooldown = 120  # 2 min cooldown (relaxed for paper trading)
        self.max_position_pct = 5.0
        self.max_positions = 3
        self.take_profit_pct = 2.0
        self.stop_loss_pct = 3.0
        self.rsi_period = 14
        self.rsi_oversold = 55  # Relaxed for paper trading — generates more signals
        self.rsi_overbought = 70
        self.redis_url = os.getenv("REDIS_ADDR", "redis://redis:6379")
        self.memory_url = os.getenv("MEMORY_URL", "http://memory:8000")
        self._last_forced_trade = 0.0

    def feed_quote(self, quote: dict):
        ticker = quote.get("ticker", "")
        price = quote.get("last_price", 0)
        if not ticker or not price:
            return

        if ticker not in self.price_history:
            self.price_history[ticker] = deque(maxlen=self.rsi_period * 2)

        self.price_history[ticker].append(float(price))

    async def run(self):
        logger.info("Strategy Agent started — scanning market for signals...")
        last_heartbeat = 0

        while True:
            await asyncio.sleep(15)

            try:
                # Heartbeat every 5 min
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 300:
                    tickers = {t: f"n={len(p)}" for t, p in self.price_history.items()}
                    logger.info(f"Strategy heartbeat: wallet=₹{wallet_instance.available:,.0f} positions={len(wallet_instance.positions)} data={tickers}")
                    last_heartbeat = now

            wallets = wallet_instance.snapshot()
            open_count = len(wallets.get("positions", {}))

            had_signal = False

            for ticker, prices in self.price_history.items():
                if len(prices) < self.rsi_period:
                    continue

                current = prices[-1]
                prev = prices[0]

                # Skip if in cooldown
                now = asyncio.get_event_loop().time()
                if ticker in self.last_signal and now - self.last_signal[ticker] < self.signal_cooldown:
                    continue

                change_pct = ((current - prev) / prev) * 100 if prev > 0 else 0
                rsi = self._calc_rsi(list(prices))

                signal = None
                if open_count < self.max_positions and rsi < self.rsi_oversold and change_pct < -0.2:
                    signal = {"direction": "BUY", "reason": f"Oversold RSI={rsi:.0f} change={change_pct:+.2f}%"}
                elif ticker in wallet_instance.positions:
                    pos = wallet_instance.positions[ticker]
                    pos_change = ((current - pos.avg_price) / pos.avg_price) * 100
                    if pos_change >= self.take_profit_pct:
                        signal = {"direction": "SELL", "reason": f"Take profit +{pos_change:+.2f}%"}
                    elif pos_change <= -self.stop_loss_pct:
                        signal = {"direction": "SELL", "reason": f"Stop loss {pos_change:+.2f}%"}

                if not signal:
                    continue

                had_signal = True

                # Size: max 5% of wallet
                notional = wallet_instance.available * (self.max_position_pct / 100)
                qty = max(1, int(notional / current))

                if signal["direction"] == "BUY" and notional > wallet_instance.available:
                    continue
                if signal["direction"] == "SELL" and ticker not in wallet_instance.positions:
                    continue

                # Pre-trade checks
                if signal["direction"] == "BUY":
                    if not await self._check_advocate(ticker, signal["direction"], qty, current, signal["reason"]):
                        logger.info(f"Strategy: {ticker} BUY BLOCKED by advocate")
                        continue
                    if await self._check_memory(ticker, rsi):
                        logger.info(f"Strategy: {ticker} BUY BLOCKED by memory (similar past failure)")
                        continue

                trade = {
                    "ticker": ticker,
                    "exchange": "NSE",
                    "direction": signal["direction"],
                    "quantity": qty,
                    "price": current,
                    "reason": signal["reason"],
                    "timestamp": asyncio.get_event_loop().time(),
                }

                await self._publish_trade(trade)
                self.last_signal[ticker] = now
                logger.info(f"Strategy: {ticker} {signal['direction']} qty={qty} @ {current:.2f} — {signal['reason']}")

            # Paper-trade stress: force one trade every 5 min if no signals fired
            if not had_signal:
                now = asyncio.get_event_loop().time()
                if now - self._last_forced_trade > 300:
                    import random
                    if open_count < self.max_positions:
                        # Force BUY on random ticker
                        tickers = list(self.price_history.keys())
                        if tickers:
                            ticker = random.choice(tickers)
                            prices = list(self.price_history[ticker])
                            if len(prices) >= 2:
                                current = prices[-1]
                                notional = wallet_instance.available * (self.max_position_pct / 100)
                                qty = max(1, int(notional / current))
                                trade = {
                                    "ticker": ticker, "exchange": "NSE", "direction": "BUY",
                                    "quantity": qty, "price": current,
                                    "reason": "Paper-run forced trade (no market signals)",
                                    "timestamp": now,
                                }
                                await self._publish_trade(trade)
                                self._last_forced_trade = now
                                logger.info(f"Strategy: {ticker} BUY (forced) qty={qty} @ {current:.2f} — paper-run stress test")
                    else:
                        # Max positions — force SELL a random held position to free slots
                        held = list(wallet_instance.positions.keys())
                        if held:
                            ticker = random.choice(held)
                            pos = wallet_instance.positions[ticker]
                            prices = list(self.price_history.get(ticker, []))
                            if len(prices) >= 2:
                                current = prices[-1]
                                trade = {
                                    "ticker": ticker, "exchange": "NSE", "direction": "SELL",
                                    "quantity": pos.qty, "price": current,
                                    "reason": f"Paper-run forced exit (max positions, freeing slot)",
                                    "timestamp": now,
                                }
                                await self._publish_trade(trade)
                                self._last_forced_trade = now
                                logger.info(f"Strategy: {ticker} SELL (forced exit) qty={pos.qty} @ {current:.2f} — freeing position slot")

            except Exception as e:
                logger.error(f"Strategy loop error (will retry): {e}", exc_info=True)

    def _calc_rsi(self, prices: list[float]) -> float:
        if len(prices) < 2:
            return 50
        gains = sum(max(prices[i] - prices[i - 1], 0) for i in range(1, len(prices)))
        losses = sum(max(prices[i - 1] - prices[i], 0) for i in range(1, len(prices)))
        avg_gain = gains / len(prices)
        avg_loss = losses / len(prices)
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    async def _check_advocate(self, ticker: str, direction: str, qty: int, price: float, reason: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    f"{self.memory_url}/api/v1/advocate",
                    json={
                        "ticker": ticker,
                        "direction": direction,
                        "quantity": qty,
                        "price": price,
                        "reason": reason,
                        "market_state": {"rsi": self._calc_rsi(list(self.price_history.get(ticker, [])))},
                    },
                )
                data = r.json()
                return data.get("verdict") != "BLOCK"
        except Exception as e:
            logger.warning(f"Advocate check failed for {ticker}: {e}")
            return True  # Allow if advocate unavailable

    async def _check_memory(self, ticker: str, rsi: float) -> bool:
        try:
            prices = list(self.price_history.get(ticker, []))
            n = len(prices)
            price_velocity = ((prices[-1] - prices[-min(5, n)]) / prices[-min(5, n)] * 100) if n >= 5 else 0
            trend_profile = ((prices[-1] - prices[0]) / prices[0] * 100) if n >= 2 else 0
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"{self.memory_url}/api/v1/pretrade",
                    json={
                        "ticker": ticker,
                        "market_state": {
                            "rsi": rsi,
                            "macd_histogram": 0,
                            "volume_z_score": 0,
                            "sector_trend": 0,
                            "price_velocity_5m": round(price_velocity, 2),
                            "trend_profile_1h": round(trend_profile, 2),
                        },
                    },
                )
                data = r.json()
                return data.get("matched", False)
        except Exception:
            return False

    async def _publish_trade(self, trade: dict):
        try:
            import redis.asyncio as redis
            t = trade.copy()
            import datetime
            t["timestamp"] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).isoformat()
            r = redis.Redis.from_url(self.redis_url)
            await r.publish("trade:signal", json.dumps(t))
            await r.aclose()
        except Exception as e:
            logger.error(f"Failed to publish trade: {e}")

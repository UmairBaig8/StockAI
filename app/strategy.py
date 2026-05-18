import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone, timedelta

import httpx
from .wallet import wallet as wallet_instance
from . import settings_store as settings_store

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Hours when auto-discovery and trading are active
DISCOVERY_HOURS = [9, 10, 11, 12, 13, 14]  # IST hours
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


class StrategyAgent:
    def __init__(self, config: dict | None = None):
        self.price_history: dict[str, deque[float]] = {}
        self.last_signal: dict[str, float] = {}
        self._load_config()
        self._last_forced_trade = 0.0
        self._last_discovery_hour = -1
        self._last_discovery_date = ""
        settings_store.on_change(self._on_settings_change)

    def _load_config(self, cfg: dict | None = None):
        if cfg is None:
            cfg = settings_store.current()
        self.signal_cooldown = int(cfg.get("signal_cooldown", 120))
        self.max_position_pct = float(cfg.get("position_size_pct", 5))
        self.max_positions = int(cfg.get("max_positions", 3))
        self.take_profit_pct = float(cfg.get("take_profit_pct", 2.0))
        self.stop_loss_pct = float(cfg.get("stop_loss_pct", 3.0))
        self.rsi_period = int(cfg.get("rsi_period", 14))
        self.rsi_oversold = float(cfg.get("rsi_oversold", 55))
        self.rsi_overbought = float(cfg.get("rsi_overbought", 70))
        self.min_drop_pct = float(cfg.get("min_drop_pct", 0.2))
        self.force_trade_sec = int(cfg.get("force_trade_sec", 300))
        self.redis_url = os.getenv("REDIS_ADDR", "redis://redis:6379")
        self.memory_url = os.getenv("MEMORY_URL", "http://memory:8000")
        logger.info(f"Strategy config loaded: max_pos={self.max_positions} RSI_oversold={self.rsi_oversold} cooldown={self.signal_cooldown}s")

    def _on_settings_change(self, cfg: dict):
        self._load_config(cfg)

    def _ist_now(self) -> datetime:
        return datetime.now(IST)

    def _is_market_open(self) -> bool:
        now = self._ist_now()
        if now.weekday() >= 5:  # Sat=5, Sun=6
            return False
        t = now.hour * 60 + now.minute
        return MARKET_OPEN[0] * 60 + MARKET_OPEN[1] <= t < MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]

    def _trading_day_key(self) -> str:
        return self._ist_now().strftime("%Y-%m-%d")

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

            # Heartbeat every 5 min — also check auto-discovery schedule
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat > 300:
                tickers = {t: f"n={len(p)}" for t, p in self.price_history.items()}
                is_open = self._is_market_open()
                logger.info(f"Strategy heartbeat: wallet=₹{wallet_instance.available:,.0f} positions={len(wallet_instance.positions)} market={'OPEN' if is_open else 'CLOSED'} data={tickers}")
                last_heartbeat = now

                # Auto-discovery at scheduled IST hours (9, 10, 11, 12, 13, 14)
                if is_open:
                    await self._maybe_discover()

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
                if open_count < self.max_positions and rsi < self.rsi_oversold and change_pct < -self.min_drop_pct:
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

            # If no natural signal, pick best opportunity across all tickers
            if not had_signal:
                now = asyncio.get_event_loop().time()
                if self.force_trade_sec > 0 and now - self._last_forced_trade > self.force_trade_sec:
                    await self._pick_best_trade(open_count)

    async def _maybe_discover(self):
        """Auto-discover trending tickers at scheduled IST hours."""
        now = self._ist_now()
        today = self._trading_day_key()
        hour = now.hour
        if hour in DISCOVERY_HOURS and (today != self._last_discovery_date or hour != self._last_discovery_hour):
            self._last_discovery_hour = hour
            self._last_discovery_date = today
            logger.info(f"Auto-discovery triggered at {now.strftime('%H:%M')} IST")
            try:
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post(
                        f"{self.memory_url}/api/v1/tickers/discover",
                        json={"count": 8},
                    )
                    if r.status_code == 200:
                        data = r.json()
                        logger.info(f"Discovered {data.get('added', 0)} new tickers")
            except Exception as e:
                logger.warning(f"Auto-discovery failed: {e}")

    async def _pick_best_trade(self, open_count: int):
        """Pick the highest-scoring opportunity across all tickers."""
        now = asyncio.get_event_loop().time()

        if open_count < self.max_positions:
            # Find best BUY candidate
            best_score, best_ticker, best_price = -999, None, 0.0
            for ticker, prices in self.price_history.items():
                if ticker in wallet_instance.positions:
                    continue
                if len(prices) < self.rsi_period:
                    continue
                score = self._score_ticker(ticker, list(prices))
                if score > best_score:
                    best_score, best_ticker = score, ticker
                    best_price = prices[-1]

            if best_ticker and best_price > 0:
                notional = wallet_instance.available * (self.max_position_pct / 100)
                qty = max(1, int(notional / best_price))
                rsi = self._calc_rsi(list(self.price_history[best_ticker]))
                reason = f"Best opportunity RSI={rsi:.0f} score={best_score:.1f}"
                await self._publish_trade({
                    "ticker": best_ticker, "exchange": "NSE", "direction": "BUY",
                    "quantity": qty, "price": best_price,
                    "reason": reason, "timestamp": now,
                })
                self._last_forced_trade = now
                logger.info(f"Strategy: {best_ticker} BUY (best pick) qty={qty} @ {best_price:.2f} — {reason}")
        else:
            # Max positions — sell the weakest held position
            worst_score, worst_ticker, worst_price = 999, None, 0.0
            for ticker in wallet_instance.positions:
                prices = list(self.price_history.get(ticker, []))
                if len(prices) < 2:
                    continue
                pos = wallet_instance.positions[ticker]
                pnl_pct = ((prices[-1] - pos.avg_price) / pos.avg_price) * 100
                rsi = self._calc_rsi(prices)
                # Score: prefer selling losers (negative P&L) and overbought positions
                score = -pnl_pct + (70 - rsi) * 0.3
                if score < worst_score:
                    worst_score, worst_ticker = score, ticker
                    worst_price = prices[-1]

            if worst_ticker and worst_price > 0:
                pos = wallet_instance.positions[worst_ticker]
                pnl_pct = ((worst_price - pos.avg_price) / pos.avg_price) * 100
                await self._publish_trade({
                    "ticker": worst_ticker, "exchange": "NSE", "direction": "SELL",
                    "quantity": pos.qty, "price": worst_price,
                    "reason": f"Rotating out P&L={pnl_pct:+.2f}% (weakest hold)",
                    "timestamp": now,
                })
                self._last_forced_trade = now
                logger.info(f"Strategy: {worst_ticker} SELL (rotate) qty={pos.qty} @ {worst_price:.2f} — P&L={pnl_pct:+.2f}%")

    def _score_ticker(self, ticker: str, prices: list[float]) -> float:
        """Score a ticker for BUY opportunity. Higher = better. Negative = skip."""
        if len(prices) < self.rsi_period:
            return -999

        rsi = self._calc_rsi(prices)
        current = prices[-1]

        # Price momentum over last 5 candles
        lookback = min(5, len(prices))
        momentum = ((current - prices[-lookback]) / prices[-lookback]) * 100 if prices[-lookback] > 0 else 0

        # Volume proxy: price range (high-low) / price = activity measure
        pmin = min(prices[-min(14, len(prices)):])
        pmax = max(prices[-min(14, len(prices)):])
        activity = ((pmax - pmin) / pmin * 100) if pmin > 0 else 0

        # Score: prefer oversold + positive momentum + active stocks
        score = (self.rsi_oversold - rsi) * 1.5   # RSI below oversold = good
        score += momentum * 2.0                     # momentum is key
        score += activity * 0.5                     # prefer active stocks

        # Filter: skip dead/flat stocks
        if activity < 0.3:
            return -998
        if rsi > self.rsi_overbought:
            return -997  # overbought — don't buy

        return score

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

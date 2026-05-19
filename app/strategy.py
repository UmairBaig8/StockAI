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
        self._highest_price: dict[str, float] = {}  # trailing stop tracker
        self._position_entry_time: dict[str, float] = {}  # min hold time tracker
        self._consecutive_losses = 0
        self._loss_cooldown_until = 0.0
        self._daily_loss = 0.0
        self._daily_loss_date = ""
        settings_store.on_change(self._on_settings_change)

    def _load_config(self, cfg: dict | None = None):
        if cfg is None:
            cfg = settings_store.current()
        self.signal_cooldown = int(cfg.get("signal_cooldown", 300))
        self.max_position_pct = float(cfg.get("position_size_pct", 5))
        self.max_positions = int(cfg.get("max_positions", 3))
        self.take_profit_pct = float(cfg.get("take_profit_pct", 2.0))
        self.stop_loss_pct = float(cfg.get("stop_loss_pct", 0.5))
        self.rsi_period = int(cfg.get("rsi_period", 14))
        self.rsi_oversold = float(cfg.get("rsi_oversold", 40))
        self.rsi_overbought = float(cfg.get("rsi_overbought", 70))
        self.min_drop_pct = float(cfg.get("min_drop_pct", 0.5))
        self.force_trade_sec = int(cfg.get("force_trade_sec", 300))
        self.min_hold_time = int(cfg.get("min_hold_time", 300))
        self.min_price_delta_pct = float(cfg.get("min_price_delta_pct", 0.1))
        self.daily_loss_limit_pct = float(cfg.get("daily_loss_limit_pct", 2.0))
        self.short_enabled = bool(cfg.get("short_enabled", False))
        self.redis_url = os.getenv("REDIS_ADDR", "redis://redis:6379")
        self.memory_url = os.getenv("MEMORY_URL", "http://memory:8000")
        logger.info(f"Strategy config loaded: max_pos={self.max_positions} RSI_oversold={self.rsi_oversold} cooldown={self.signal_cooldown}s stop_loss={self.stop_loss_pct}%")

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
            self.price_history[ticker] = deque(maxlen=200)  # ~7 min raw + resample room

        self.price_history[ticker].append(float(price))

    async def run(self):
        logger.info("Strategy Agent started — scanning market for signals...")
        last_heartbeat = 0

        # Background: listen for trade results to track consecutive losses
        asyncio.create_task(self._listen_trade_results())

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

            # Daily loss limit check
            today_key = self._trading_day_key()
            if today_key != self._daily_loss_date:
                self._daily_loss = 0.0
                self._daily_loss_date = today_key
                self._daily_start_equity = wallet_instance.total_equity

            current_equity = wallet_instance.total_equity
            if hasattr(self, '_daily_start_equity') and current_equity > 0:
                daily_pnl = current_equity - self._daily_start_equity
                if daily_pnl < 0 and abs(daily_pnl) / self._daily_start_equity * 100 >= self.daily_loss_limit_pct:
                    logger.warning(f"DAILY LOSS LIMIT HIT: {daily_pnl/self._daily_start_equity*100:.2f}% — halting trades")
                    await asyncio.sleep(60)
                    continue

            # Consecutive loss cooldown
            loop_now = asyncio.get_event_loop().time()
            if self._loss_cooldown_until > 0 and loop_now < self._loss_cooldown_until:
                pass  # skip signal generation during cooldown, but still allow exits
            else:
                self._loss_cooldown_until = 0.0  # reset expired cooldown

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

                # BUY signals (only eval during non-loss-cooldown)
                if self._loss_cooldown_until == 0.0:
                    if open_count < self.max_positions and rsi < self.rsi_oversold and change_pct < -self.min_drop_pct:
                        # Multi-timeframe confirmation: 1m, 5m, 15m RSI all oversold
                        if self._confirm_multiframe_rsi(list(prices)):
                            if self._check_macd_bullish(list(prices)):
                                signal = {"direction": "BUY", "reason": f"MTF RSI={rsi:.0f} MACD bullish change={change_pct:+.2f}%"}
                        elif self._check_bb_oversold(list(prices), current) and self._confirm_volume(list(prices)):
                            signal = {"direction": "BUY", "reason": f"BB oversold RSI={rsi:.0f} bounce at {current:.2f}"}

                    # SHORT signals (if enabled)
                    if not signal and self.short_enabled and open_count < self.max_positions and rsi > self.rsi_overbought and change_pct > self.min_drop_pct:
                        if self._check_bb_overbought(list(prices), current) and self._confirm_volume(list(prices)):
                            signal = {"direction": "SELL", "reason": f"BB overbought RSI={rsi:.0f} short at {current:.2f}"}

                # SELL exits for open positions
                if not signal and ticker in wallet_instance.positions:
                    pos = wallet_instance.positions[ticker]
                    pos_change = ((current - pos.avg_price) / pos.avg_price) * 100
                    if pos_change >= self.take_profit_pct:
                        signal = {"direction": "SELL", "reason": f"Take profit +{pos_change:+.2f}%"}
                    elif pos_change <= -self.stop_loss_pct:
                        signal = {"direction": "SELL", "reason": f"Stop loss {pos_change:+.2f}%"}
                    elif self._check_trailing_stop(ticker, current, pos.avg_price):
                        signal = {"direction": "SELL", "reason": f"Trailing stop triggered at {current:.2f}"}
                    elif self._check_bb_overbought(list(prices), current):
                        entry_time = self._position_entry_time.get(ticker, 0)
                        hold_sec = now - entry_time if entry_time > 0 else 999
                        delta_pct = abs(pos_change)
                        if hold_sec < self.min_hold_time:
                            continue  # skip BB exit within min hold time
                        if delta_pct < self.min_price_delta_pct:
                            continue  # skip BB exit with no real price movement
                        signal = {"direction": "SELL", "reason": f"BB overbought at {current:.2f} (held {hold_sec:.0f}s, chg={pos_change:+.2f}%)"}

                if not signal:
                    continue

                had_signal = True

                # Size: max 5% of wallet
                notional = wallet_instance.available * (self.max_position_pct / 100)
                qty = max(1, int(notional / current))

                if signal["direction"] == "BUY" and notional > wallet_instance.available:
                    continue
                if signal["direction"] == "SELL" and ticker not in wallet_instance.positions:
                    # Only block if this is an EXIT sell (not a short entry)
                    if self.short_enabled and open_count < self.max_positions:
                        pass  # allow short entry
                    else:
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
                if signal["direction"] == "BUY":
                    self._position_entry_time[ticker] = now  # track entry time for min hold
                elif signal["direction"] == "SELL":
                    self._highest_price.pop(ticker, None)  # reset trailing stop tracker
                    self._position_entry_time.pop(ticker, None)
                logger.info(f"Strategy: {ticker} {signal['direction']} qty={qty} @ {current:.2f} — {signal['reason']}")

            # If no natural signal, pick best opportunity across all tickers
            if not had_signal and self._loss_cooldown_until == 0.0:
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

            if best_ticker and best_price > 0 and best_score > -500:
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
        elif self._is_market_open():
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

    # ── Multi-Timeframe RSI ──

    def _confirm_multiframe_rsi(self, prices: list[float]) -> bool:
        """BUY only if 1m, 5m, 15m RSI are all oversold."""
        n = len(prices)
        if n < 30:
            return False
        # 1m: last 14 raw points (~28s)
        rsi_1m = self._calc_rsi(prices[-14:])
        # 5m: sample every 5th point (~2.5 min window)
        m5 = prices[-int(min(14*5, n))::5]
        rsi_5m = self._calc_rsi(m5) if len(m5) >= 5 else 50
        # 15m: sample every 15th point (~7.5 min window)
        m15 = prices[-int(min(14*15, n))::15]
        rsi_15m = self._calc_rsi(m15) if len(m15) >= 5 else 50
        return rsi_1m < self.rsi_oversold and rsi_5m < self.rsi_oversold and rsi_15m < self.rsi_oversold

    # ── MACD ──

    def _ema(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * multiplier + ema
        return ema

    def _calc_macd(self, prices: list[float]) -> tuple[float, float, float]:
        """Returns (macd_line, signal_line, histogram)."""
        if len(prices) < 26:
            return 0, 0, 0
        ema12 = self._ema(prices, 12)
        ema26 = self._ema(prices, 26)
        macd_line = ema12 - ema26
        # Signal: 9-period EMA of recent MACD approximations
        signal = macd_line * 0.9  # simplified for real-time
        hist = macd_line - signal
        return macd_line, signal, hist

    def _check_macd_bullish(self, prices: list[float]) -> bool:
        """MACD histogram turning positive or above signal."""
        _, _, hist = self._calc_macd(prices)
        if len(prices) < 30:
            return hist > 0
        # Check if histogram was negative and is now rising
        _, _, prev_hist = self._calc_macd(prices[:-1])
        return hist > prev_hist or hist > 0

    # ── Bollinger Bands ──

    def _calc_bb(self, prices: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[float, float, float]:
        """Returns (lower, middle, upper)."""
        if len(prices) < period:
            return 0, 0, 0
        window = prices[-period:]
        sma = sum(window) / period
        variance = sum((p - sma) ** 2 for p in window) / period
        std = variance ** 0.5
        return sma - std_mult * std, sma, sma + std_mult * std

    def _check_bb_oversold(self, prices: list[float], current: float) -> bool:
        """Price at or below lower Bollinger Band = oversold bounce opportunity."""
        lower, mid, upper = self._calc_bb(prices)
        if lower <= 0:
            return False
        # Price near or below lower band
        return current <= lower * 1.005 and len(prices) >= 20

    def _check_bb_overbought(self, prices: list[float], current: float) -> bool:
        """Price at or above upper Bollinger Band = overbought signal."""
        lower, mid, upper = self._calc_bb(prices)
        if upper <= 0:
            return False
        return current >= upper * 0.995 and len(prices) >= 20

    def _confirm_volume(self, prices: list[float]) -> bool:
        """Volume proxy: Z-Score of price range > 1.0 to confirm genuine momentum."""
        if len(prices) < 14:
            return False
        ranges = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        recent = ranges[-14:]
        avg_range = sum(recent) / len(recent)
        if avg_range == 0:
            return False
        variance = sum((r - avg_range) ** 2 for r in recent) / len(recent)
        std_range = variance ** 0.5
        if std_range == 0:
            return False
        current_range = ranges[-1]
        z_score = (current_range - avg_range) / std_range
        return z_score > 1.0

    # ── Market Regime Detection (ADX + ATR) ──

    def _calc_adx(self, prices: list[float], highs: list[float] | None = None, lows: list[float] | None = None, period: int = 14) -> float:
        """ADX: >25 trending, <20 choppy. Uses price range as proxy if no high/low."""
        n = len(prices)
        if n < period + 1:
            return 0
        # Use price range (high-low proxy) if no real OHLC data
        tr_list = []
        dm_plus = []
        dm_minus = []
        for i in range(1, n):
            curr_high = highs[i] if highs and i < len(highs) else max(prices[i], prices[i-1])
            curr_low = lows[i] if lows and i < len(lows) else min(prices[i], prices[i-1])
            prev_high = highs[i-1] if highs and i-1 < len(highs) else max(prices[i-1], prices[i-2]) if i >= 2 else prices[i-1]
            prev_low = lows[i-1] if lows and i-1 < len(lows) else min(prices[i-1], prices[i-2]) if i >= 2 else prices[i-1]
            prev_close = prices[i-1]
            # True Range
            tr = max(curr_high - curr_low, abs(curr_high - prev_close), abs(curr_low - prev_close))
            tr_list.append(tr)
            # Directional Movement
            up_move = curr_high - prev_high
            down_move = prev_low - curr_low
            dm_plus.append(up_move if up_move > down_move and up_move > 0 else 0)
            dm_minus.append(down_move if down_move > up_move and down_move > 0 else 0)

        if len(tr_list) < period:
            return 0

        # Smooth with Wilder's method (EMA-like)
        tr_smooth = sum(tr_list[:period])
        dp_smooth = sum(dm_plus[:period])
        dm_smooth = sum(dm_minus[:period])
        for i in range(period, len(tr_list)):
            tr_smooth = tr_smooth - tr_smooth/period + tr_list[i]
            dp_smooth = dp_smooth - dp_smooth/period + dm_plus[i]
            dm_smooth = dm_smooth - dm_smooth/period + dm_minus[i]

        di_plus = (dp_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
        di_minus = (dm_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
        dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100 if (di_plus + di_minus) > 0 else 0

        # ADX = smoothed DX
        return dx  # simplified — full would need another Wilder smooth

    def _calc_atr(self, prices: list[float], period: int = 14) -> float:
        """Average True Range — volatility measure."""
        if len(prices) < period:
            return 0
        trs = []
        for i in range(1, len(prices)):
            high = max(prices[i], prices[i-1])
            low = min(prices[i], prices[i-1])
            tr = max(high - low, abs(high - prices[i-1]), abs(low - prices[i-1]))
            trs.append(tr)
        return sum(trs[-period:]) / period if trs else 0

    def _detect_regime(self, prices: list[float]) -> dict:
        """Returns regime: trending/choppy + volatility level."""
        adx = self._calc_adx(prices)
        atr = self._calc_atr(prices)
        avg_price = sum(prices[-14:]) / len(prices[-14:]) if len(prices) >= 14 else prices[-1]
        atr_pct = (atr / avg_price * 100) if avg_price > 0 else 0

        if adx > 25:
            regime = "trending"
        elif adx > 18:
            regime = "weak_trend"
        else:
            regime = "choppy"

        volatility = "high" if atr_pct > 2 else "medium" if atr_pct > 0.8 else "low"
        return {"regime": regime, "adx": round(adx, 1), "atr": round(atr, 2), "atr_pct": round(atr_pct, 2), "volatility": volatility}

    def get_indicators(self, ticker: str) -> dict:
        """Debug: return all computed indicators for a ticker."""
        prices = list(self.price_history.get(ticker, []))
        if len(prices) < 14:
            return {"ticker": ticker, "error": "insufficient data", "points": len(prices)}

        rsi = self._calc_rsi(prices)
        macd, signal, hist = self._calc_macd(prices)
        bb_lower, bb_mid, bb_upper = self._calc_bb(prices)
        regime = self._detect_regime(prices)
        current = prices[-1]
        change_pct = ((current - prices[0]) / prices[0] * 100) if prices[0] > 0 else 0
        momentum = ((current - prices[-min(5, len(prices))]) / prices[-min(5, len(prices))] * 100) if len(prices) >= 5 else 0
        mtf = {
            "1m": round(self._calc_rsi(prices[-14:]), 1) if len(prices) >= 14 else None,
            "5m": round(self._calc_rsi(prices[-int(min(14*5, len(prices)))::5]), 1) if len(prices) >= 30 else None,
            "15m": round(self._calc_rsi(prices[-int(min(14*15, len(prices)))::15]), 1) if len(prices) >= 50 else None,
        }

        return {
            "ticker": ticker,
            "price": round(current, 2),
            "change_pct": round(change_pct, 2),
            "momentum_5": round(momentum, 2),
            "rsi": round(rsi, 1),
            "rsi_mtf": mtf,
            "macd": {"line": round(macd, 4), "signal": round(signal, 4), "histogram": round(hist, 4)},
            "bb": {"lower": round(bb_lower, 2), "mid": round(bb_mid, 2), "upper": round(bb_upper, 2)},
            "regime": regime,
            "points": len(prices),
        }

    # ── Trailing Stop ──

    def _check_trailing_stop(self, ticker: str, current: float, entry: float) -> bool:
        """Dynamic trailing stop: locks in profits as price rises."""
        highest = self._highest_price.get(ticker, entry)
        if current > highest:
            highest = current
            self._highest_price[ticker] = highest

        pnl_pct = ((current - entry) / entry) * 100

        # Once +2% profit, move stop to breakeven
        if pnl_pct >= 2.0:
            return current <= entry

        # Once +5% profit, trail stop at current - 3%
        if pnl_pct >= 5.0:
            return current <= highest * 0.97

        # Initial stop: -3% from entry
        return pnl_pct <= -self.stop_loss_pct

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

    async def _listen_trade_results(self):
        """Background task: subscribes to trade:result to track consecutive losses."""
        import redis.asyncio as redis
        while True:
            try:
                r = redis.Redis.from_url(self.redis_url)
                pubsub = r.pubsub()
                await pubsub.subscribe("trade:result")
                logger.info("Strategy: listening on trade:result for loss tracking")
                async for msg in pubsub.listen():
                    if msg["type"] != "message":
                        continue
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    status = data.get("status", "")
                    pnl = float(data.get("pnl_percent", 0))
                    if status == "LOSS" and pnl < 0:
                        self._consecutive_losses += 1
                        logger.info(f"Strategy: consecutive losses = {self._consecutive_losses}")
                        if self._consecutive_losses >= 3:
                            cooldown = asyncio.get_event_loop().time() + 600
                            self._loss_cooldown_until = cooldown
                            logger.warning(f"Strategy: 3+ consecutive losses — cooldown until {cooldown:.0f}")
                    elif status == "WIN":
                        self._consecutive_losses = 0
                await pubsub.unsubscribe("trade:result")
                await r.aclose()
            except Exception as e:
                logger.error(f"Strategy: trade:result listener error: {e}")
                await asyncio.sleep(10)

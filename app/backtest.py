import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class BTPosition:
    ticker: str
    qty: int
    entry_price: float
    entry_time: datetime
    side: str = "LONG"


@dataclass
class BTTrade:
    ticker: str
    direction: str
    qty: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float


class BacktestEngine:
    def __init__(self, **params):
        self.capital = params.get("initial_capital", 100000.0)
        self.max_positions = params.get("max_positions", 3)
        self.position_size_pct = params.get("position_size_pct", 5.0)
        self.take_profit_pct = params.get("take_profit_pct", 2.0)
        self.stop_loss_pct = params.get("stop_loss_pct", 3.0)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_oversold = params.get("rsi_oversold", 55.0)
        self.rsi_overbought = params.get("rsi_overbought", 70.0)
        self.min_drop_pct = params.get("min_drop_pct", 0.2)

    def run(self, tickers: list[str], period: str = "6mo", interval: str = "1h") -> dict:
        """Run backtest and return results."""
        results = []
        for ticker in tickers:
            try:
                r = self._backtest_ticker(ticker, period, interval)
                if r:
                    results.append(r)
            except Exception as e:
                logger.error(f"Backtest failed for {ticker}: {e}")

        if not results:
            return {"error": "No results — all tickers failed"}

        return self._aggregate(results)

    def _backtest_ticker(self, ticker: str, period: str, interval: str) -> Optional[dict]:
        logger.info(f"Backtesting {ticker} ({period}, {interval})...")

        yt = ticker if ticker.endswith(".NS") or ticker.endswith(".BO") else f"{ticker}.NS"
        df = yf.download(yt, period=period, interval=interval, progress=False)
        if df is None or df.empty or len(df) < 30:
            logger.warning(f"Insufficient data for {ticker}: {len(df) if df is not None else 0} rows")
            return None

        closes = df["Close"].values.tolist()
        timestamps = df.index.tolist()

        positions: dict[str, BTPosition] = {}
        trades: list[BTTrade] = []
        wallet = self.capital
        invested = 0.0
        price_history: deque[float] = deque(maxlen=200)

        equity_curve = [wallet]
        drawdown_peak = wallet

        for i in range(30, len(closes)):
            current = float(closes[i])
            ts = timestamps[i]
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()
            elif not isinstance(ts, datetime):
                ts = datetime.now()

            price_history.append(current)
            prices = list(price_history)

            # Check exits on open positions
            to_close = []
            for tick, pos in list(positions.items()):
                if tick != ticker:  # only tracking this ticker
                    continue
                pos_pnl_pct = ((current - pos.entry_price) / pos.entry_price) * 100

                # Trailing stop
                highest = getattr(pos, '_highest', pos.entry_price)
                if current > highest:
                    highest = current
                    pos._highest = highest  # type: ignore

                sell = False
                if pos_pnl_pct >= self.take_profit_pct:
                    sell = True
                elif pos_pnl_pct <= -self.stop_loss_pct:
                    sell = True
                elif pos_pnl_pct >= 2.0 and current <= pos.entry_price:
                    sell = True  # breakeven trail
                elif pos_pnl_pct >= 5.0 and current <= highest * 0.97:
                    sell = True  # trail at -3%

                if sell:
                    to_close.append((tick, current, pos_pnl_pct))

            for tick, exit_price, pnl_pct in to_close:
                pos = positions[tick]
                realized_pnl = (exit_price - pos.entry_price) * pos.qty
                wallet += pos.qty * pos.entry_price + realized_pnl
                invested -= pos.qty * pos.entry_price
                trades.append(BTTrade(
                    ticker=tick, direction="SELL", qty=pos.qty,
                    entry_price=pos.entry_price, exit_price=exit_price,
                    entry_time=pos.entry_time, exit_time=ts,
                    pnl=realized_pnl, pnl_pct=pnl_pct,
                ))
                del positions[tick]

            # Check entries
            if len(positions) < self.max_positions and ticker not in positions and len(prices) >= self.rsi_period:
                rsi = self._calc_rsi(prices)
                change_pct = ((current - prices[0]) / prices[0] * 100) if prices[0] > 0 else 0

                if rsi < self.rsi_oversold and change_pct < -self.min_drop_pct:
                    if self._mtf_rsi_ok(prices) and self._macd_ok(prices):
                        notional = wallet * (self.position_size_pct / 100)
                        qty = max(1, int(notional / current))
                        cost = qty * current
                        if cost <= wallet:
                            wallet -= cost
                            invested += cost
                            positions[ticker] = BTPosition(
                                ticker=ticker, qty=qty, entry_price=current,
                                entry_time=ts, side="LONG",
                            )
                            positions[ticker]._highest = current  # type: ignore

            # Track equity
            unrealized = sum((current - p.entry_price) * p.qty for p in positions.values())
            equity = wallet + invested + unrealized
            equity_curve.append(equity)
            if equity > drawdown_peak:
                drawdown_peak = equity

        # Close any remaining positions at last price
        final_price = float(closes[-1])
        for tick, pos in list(positions.items()):
            pnl = (final_price - pos.entry_price) * pos.qty
            pnl_pct = ((final_price - pos.entry_price) / pos.entry_price) * 100
            wallet += pos.qty * pos.entry_price + pnl
            invested -= pos.qty * pos.entry_price
            trades.append(BTTrade(
                ticker=tick, direction="SELL", qty=pos.qty,
                entry_price=pos.entry_price, exit_price=final_price,
                entry_time=pos.entry_time, exit_time=timestamps[-1],
                pnl=pnl, pnl_pct=pnl_pct,
            ))

        return {
            "ticker": ticker,
            "trades": len(trades),
            "wins": sum(1 for t in trades if t.pnl > 0),
            "losses": sum(1 for t in trades if t.pnl < 0),
            "final_equity": wallet + invested,
            "equity_curve": equity_curve,
            "trades_list": trades,
        }

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

    def _mtf_rsi_ok(self, prices: list[float]) -> bool:
        n = len(prices)
        if n < 30:
            return False
        rsi_1m = self._calc_rsi(prices[-14:])
        m5 = prices[-int(min(14*5, n))::5]
        m15 = prices[-int(min(14*15, n))::15]
        rsi_5m = self._calc_rsi(m5) if len(m5) >= 5 else 50
        rsi_15m = self._calc_rsi(m15) if len(m15) >= 5 else 50
        return rsi_1m < self.rsi_oversold and rsi_5m < self.rsi_oversold and rsi_15m < self.rsi_oversold

    def _macd_ok(self, prices: list[float]) -> bool:
        if len(prices) < 30:
            return True
        ema12 = self._ema(prices, 12)
        ema26 = self._ema(prices, 26)
        macd = ema12 - ema26
        # Check previous
        prev_ema12 = self._ema(prices[:-1], 12) if len(prices) > 12 else ema12
        prev_ema26 = self._ema(prices[:-1], 26) if len(prices) > 26 else ema26
        prev_macd = prev_ema12 - prev_ema26
        return macd > prev_macd or macd > 0

    def _ema(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        multiplier = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * multiplier + ema
        return ema

    def _aggregate(self, results: list[dict]) -> dict:
        all_trades = []
        total_equity = self.capital * len(results)
        equity_curves = []

        for r in results:
            all_trades.extend(r["trades_list"])
            total_equity += (r["final_equity"] - self.capital)
            equity_curves.append(r["equity_curve"])

        trades = all_trades
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl < 0]

        total_pnl = sum(t.pnl for t in trades)
        total_return = (total_pnl / (self.capital * len(results))) * 100
        win_rate = (len(wins) / len(trades) * 100) if trades else 0

        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 0
        profit_factor = (sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses))) if losses and sum(t.pnl for t in losses) != 0 else 0

        # CAGR: annualized return
        if equity_curves and equity_curves[0]:
            eq = np.array(equity_curves[0])
            periods = len(eq)
            if periods > 1 and eq[0] > 0:
                total_return_frac = (eq[-1] - eq[0]) / eq[0]
                # Rough annualization
                years = periods / (252 * 6.5)  # trading days * hours
                if years > 0:
                    cagr = ((1 + total_return_frac) ** (1 / max(years, 0.1)) - 1) * 100
                else:
                    cagr = 0
            else:
                cagr = 0
        else:
            cagr = 0

        # Max drawdown
        if equity_curves and equity_curves[0]:
            eq = np.array(equity_curves[0])
            peak = np.maximum.accumulate(eq)
            drawdown = (eq - peak) / peak * 100
            max_dd = abs(drawdown.min())
        else:
            max_dd = 0

        # Sharpe (simplified)
        if equity_curves and equity_curves[0] and len(equity_curves[0]) > 2:
            eq = np.array(equity_curves[0])
            returns = np.diff(eq) / eq[:-1]
            returns = returns[~np.isnan(returns)]
            if len(returns) > 0 and returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 6.5)  # annualized
            else:
                sharpe = 0
        else:
            sharpe = 0

        return {
            "summary": {
                "total_trades": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "total_return_pct": round(total_return, 2),
                "cagr": round(cagr, 2),
                "sharpe_ratio": round(sharpe, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 2),
            },
            "tickers_tested": [r["ticker"] for r in results],
            "recent_trades": [
                {
                    "ticker": t.ticker, "dir": t.direction, "qty": t.qty,
                    "entry": round(t.entry_price, 2), "exit": round(t.exit_price, 2),
                    "pnl_pct": round(t.pnl_pct, 2), "pnl": round(t.pnl, 2),
                    "entry_time": t.entry_time.isoformat() if hasattr(t.entry_time, 'isoformat') else str(t.entry_time),
                }
                for t in trades[-10:]
            ],
        }


backtest_engine = BacktestEngine()

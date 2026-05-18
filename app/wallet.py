import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    ticker: str
    qty: int
    avg_price: float
    side: str  # LONG or SHORT


    def _default_capital() -> float:
        return float(os.getenv("STRATEGY_INITIAL_CAPITAL", "100000"))

@dataclass
class Wallet:
    initial_capital: float = field(default_factory=_default_capital)
    available: float = 0.0
    invested: float = 0.0
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)

    def __post_init__(self):
        if self.available == 0.0:
            self.available = self.initial_capital

    def can_afford(self, notional: float) -> bool:
        return self.available >= notional

    def open_position(self, ticker: str, qty: int, price: float, side: str):
        notional = qty * price
        if notional > self.available:
            raise ValueError(f"Insufficient funds: need ₹{notional:,.2f}, have ₹{self.available:,.2f}")

        self.available -= notional
        self.invested += notional

        if ticker in self.positions:
            pos = self.positions[ticker]
            total_qty = pos.qty + qty
            total_cost = (pos.qty * pos.avg_price) + notional
            pos.qty = total_qty
            pos.avg_price = total_cost / total_qty if total_qty > 0 else 0
        else:
            self.positions[ticker] = Position(ticker=ticker, qty=qty, avg_price=price, side=side)

        logger.info(f"Position opened: {ticker} {side} qty={qty} @ {price} | available={self.available:,.0f} invested={self.invested:,.0f}")

    def close_position(self, ticker: str, qty: int, price: float):
        if ticker not in self.positions:
            raise ValueError(f"No position in {ticker}")

        pos = self.positions[ticker]
        close_qty = min(qty, pos.qty)
        pnl = close_qty * (price - pos.avg_price)
        if pos.side == "SHORT":
            pnl = close_qty * (pos.avg_price - price)

        self.realized_pnl += pnl
        notional_returned = close_qty * pos.avg_price
        self.available += notional_returned + pnl
        self.invested -= notional_returned

        pos.qty -= close_qty
        if pos.qty <= 0:
            del self.positions[ticker]

        logger.info(f"Position closed: {ticker} qty={close_qty} @ {price} P&L=₹{pnl:,.2f}")

    def total_equity(self) -> float:
        return self.available + self.invested

    def total_pnl(self) -> float:
        return self.total_equity() - self.initial_capital

    def total_pnl_pct(self) -> float:
        return (self.total_pnl() / self.initial_capital) * 100

    def win_rate(self, wins: int, total: int) -> float:
        return (wins / total * 100) if total > 0 else 0

    def snapshot(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "available": self.available,
            "invested": self.invested,
            "realized_pnl": self.realized_pnl,
            "total_equity": self.total_equity(),
            "total_pnl": self.total_pnl(),
            "total_pnl_pct": self.total_pnl_pct(),
            "positions": {
                t: {"ticker": p.ticker, "qty": p.qty, "avg_price": p.avg_price, "side": p.side}
                for t, p in self.positions.items()
            },
        }


wallet = Wallet()

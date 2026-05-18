import asyncio
import json
import logging
import random
import os
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

DEFAULT_TICKERS = ["RELIANCE.NS", "TATAPOWER.NS", "HAL.NS", "BEL.NS", "SBIN.NS"]

def _load_tickers() -> list[str]:
    raw = os.getenv("STRATEGY_TICKERS", "")
    if raw:
        tickers = [t.strip() for t in raw.split(",") if t.strip()]
        if tickers:
            return tickers
    return DEFAULT_TICKERS

NSE_TICKERS = _load_tickers()

TICKER_MAP = {
    t: t.replace(".NS", "").replace(".BO", "")
    for t in NSE_TICKERS
}


def _add_tickers(new_tickers: list[str]):
    """Dynamically add tickers to the watchlist."""
    global NSE_TICKERS, TICKER_MAP
    added = []
    for t in new_tickers:
        t = t.strip().upper()
        if t not in NSE_TICKERS and (t.endswith(".NS") or t.endswith(".BO")):
            NSE_TICKERS.append(t)
            TICKER_MAP[t] = t.replace(".NS", "").replace(".BO", "")
            added.append(t)
    if added:
        logger.info(f"Added {len(added)} tickers dynamically: {added}")
    return added


class MarketDataBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self._running = False
        self._latest: dict[str, dict] = {}
        self.callbacks: list = []

    def add_client(self, ws: WebSocket):
        self.clients.append(ws)

    def remove_client(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def start(self):
        self._running = True
        logger.info("Market data bridge started (yfinance, polling 2s)")

        while self._running:
            try:
                quotes = await asyncio.to_thread(self._poll_yfinance)
                for q in quotes:
                    self._latest[q["data"]["ticker"]] = q
                    for cb in self.callbacks:
                        try:
                            cb(q["data"])
                        except Exception:
                            pass
                    for ws in self.clients:
                        try:
                            await ws.send_text(json.dumps(q))
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Market data poll error: {e}")

            await asyncio.sleep(2)

    def _poll_yfinance(self) -> list[dict]:
        tickers_str = " ".join(NSE_TICKERS)
        results = []

        try:
            data = yf.download(
                tickers=tickers_str,
                period="1d",
                interval="1m",
                progress=False,
                group_by="ticker",
            )
        except Exception as e:
            logger.warning(f"yfinance download failed: {e}")
            return []

        if data is None or data.empty:
            return []

        for yf_ticker in NSE_TICKERS:
            short = TICKER_MAP.get(yf_ticker, yf_ticker.replace(".NS", ""))
            try:
                if yf_ticker in data.columns.get_level_values(0):
                    df = data[yf_ticker]
                elif len(NSE_TICKERS) == 1:
                    df = data
                else:
                    continue

                if df.empty:
                    continue

                last_row = df.iloc[-1]
                price = float(last_row["Close"])
                if price <= 0:
                    continue

                volume = int(last_row.get("Volume", 0) or 0)

                prev = self._latest.get(short, {})
                prev_price = prev.get("data", {}).get("last_price", price)

                spread = max(price * 0.0005, 0.05)
                bid = round(price - spread, 2)
                ask = round(price + spread, 2)

                quote = {
                    "type": "quote",
                    "data": {
                        "ticker": short,
                        "exchange": "NSE",
                        "bid": bid,
                        "ask": ask,
                        "bid_qty": random.randint(500, 5000),
                        "ask_qty": random.randint(500, 5000),
                        "last_price": price,
                        "volume": volume,
                        "trend": "up" if price >= prev_price else "down",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }
                results.append(quote)
            except Exception as e:
                logger.debug(f"Skipping {yf_ticker}: {e}")
                continue

        return results

    def get_latest(self, ticker: str) -> Optional[dict]:
        return self._latest.get(ticker)

    def stop(self):
        self._running = False

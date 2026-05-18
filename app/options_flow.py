import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_latest_oi: dict[str, dict] = {}
_latest_pcr: float | None = None
_last_update: datetime | None = None


async def scan_ticker_options(ticker: str) -> Optional[dict]:
    """Scan options chain for unusual activity on a ticker."""
    global _latest_oi
    try:
        yt = ticker if ticker.endswith(".NS") else f"{ticker}.NS"
        stock = yf.Ticker(yt)

        # Get nearest expiration
        expirations = stock.options
        if not expirations:
            return None

        expiry = expirations[0]
        chain = stock.option_chain(expiry)

        calls = chain.calls
        puts = chain.puts

        if calls.empty or puts.empty:
            return None

        # Total OI and volume
        total_call_oi = calls["openInterest"].sum() if "openInterest" in calls.columns else 0
        total_put_oi = puts["openInterest"].sum() if "openInterest" in puts.columns else 0
        total_call_vol = calls["volume"].sum() if "volume" in calls.columns else 0
        total_put_vol = puts["volume"].sum() if "volume" in puts.columns else 0

        # PCR (Put-Call Ratio) from OI
        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0

        # Detect unusual activity: volume > 2x OI (intraday churn)
        unusual = []
        atm_price = stock.info.get("currentPrice", stock.info.get("regularMarketPrice", 0))
        atm_strike = round(atm_price / 10) * 10 if atm_price else 0

        for _, row in calls.iterrows():
            vol = row.get("volume", 0) or 0
            oi = row.get("openInterest", 0) or 0
            if oi > 0 and vol > oi * 2:
                strike = row.get("strike", 0)
                unusual.append({
                    "type": "CALL",
                    "strike": strike,
                    "volume": int(vol),
                    "oi": int(oi),
                    "ratio": round(vol / oi, 1),
                    "signal": "bullish" if strike > atm_strike else "ATM/mild_bullish",
                })

        for _, row in puts.iterrows():
            vol = row.get("volume", 0) or 0
            oi = row.get("openInterest", 0) or 0
            if oi > 0 and vol > oi * 2:
                strike = row.get("strike", 0)
                unusual.append({
                    "type": "PUT",
                    "strike": strike,
                    "volume": int(vol),
                    "oi": int(oi),
                    "ratio": round(vol / oi, 1),
                    "signal": "bearish" if strike < atm_strike else "ATM/hedge",
                })

        result = {
            "ticker": ticker,
            "expiry": expiry,
            "pcr": round(pcr, 2),
            "call_oi": int(total_call_oi),
            "put_oi": int(total_put_oi),
            "call_volume": int(total_call_vol),
            "put_volume": int(total_put_vol),
            "atm_strike": atm_strike,
            "unusual_activity": unusual,
            "sentiment": "bullish" if pcr < 0.7 else "bearish" if pcr > 1.3 else "neutral",
            "timestamp": datetime.now(IST).isoformat(),
        }

        _latest_oi[ticker] = result
        return result

    except Exception as e:
        logger.warning(f"Options scan failed for {ticker}: {e}")
        return None


async def scan_nifty_pcr() -> Optional[dict]:
    """Scan NIFTY 50 options for overall market PCR."""
    global _latest_pcr, _last_update
    try:
        # Use NIFTY ETF or index options
        result = await scan_ticker_options("NIFTY50")
        if result:
            _latest_pcr = result["pcr"]
            _last_update = datetime.now(IST)
        return result
    except Exception:
        return None


def get_option_sentiment(ticker: str) -> dict:
    """Get latest options sentiment for a ticker."""
    if ticker in _latest_oi:
        return _latest_oi[ticker]
    return {"ticker": ticker, "status": "no_data", "message": "No options data available yet"}


def get_market_pcr() -> dict:
    """Get latest NIFTY PCR."""
    return {
        "pcr": _latest_pcr,
        "sentiment": "bullish" if _latest_pcr and _latest_pcr < 0.7 else "bearish" if _latest_pcr and _latest_pcr > 1.3 else "neutral",
        "updated": _last_update.isoformat() if _last_update else None,
    }


async def options_poller(interval: int = 900):
    """Background task that scans options periodically."""
    logger.info(f"Options flow scanner started (interval={interval}s)")
    tickers = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS"]
    while True:
        for ticker in tickers:
            try:
                result = await scan_ticker_options(ticker)
                if result and result["unusual_activity"]:
                    logger.info(f"Unusual options in {ticker}: {len(result['unusual_activity'])} strikes")
            except Exception as e:
                logger.error(f"Options poller error for {ticker}: {e}")
            await asyncio.sleep(5)  # Rate limit
        # Scan NIFTY PCR
        try:
            await scan_nifty_pcr()
        except Exception:
            pass
        await asyncio.sleep(interval)

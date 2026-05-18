import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_latest_oi: dict[str, dict] = {}
_latest_pcr: float | None = None
_last_update: datetime | None = None

# NSE symbol mapping (yfinance format → NSE format)
NSE_SYMBOL_MAP = {
    "RELIANCE.NS": "RELIANCE", "RELIANCE": "RELIANCE",
    "TCS.NS": "TCS", "TCS": "TCS",
    "INFY.NS": "INFY", "INFY": "INFY",
    "HDFCBANK.NS": "HDFCBANK", "HDFCBANK": "HDFCBANK",
    "ITC.NS": "ITC", "ITC": "ITC",
    "SBIN.NS": "SBIN", "SBIN": "SBIN",
    "ICICIBANK.NS": "ICICIBANK", "ICICIBANK": "ICICIBANK",
    "BHARTIARTL.NS": "BHARTIARTL", "BHARTIARTL": "BHARTIARTL",
    "HINDUNILVR.NS": "HINDUNILVR", "HINDUNILVR": "HINDUNILVR",
    "MARUTI.NS": "MARUTI", "MARUTI": "MARUTI",
}


def _nse_symbol(ticker: str) -> str:
    return NSE_SYMBOL_MAP.get(ticker.upper(), ticker.upper().replace(".NS", "").replace(".BO", ""))


async def scan_ticker_options(ticker: str, client: httpx.AsyncClient | None = None) -> Optional[dict]:
async def scan_ticker_options(ticker: str, client: httpx.AsyncClient | None = None) -> Optional[dict]:
    """Scan NSE options chain for unusual activity on a ticker."""
    global _latest_oi
    sym = _nse_symbol(ticker)

    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })

    try:
        # NSE options chain API
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={sym}"
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(f"NSE options API returned {resp.status_code} for {sym}")
            return None

        data = resp.json()
        records = data.get("records", {})
        underlying = records.get("underlyingValue", 0)
        atm_strike = round(underlying / 10) * 10 if underlying else 0
        expiry_dates = records.get("expiryDates", [])
        current_expiry = expiry_dates[0] if expiry_dates else None

        # Aggregate call/put data
        total_call_oi = 0
        total_put_oi = 0
        total_call_vol = 0
        total_put_vol = 0
        unusual = []

        filtered = records.get("data", [])
        for strike_data in filtered:
            ce = strike_data.get("CE", {})
            pe = strike_data.get("PE", {})

            if ce:
                call_oi = ce.get("openInterest", 0) or 0
                call_vol = ce.get("totalTradedVolume", 0) or 0
                total_call_oi += call_oi
                total_call_vol += call_vol
                if call_oi > 0 and call_vol > call_oi * 1.5:
                    unusual.append({
                        "type": "CALL", "strike": ce.get("strikePrice", 0),
                        "volume": call_vol, "oi": call_oi,
                        "ratio": round(call_vol / call_oi, 1),
                        "signal": "bullish" if ce.get("strikePrice", 0) > atm_strike else "ATM/bullish",
                    })

            if pe:
                put_oi = pe.get("openInterest", 0) or 0
                put_vol = pe.get("totalTradedVolume", 0) or 0
                total_put_oi += put_oi
                total_put_vol += put_vol
                if put_oi > 0 and put_vol > put_oi * 1.5:
                    unusual.append({
                        "type": "PUT", "strike": pe.get("strikePrice", 0),
                        "volume": put_vol, "oi": put_oi,
                        "ratio": round(put_vol / put_oi, 1),
                        "signal": "bearish" if pe.get("strikePrice", 0) < atm_strike else "ATM/hedge",
                    })

        pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0

        # PCR sentiment: <0.7 bullish, >1.3 bearish
        sentiment = "bullish" if pcr < 0.7 else "bearish" if pcr > 1.3 else "neutral"

        result = {
            "ticker": ticker,
            "expiry": current_expiry,
            "pcr": round(pcr, 2),
            "call_oi": total_call_oi,
            "put_oi": total_put_oi,
            "call_volume": total_call_vol,
            "put_volume": total_put_vol,
            "atm_strike": atm_strike,
            "underlying": underlying,
            "unusual_activity": unusual[:10],
            "sentiment": sentiment,
            "timestamp": datetime.now(IST).isoformat(),
        }

        _latest_oi[ticker] = result
        return result

    except Exception as e:
        logger.warning(f"Options scan failed for {ticker}: {e}")
        return None
    finally:
        if should_close:
            await client.aclose()


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


async def options_poller(interval: int = 1800):
    """Background task that scans options periodically."""
    logger.info(f"Options flow scanner started (interval={interval}s)")
    tickers = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC"]
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as client:
        while True:
            for ticker in tickers:
                try:
                    result = await scan_ticker_options(ticker, client)
                    if result and result["unusual_activity"]:
                        logger.info(f"Unusual options in {ticker}: {len(result['unusual_activity'])} strikes, PCR={result['pcr']}")
                except Exception as e:
                    logger.error(f"Options poller error for {ticker}: {e}")
                await asyncio.sleep(3)
            await asyncio.sleep(interval)

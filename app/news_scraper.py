import feedparser
import logging
import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.moneycontrol.com/rss/Marketreports.xml",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

NSE_TICKER_PATTERN = re.compile(r'\b([A-Z]{2,20})\b')
COMMON_WORDS = {"THE", "AND", "FOR", "LTD", "NSE", "BSE", "IPO", "Q1", "Q2", "Q3", "Q4",
                "FY24", "FY25", "FY26", "RSI", "NIFTY", "SENSEX", "INDIA", "STOCK", "STOCKS",
                "MARKET", "NEWS", "RUPEE", "DOLLAR", "BANK", "RBI", "SEBI", "GST", "CEO", "CFO"}

_latest_news: list[dict] = []
_last_fetch = datetime(2000, 1, 1, tzinfo=IST)


def _extract_tickers(text: str) -> list[str]:
    """Extract potential NSE ticker names from text."""
    tickers = set()
    for match in NSE_TICKER_PATTERN.finditer(text.upper()):
        word = match.group(1)
        if word not in COMMON_WORDS and len(word) >= 3:
            tickers.add(word)
    return list(tickers)[:5]


async def _fetch_feed(url: str) -> list[dict]:
    """Fetch and parse one RSS feed."""
    items = []
    try:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, lambda: feedparser.parse(url))
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            summary = entry.get("summary", entry.get("description", ""))
            link = entry.get("link", "")
            published = entry.get("published", entry.get("updated", ""))
            # Strip HTML tags
            clean_summary = re.sub(r'<[^>]+>', '', summary)[:300]
            tickers = _extract_tickers(title + " " + clean_summary)
            items.append({
                "title": title,
                "summary": clean_summary,
                "tickers": tickers,
                "link": link,
                "published": published,
            })
    except Exception as e:
        logger.warning(f"RSS fetch failed for {url}: {e}")
    return items


async def fetch_all_news() -> list[dict]:
    """Fetch all RSS feeds, deduplicate, return latest news."""
    global _latest_news, _last_fetch

    now = datetime.now(IST)
    if (now - _last_fetch).total_seconds() < 600:  # Cache 10 min
        return _latest_news

    all_items = []
    for url in RSS_FEEDS:
        items = await _fetch_feed(url)
        all_items.extend(items)

    # Deduplicate by title similarity
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    _latest_news = unique
    _last_fetch = now
    logger.info(f"Fetched {len(unique)} news items across {len(RSS_FEEDS)} feeds")
    return unique


def get_news_for_ticker(ticker: str, limit: int = 5) -> list[dict]:
    """Get news items relevant to a specific ticker."""
    clean = ticker.upper().replace(".NS", "").replace(".BO", "")
    matches = []
    for item in _latest_news:
        if clean in item.get("tickers", []) or clean in item["title"].upper():
            matches.append(item)
    return matches[:limit]


def get_latest_news(limit: int = 10) -> list[dict]:
    """Get latest cached news items."""
    return _latest_news[:limit]


def get_news_context(ticker: str) -> str:
    """Build a context string for LLM prompt from news about a ticker."""
    items = get_news_for_ticker(ticker, limit=5)
    if not items:
        return "No recent news found for this ticker."

    lines = ["Recent news:"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']}")
        if item["summary"]:
            lines.append(f"   {item['summary'][:150]}")
    return "\n".join(lines)


async def start_news_poller(interval: int = 900):
    """Background task that polls RSS feeds periodically."""
    logger.info(f"News poller started (interval={interval}s)")
    while True:
        try:
            await fetch_all_news()
        except Exception as e:
            logger.error(f"News poller error: {e}")
        await asyncio.sleep(interval)

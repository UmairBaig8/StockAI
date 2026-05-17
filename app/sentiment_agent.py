import json
import logging

from .config import Settings
from .models import Sentiment
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

SENTIMENT_PROMPT = """You are a Real-Time Market Sentiment Analyst for the Indian Stock Market (NSE/BSE). Your job is to assess the current market sentiment for a specific stock or sector using your knowledge of recent events.

### YOUR TASK:
1. Assess overall market sentiment for the given ticker
2. Identify key drivers (news, earnings, regulatory, geopolitical)
3. Assign a Fear & Greed score (0 = extreme fear, 100 = extreme greed)
4. Flag any imminent catalyst events (earnings, RBI policy, budget, etc.)

### OUTPUT FORMAT — JSON ONLY:
{
  "ticker": "SYMBOL",
  "sentiment": "Bullish / Bearish / Neutral",
  "fear_greed_index": 0 to 100,
  "confidence": 0.0 to 1.0,
  "key_drivers": ["driver 1", "driver 2"],
  "risk_factors": ["risk 1", "risk 2"],
  "catalyst_events": ["event 1"],
  "recommendation": "LONG / SHORT / AVOID",
  "summary": "One-line executive summary."
}"""


class SentimentAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "sentiment")

    def analyze(self, ticker: str, sector: str = "General", context: str = "") -> dict:
        prompt = json.dumps({
            "ticker": ticker,
            "sector": sector,
            "exchange": "NSE",
            "context": context or "Analyze recent market sentiment and news for this stock.",
        })

        try:
            data = self.llm.generate_json(SENTIMENT_PROMPT, prompt, temperature=0.5, max_tokens=768)
            logger.info(f"Sentiment: {ticker} → {data.get('sentiment')} FGI={data.get('fear_greed_index')}")
            return data
        except Exception as e:
            logger.error(f"Sentiment analysis failed for {ticker}: {e}")
            return {"ticker": ticker, "sentiment": "Neutral", "fear_greed_index": 50, "confidence": 0.3, "key_drivers": [], "risk_factors": [], "catalyst_events": [], "recommendation": "AVOID", "summary": "Analysis failed."}

    def market_snapshot(self, tickers: list[str]) -> list[dict]:
        results = []
        for t in tickers:
            try:
                r = self.analyze(t)
                results.append(r)
            except Exception as e:
                logger.error(f"Snapshot failed for {t}: {e}")
        return results

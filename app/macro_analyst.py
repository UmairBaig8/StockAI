import json
import logging

from .config import Settings
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

MACRO_PROMPT = """You are a Macro Economic Analyst for the Indian Stock Market (NSE/BSE). Your role is to provide a high-level view of the economic environment affecting Indian equities.

### YOUR TASK:
Analyze the macroeconomic landscape for Indian markets. Consider:
1. RBI Monetary Policy (repo rate, inflation, liquidity)
2. Global cues (Fed policy, crude oil, USD/INR, FII flows)
3. Sector-specific tailwinds/headwinds
4. Geopolitical factors affecting India
5. Upcoming events (Budget, elections, trade deals)

### OUTPUT FORMAT — JSON ONLY:
{
  "overall_sentiment": "Bullish / Bearish / Cautious",
  "nifty_outlook": "Positive / Negative / Range-bound",
  "confidence": 0.0 to 1.0,
  "key_themes": ["theme 1", "theme 2"],
  "risk_factors": ["risk 1", "risk 2"],
  "sectors_to_watch": [
    {"sector": "Banking", "outlook": "Positive", "reason": "..."},
    {"sector": "IT", "outlook": "Negative", "reason": "..."}
  ],
  "fii_dii_sentiment": "Net Buyers / Net Sellers / Neutral",
  "volatility_forecast": "Low / Moderate / High",
  "summary": "One-paragraph macro summary."
}"""


class MacroAnalyst:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "macro")

    def analyze(self, context: str = "") -> dict:
        prompt = json.dumps({
            "market": "NSE/BSE India",
            "context": context or "Provide a current macro overview of Indian equity markets.",
        })

        try:
            data = self.llm.generate_json(MACRO_PROMPT, prompt, temperature=0.4, max_tokens=1024)
            logger.info(f"Macro: {data.get('overall_sentiment')} | Nifty: {data.get('nifty_outlook')}")
            return data
        except Exception as e:
            logger.error(f"Macro analysis failed: {e}")
            return {"overall_sentiment": "Cautious", "nifty_outlook": "Range-bound", "risk_level": "HIGH", "risk": "HIGH", "outlook": "BEARISH", "confidence": 0.3, "key_themes": [], "risk_factors": ["Macro analysis service unavailable — defaulting to conservative"], "sectors_to_watch": [], "fii_dii_sentiment": "Neutral", "volatility_forecast": "Moderate", "summary": "Analysis failed. Defaulting to conservative stance."}

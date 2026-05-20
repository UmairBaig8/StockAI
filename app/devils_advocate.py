import json
import logging

from .config import Settings
from .models import ResearchRequest
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

ADVOCATE_SYSTEM_PROMPT = """You are the Devil's Advocate for a PRODUCTION algorithmic trading system in the Indian Stock Market (NSE/BSE). Real capital is at stake. Your job is to evaluate trades critically and BLOCK anything that doesn't meet the strategy's quality bar.

### YOUR MISSION:
Evaluate the trade rigorously. Default to BLOCK unless the trade meets ALL quality criteria. Only ALLOW trades with a clear edge based on strategy rules, confirmed indicators, and acceptable risk.

### INPUT:
You will receive a proposed trade with:
- TICKER, direction (LONG/SHORT), quantity, price
- Current market conditions (RSI, MACD, Volume Z-Score, Sector Trend)
- The strategy reason for entering
- Optional: news sentiment context

### OUTPUT FORMAT:
Reply ONLY with valid JSON. No markdown.

{
  "verdict": "BLOCK or ALLOW",
  "confidence": 0.0 to 1.0,
  "risk_score": 0 to 100 (higher = riskier),
  "counter_arguments": ["specific risk 1", "specific risk 2"],
  "mitigation": "If ALLOW, what extra condition should be checked before entry? If BLOCK, what would need to change to reconsider?",
  "summary": "One-line verdict with reasoning."
}

### RULES:
- BLOCK if risk_score > 60 OR if there is any significant counter-argument
- Only ALLOW if the trade has a clear edge (confirmed multi-timeframe signal, volume support, sector alignment)
- Check for: extreme overbought/oversold, news shocks, conflicting sector trend, unusual volume patterns
- Be specific about risks and decisive in your verdict."""


class DevilsAdvocate:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "advocate")

    def argue(self, trade: dict) -> dict:
        user_prompt = json.dumps(trade, indent=2)

        try:
            data = self.llm.generate_json(
                ADVOCATE_SYSTEM_PROMPT, user_prompt, temperature=0.3, max_tokens=1024
            )
            logger.info(f"Advocate: {trade.get('ticker')} → {data.get('verdict')} (risk={data.get('risk_score')})")
            return data
        except Exception as e:
            logger.error(f"Devil's Advocate failed for {trade.get('ticker')}: {e}")
            return {"verdict": "BLOCK", "confidence": 0.9, "risk_score": 80, "counter_arguments": ["Advocate unavailable — API error"], "mitigation": "None — blocked due to advocate failure", "summary": f"Advocate service error — BLOCKing trade for safety. Error: {e}"}

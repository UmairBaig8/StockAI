import json
import logging

from .config import Settings
from .models import ResearchRequest
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

ADVOCATE_SYSTEM_PROMPT = """You are the Devil's Advocate for a PAPER TRADING algorithmic system in the Indian Stock Market (NSE/BSE). This is a TEST run — no real money is at stake. Your job is to evaluate trades objectively and only block if there is a genuinely FATAL flaw.

### YOUR MISSION:
Evaluate the trade fairly. Default to ALLOW unless you find a severe, specific risk. Since this is paper trading, we WANT trades to execute so we can learn from outcomes. Only BLOCK trades that are obviously reckless (extreme overbought, major news shock, absurd position sizing).

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
- BLOCK only if risk_score > 85 AND there is a severe counter-argument
- Default to ALLOW for reasonable trades — we learn more by executing
- Be specific about risks, but don't fabricate exaggerated dangers
- Be decisive. Never return vague or fence-sitting analysis."""


class DevilsAdvocate:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "advocate")

    def argue(self, trade: dict) -> dict:
        user_prompt = json.dumps(trade, indent=2)

        try:
            data = self.llm.generate_json(
                ADVOCATE_SYSTEM_PROMPT, user_prompt, temperature=0.5, max_tokens=768
            )
            logger.info(f"Advocate: {trade.get('ticker')} → {data.get('verdict')} (risk={data.get('risk_score')})")
            return data
        except Exception as e:
            logger.error(f"Devil's Advocate failed for {trade.get('ticker')}: {e}")
            return {"verdict": "ALLOW", "confidence": 0.5, "risk_score": 50, "counter_arguments": ["Advocate unavailable"], "mitigation": "Proceed with caution", "summary": "Advocate service error — allowing trade with standard risk checks."}

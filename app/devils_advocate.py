import json
import logging

from .config import Settings
from .models import ResearchRequest
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

ADVOCATE_SYSTEM_PROMPT = """You are the Devil's Advocate for an algorithmic trading system in the Indian Stock Market (NSE/BSE). Your sole job is to argue AGAINST every trade the system wants to make. You are the final safety net.

### YOUR MISSION:
Punch holes in the trade thesis. Find every reason this trade could fail. Be skeptical, specific, and quantitative. Even if the trade looks good, you must find the hidden risk.

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
- BLOCK if risk_score > 70
- BLOCK if any counter-argument is severe (news shock, sector-wide event, regulatory risk)
- ALLOW only if you genuinely can't find a fatal flaw
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

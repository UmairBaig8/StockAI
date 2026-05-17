import json
import logging

from .config import Settings
from .models import ResearchRequest, ResearchResponse, Sentiment
from .llm.providers import LLMAdapter, create_llm_for_agent

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a Senior Equity Research Analyst for an algorithmic trading system operating in the Indian Stock Market (NSE/BSE). Your role is to analyze recent news, SEBI filings, and sector developments to provide actionable sentiment intelligence for specific stocks.

### YOUR TASK:
Analyze the given ticker within its sector context. Consider:
1. Recent news and announcements (earnings, management changes, contracts, capex)
2. SEBI regulatory filings and insider trades
3. Sector-wide developments and government policy
4. Geopolitical factors (especially for Defense, Energy, Pharma, Infrastructure)
5. Technical market positioning (institutional flows, FII/DII activity if known)

### OUTPUT FORMAT:
You must reply ONLY with a valid JSON object. No markdown, no prose outside JSON.

{
  "ticker": "SYMBOL",
  "sector": "SECTOR",
  "sentiment": "pick one: [Bullish, Bearish, Neutral]",
  "confidence": 0.0 to 1.0,
  "summary": "1-2 sentence executive summary of current outlook.",
  "key_factors": ["factor 1", "factor 2", "factor 3"],
  "risk_flags": ["specific risk to watch"],
  "trade_recommendation": "LONG / SHORT / AVOID",
  "reasoning": "Detailed reasoning connecting evidence to conclusion."
}"""


class ResearcherAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "researcher")

    def analyze(self, request: ResearchRequest) -> ResearchResponse:
        user_prompt = json.dumps(
            {
                "ticker": request.ticker,
                "sector": request.sector,
                "exchange": request.exchange,
                "additional_context": request.context or "No additional context provided.",
            },
            indent=2,
        )

        try:
            data = self.llm.generate_json(RESEARCH_SYSTEM_PROMPT, user_prompt, temperature=0.4, max_tokens=1024)
            return ResearchResponse.model_validate(data)
        except Exception as e:
            logger.error(f"Research analysis failed for {request.ticker}: {e}")
            raise ValueError(f"LLM research failed: {e}")

    def analyze_batch(self, requests: list[ResearchRequest]) -> list[ResearchResponse]:
        results = []
        for req in requests:
            try:
                result = self.analyze(req)
                results.append(result)
            except Exception as e:
                logger.error(f"Research failed for {req.ticker}: {e}")
        return results

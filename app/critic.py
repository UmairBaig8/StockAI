import json
import logging

from .config import Settings
from .models import TradePayload, CriticResponse
from .llm.providers import LLMAdapter, create_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Chief Risk Officer and Senior Strategy Critic for an automated algorithmic trading system operating in the Indian Stock Market (NSE/BSE). Your job is to perform a post-mortem analysis on executed trades, identify structural or logical mistakes, and generate actionable "Self-Correction Rules" for the trading agent to follow tomorrow.

### CONTEXT FOR 2026 MARKET ENVIRONMENT:
- SEBI regulations restrict core strategy code rewriting, so your corrections must act as "Execution Filters" or "Risk Overlays".
- Watch out for modern market anomalies: algorithmic wash trading creating fake breakouts, high-frequency liquidity sweeps, and sector-specific sentiment shifts (especially in Defense and Energy).

### INPUT DATA DEFINITIONS:
You will receive a JSON payload containing:
1. "Market_State_At_Entry": Indicators like RSI, MACD, Volume Z-Score, and Sector Trend.
2. "Trade_Execution": Ticker, Entry Price, Exit Price, Direction (Long/Short), and P&L.
3. "Strategy_Intent": The core rule the bot thought it was following.

### CRITICAL ANALYSIS GUIDELINES:
- Isolate the EXACT point of failure. Was it an indicator trap (e.g., buying overbought RSI), a liquidity sweep, or a macro-sentiment shock?
- Do not give generic advice like "be more careful." Give specific, quantifiable boundary adjustments.
- Separate your output into a human-readable analysis and a strict database payload.

### OUTPUT FORMAT:
You must reply ONLY with a valid JSON object matching this schema. Do not include markdown formatting or prose outside the JSON object.

{
  "analysis": {
    "root_cause": "Detailed explanation of why the trade failed based on market state.",
    "mistake_category": "Pick one: [Indicator_Trap, Liquidity_Sweep, Fake_Breakout, Trend_Fight, Macro_Shock]"
  },
  "evolutionary_overlay": {
    "metric_to_watch": "The specific indicator or condition to modify (e.g., 'Volume_Z_Score', 'RSI', 'Time_Of_Day').",
    "operator": "The mathematical operator for the filter (e.g., '>', '<', '!=', 'BETWEEN').",
    "threshold_value": "The new dynamic value or range to enforce.",
    "correction_rule": "A concise, actionable rule for the Actor Agent's system prompt tomorrow (e.g., 'Do not long if Energy sector trend is negative on 1H chart')."
  }
}"""


class CriticAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm(settings)

    def analyze(self, trade: TradePayload) -> CriticResponse:
        user_prompt = json.dumps(
            {
                "Market_State_At_Entry": trade.market_state.model_dump(),
                "Trade_Execution": trade.trade_execution.model_dump(),
                "Strategy_Intent": trade.strategy_intent.model_dump(),
            },
            indent=2,
        )

        try:
            data = self.llm.generate_json(SYSTEM_PROMPT, user_prompt, temperature=0.3, max_tokens=1024)
            return CriticResponse.model_validate(data)
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")

    def analyze_batch(self, trades: list[TradePayload]) -> list[CriticResponse]:
        results = []
        for trade in trades:
            try:
                result = self.analyze(trade)
                results.append(result)
            except Exception as e:
                logger.error(f"Critic failed for {trade.trade_execution.ticker}: {e}")
        return results

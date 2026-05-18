import json
import logging
from datetime import datetime, timedelta, timezone

from .llm.providers import LLMAdapter, create_llm_for_agent
from .config import Settings

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

OPTIMIZER_PROMPT = """You are a Quantitative Strategy Optimizer for an algorithmic trading system operating on the NSE Indian Stock Market. Your job is to analyze recent trading performance and suggest parameter adjustments.

### STRATEGY OVERVIEW:
- Entry: Multi-timeframe RSI (1m/5m/15m) all below oversold threshold + MACD histogram turning positive
- Alternative Entry: Price at lower Bollinger Band (bounce)
- Exit: Take-profit at TP%, Stop-loss at SL%, Trailing stop (breakeven at +2%, trail at -3% after +5%), BB overbought
- Position sizing: PositionSize% of wallet per trade, max MaxPositions open
- Market filters: Skip choppy regime (ADX < 18), skip dead stocks (activity < 0.3%)

### INPUT:
You will receive:
1. Current strategy parameters
2. Last week's trade summary (trades, wins, losses, avg win/loss, P&L, win rate)
3. Sample losing trades with entry/exit reasoning
4. Current market regime

### OUTPUT FORMAT:
Reply ONLY with valid JSON:
{
  "analysis": {
    "main_issue": "One-line diagnosis of biggest performance problem",
    "good_patterns": ["what's working"],
    "bad_patterns": ["what's failing"]
  },
  "suggestions": [
    {
      "parameter": "param_name",
      "current": current_value,
      "suggested": new_value,
      "reason": "Why this change"
    }
  ],
  "confidence": 0.0-1.0,
  "summary": "2-3 sentence executive summary"
}

### RULES:
- Only suggest changes if you're confident (evidence from trade data)
- Max 3 parameter suggestions per review
- Be conservative — don't suggest radical changes without strong evidence
- Consider market regime when making suggestions"""


class OptimizerAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm: LLMAdapter = create_llm_for_agent(settings, "critic")  # reuse critic LLM

    async def analyze_week(self, trades: list[dict], current_params: dict) -> dict:
        """Analyze a week of trades and suggest parameter changes."""
        if not trades:
            return {"analysis": {"main_issue": "No trades to analyze"}, "suggestions": [], "confidence": 0}

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) < 0]
        total = len(trades)
        win_rate = len(wins) / total * 100 if total else 0
        avg_win_pct = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss_pct = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        total_pnl = sum(t["pnl"] for t in trades)

        sample_losses = sorted(losses, key=lambda t: t["pnl"])[:5]
        sample_wins = sorted(wins, key=lambda t: t["pnl"], reverse=True)[:3]

        user_prompt = json.dumps({
            "current_params": current_params,
            "period": "Last 7 days",
            "summary": {
                "total_trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "avg_win_pnl": round(avg_win_pct, 2),
                "avg_loss_pnl": round(avg_loss_pct, 2),
                "profit_factor": round(abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else 0, 2),
            },
            "sample_losing_trades": [
                {"ticker": t["ticker"], "entry": t["entry_price"], "exit": t["exit_price"],
                 "pnl_pct": t["pnl"], "direction": t.get("dir", "BUY")}
                for t in sample_losses
            ],
            "sample_winning_trades": [
                {"ticker": t["ticker"], "entry": t["entry_price"], "exit": t["exit_price"],
                 "pnl_pct": t["pnl"], "direction": t.get("dir", "BUY")}
                for t in sample_wins
            ],
        }, indent=2)

        try:
            data = self.llm.generate_json(OPTIMIZER_PROMPT, user_prompt, temperature=0.4, max_tokens=1024)
            logger.info(f"Optimizer: {data.get('analysis', {}).get('main_issue', 'N/A')}")
            return data
        except Exception as e:
            logger.error(f"Optimizer failed: {e}")
            return {"analysis": {"main_issue": f"LLM error: {e}"}, "suggestions": [], "confidence": 0}

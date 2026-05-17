from pydantic import BaseModel, Field, field_validator
from typing import Optional, Union
from datetime import datetime
from enum import Enum


class MistakeCategory(str, Enum):
    INDICATOR_TRAP = "Indicator_Trap"
    LIQUIDITY_SWEEP = "Liquidity_Sweep"
    FAKE_BREAKOUT = "Fake_Breakout"
    TREND_FIGHT = "Trend_Fight"
    MACRO_SHOCK = "Macro_Shock"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Sentiment(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


class MarketState(BaseModel):
    rsi: float
    macd_histogram: float
    volume_z_score: float
    sector_trend: float
    price_velocity_5m: float
    trend_profile_1h: float

    def to_vector(self) -> list[float]:
        return [
            self.rsi,
            self.macd_histogram,
            self.volume_z_score,
            self.sector_trend,
            self.price_velocity_5m,
            self.trend_profile_1h,
        ]


class TradeExecution(BaseModel):
    ticker: str
    exchange: str = "NSE"
    direction: Direction
    entry_price: float
    exit_price: float
    quantity: int
    pnl_percent: float
    timestamp: Optional[datetime] = None


class StrategyIntent(BaseModel):
    core_rule: str
    indicators_used: list[str] = []


class TradePayload(BaseModel):
    market_state: MarketState
    trade_execution: TradeExecution
    strategy_intent: StrategyIntent


class EvolutionaryOverlay(BaseModel):
    metric_to_watch: str
    operator: str
    threshold_value: str
    correction_rule: str

    @field_validator("threshold_value", mode="before")
    @classmethod
    def coerce_threshold(cls, v):
        return str(v)


class CriticAnalysis(BaseModel):
    root_cause: str
    mistake_category: MistakeCategory


class CriticResponse(BaseModel):
    analysis: CriticAnalysis
    evolutionary_overlay: EvolutionaryOverlay


class MemoryEntry(BaseModel):
    id: Optional[str] = None
    timestamp: datetime
    ticker: str
    trade_type: Direction
    outcome: str = "LOSS"
    pnl_percent: float
    market_vector: list[float]
    analysis: CriticAnalysis
    evolutionary_overlay: EvolutionaryOverlay


class PreTradeQuery(BaseModel):
    ticker: str
    market_state: MarketState


class PreTradeResult(BaseModel):
    matched: bool
    similarity: float
    correction_rule: Optional[str] = None
    past_mistake: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    entries: int
    provider: str = ""


class ResearchRequest(BaseModel):
    ticker: str
    sector: str
    exchange: str = "NSE"
    context: Optional[str] = None


class ResearchResponse(BaseModel):
    ticker: str
    sector: str
    sentiment: Sentiment
    confidence: float
    summary: str
    key_factors: list[str] = []
    risk_flags: list[str] = []
    trade_recommendation: str
    reasoning: str


class DashTrade(BaseModel):
    time: str
    ticker: str
    dir: str
    qty: int = 0
    entry_price: float = 0
    pnl: float
    status: str


class DashSummary(BaseModel):
    invested: float = 0
    pnl: float = 0
    pnl_percent: float = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0


class DashEvent(BaseModel):
    msg: str
    level: str = "info"


class DashResponse(BaseModel):
    trades: list[DashTrade] = []
    summary: DashSummary = DashSummary()
    last_postmortem: str = ""
    recent_rules: list[str] = []
    events: list[DashEvent] = []
    provider: str = ""
    entries: int = 0

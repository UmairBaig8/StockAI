import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from .config import Settings, get_settings
from .events import store as event_store
from .models import (
    CriticResponse,
    DashResponse,
    DashSummary,
    DashTrade,
    HealthResponse,
    MemoryEntry,
    PreTradeQuery,
    PreTradeResult,
    ResearchRequest,
    ResearchResponse,
    TradePayload,
)
from .critic import CriticAgent
from .researcher import ResearcherAgent
from .devils_advocate import DevilsAdvocate
from .sentiment_agent import SentimentAgent
from .macro_analyst import MacroAnalyst
from .vector_store import VectorStore
from .wallet import wallet as wallet_instance
from .market_data import MarketDataBridge
from . import settings_store as settings_store
from . import news_scraper as news_scraper

logger = logging.getLogger(__name__)
router = APIRouter()

_bridge: MarketDataBridge | None = None


def set_bridge(bridge: MarketDataBridge):
    global _bridge
    _bridge = bridge


def get_bridge() -> MarketDataBridge | None:
    return _bridge


def get_critic(settings: Settings = Depends(get_settings)) -> CriticAgent:
    return CriticAgent(settings)


def get_researcher(settings: Settings = Depends(get_settings)) -> ResearcherAgent:
    return ResearcherAgent(settings)


def get_store(settings: Settings = Depends(get_settings)) -> VectorStore:
    return VectorStore(settings)


def get_advocate(settings: Settings = Depends(get_settings)) -> DevilsAdvocate:
    return DevilsAdvocate(settings)


def get_sentiment(settings: Settings = Depends(get_settings)) -> SentimentAgent:
    return SentimentAgent(settings)


def get_macro(settings: Settings = Depends(get_settings)) -> MacroAnalyst:
    return MacroAnalyst(settings)


@router.post("/postmortem", response_model=CriticResponse)
async def run_postmortem(
    trade: TradePayload,
    critic: CriticAgent = Depends(get_critic),
    store: VectorStore = Depends(get_store),
):
    result = critic.analyze(trade)

    entry = MemoryEntry(
        timestamp=trade.trade_execution.timestamp or datetime.utcnow(),
        ticker=trade.trade_execution.ticker,
        trade_type=trade.trade_execution.direction,
        pnl_percent=trade.trade_execution.pnl_percent,
        market_vector=trade.market_state.to_vector(),
        analysis=result.analysis,
        evolutionary_overlay=result.evolutionary_overlay,
    )
    entry_id = store.store(entry)

    event_store.add_postmortem(result.evolutionary_overlay.correction_rule)
    event_store.add_event(
        f"Postmortem: {trade.trade_execution.ticker} {result.analysis.mistake_category.value} — {result.evolutionary_overlay.correction_rule[:60]}..."
    )

    # SEBI audit trail
    store.audit_log("postmortem", trade.trade_execution.ticker, result.model_dump())

    logger.info(f"Post-mortem stored: {entry_id}")
    return result


@router.post("/pretrade", response_model=PreTradeResult)
async def pre_trade_check(
    query: PreTradeQuery,
    store: VectorStore = Depends(get_store),
):
    result = store.pre_trade_check(query.ticker, query.market_state)
    return result


@router.post("/research", response_model=ResearchResponse)
async def research(
    request: ResearchRequest,
    researcher: ResearcherAgent = Depends(get_researcher),
):
    result = researcher.analyze(request)
    event_store.add_event(
        f"Research: {request.ticker} -> {result.sentiment.value} ({result.confidence:.0%}) {result.trade_recommendation}"
    )
    return result


@router.post("/research/batch", response_model=list[ResearchResponse])
async def research_batch(
    requests: list[ResearchRequest],
    researcher: ResearcherAgent = Depends(get_researcher),
):
    results = researcher.analyze_batch(requests)
    for r in results:
        event_store.add_event(f"Research: {r.ticker} -> {r.sentiment.value} {r.trade_recommendation}")
    return results


@router.get("/dash", response_model=DashResponse)
async def dash(store: VectorStore = Depends(get_store), settings: Settings = Depends(get_settings)):
    snap = event_store.snapshot()
    trades = snap["trades"]

    total_invested = sum(t.entry_price * t.qty for t in trades)
    total_pnl_amount = sum(t.entry_price * t.qty * t.pnl / 100 for t in trades)
    total_pnl_pct = (total_pnl_amount / total_invested * 100) if total_invested > 0 else 0
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)
    total = len(trades)

    summary = DashSummary(
        invested=total_invested,
        pnl=total_pnl_amount,
        pnl_percent=total_pnl_pct,
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=(wins / total * 100) if total > 0 else 0,
    )

    return DashResponse(
        trades=list(trades)[:10],
        summary=summary,
        last_postmortem=snap["last_postmortem"],
        recent_rules=snap["recent_rules"],
        events=snap["events"],
        provider=settings.llm_provider.value,
        entries=store.count(),
    )


@router.get("/services", response_model=dict)
async def services_status(settings: Settings = Depends(get_settings)):
    status = {
        "memory": {"online": True, "port": 8000},
        "redis": {"online": False, "port": 6379},
        "engine": {"online": False, "port": 9001},
        "orchestrator": {"online": False, "port": 8080},
        "llm": {"online": True, "provider": settings.llm_provider.value},
    }
    try:
        import socket, os
        hosts = ["redis", "localhost"] if os.getenv("DOCKER_MODE") else ["localhost"]
        for host in hosts:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                if s.connect_ex((host, 6379)) == 0:
                    status["redis"]["online"] = True
                    break
                s.close()
            except Exception:
                pass
    except Exception:
        pass
    try:
        import socket, os
        hosts = ["engine", "localhost"] if os.getenv("DOCKER_MODE") else ["localhost"]
        for host in hosts:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                if s.connect_ex((host, 9001)) == 0:
                    status["engine"]["online"] = True
                    break
                s.close()
            except Exception:
                pass
    except Exception:
        pass
    try:
        import socket, os
        hosts = ["orchestrator", "localhost"] if os.getenv("DOCKER_MODE") else ["localhost"]
        for host in hosts:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                if s.connect_ex((host, 8080)) == 0:
                    status["orchestrator"]["online"] = True
                    break
                s.close()
            except Exception:
                pass
    except Exception:
        pass
    return status


@router.get("/quote/{ticker}", response_model=dict)
async def quote(ticker: str):
    bridge = get_bridge()
    if bridge is None:
        raise HTTPException(status_code=503, detail="Market data bridge not ready")
    q = bridge.get_latest(ticker.upper())
    if q is None:
        raise HTTPException(status_code=404, detail=f"No data for {ticker}")
    return q["data"]


@router.get("/health", response_model=HealthResponse)
async def health(
    store: VectorStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    return HealthResponse(status="ok", entries=store.count(), provider=settings.llm_provider.value)


@router.post("/dash/trade", response_model=dict)
async def log_trade(trade: DashTrade, store: VectorStore = Depends(get_store)):
    event_store.add_trade(trade)

    # SEBI audit trail
    store.audit_log("trade", trade.ticker, trade.model_dump())

    # Persist to PostgreSQL
    try:
        from . import db
        await db.log_trade(
            trade.ticker, trade.dir, trade.qty, trade.entry_price,
            getattr(trade, 'exit_price', getattr(trade, 'entry_price', 0)),
            trade.pnl or 0, trade.status, "",
        )
    except Exception as e:
        logger.warning(f"DB trade log skipped: {e}")

    notional = trade.entry_price * trade.qty
    try:
        if trade.dir.upper() in ("BUY", "LONG"):
            wallet_instance.open_position(trade.ticker, trade.qty, trade.entry_price, "LONG")
        elif trade.dir.upper() in ("SELL", "SHORT"):
            wallet_instance.close_position(trade.ticker, trade.qty, trade.entry_price)
    except ValueError as e:
        logger.warning(f"Wallet update skipped: {e}")

    event_store.add_event(f"Trade: {trade.ticker} {trade.dir} {trade.pnl:+.2f}% [{trade.status}]")
    return {"ok": True}


@router.get("/wallet", response_model=dict)
async def wallet_status():
    return wallet_instance.snapshot()


@router.post("/wallet/reset", response_model=dict)
async def wallet_reset(capital: float = 100_000):
    global wallet_instance
    from .wallet import Wallet
    wallet_instance = Wallet(initial_capital=capital)
    return wallet_instance.snapshot()


@router.post("/advocate", response_model=dict)
async def advocate_check(request: dict, advocate: DevilsAdvocate = Depends(get_advocate)):
    return advocate.argue(request)


@router.post("/sentiment", response_model=dict)
async def sentiment_analysis(request: dict, agent: SentimentAgent = Depends(get_sentiment)):
    return agent.analyze(
        ticker=request.get("ticker", ""),
        sector=request.get("sector", "General"),
        context=request.get("context", ""),
    )


@router.post("/macro", response_model=dict)
async def macro_analysis(request: dict, agent: MacroAnalyst = Depends(get_macro)):
    return agent.analyze(context=request.get("context", ""))


# === Settings ===

@router.get("/settings", response_model=dict)
async def get_settings():
    return settings_store.current()


@router.post("/settings", response_model=dict)
async def save_settings(data: dict):
    cfg = settings_store.save(data)
    return {"ok": True, "settings": cfg}


# === Ticker Discovery ===

@router.post("/tickers/discover", response_model=dict)
async def discover_tickers(
    count: int = 10,
    researcher: ResearcherAgent = Depends(get_researcher),
):
    from .market_data import _add_tickers
    tickers = researcher.discover_tickers(count)
    if tickers:
        _add_tickers(tickers)
    return {"tickers": tickers, "added": len(tickers)}


# === News ===

@router.get("/news", response_model=dict)
async def get_news(ticker: str = ""):
    if ticker:
        items = news_scraper.get_news_for_ticker(ticker, limit=10)
    else:
        items = news_scraper.get_latest_news(limit=20)
    return {"ticker": ticker, "count": len(items), "items": items}


@router.post("/news/refresh", response_model=dict)
async def refresh_news():
    items = await news_scraper.fetch_all_news()
    return {"count": len(items), "items": items[:5]}


# === History (PostgreSQL) ===

@router.get("/history", response_model=dict)
async def trade_history(ticker: str = "", limit: int = 50):
    from . import db
    trades = await db.get_trades(limit=limit, ticker=ticker)
    summary = await db.get_summary(ticker=ticker)
    return {"trades": trades, "summary": summary, "ticker": ticker}


# === Indicators (debug) ===

@router.get("/indicators/{ticker}", response_model=dict)
async def get_indicators(ticker: str):
    from .main import strategy
    return strategy.get_indicators(ticker.upper())

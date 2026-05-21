import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse

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
from .llm.providers import check_llm_health, get_available_providers, get_active_provider

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
    from .vector_store import get_vector_store
    return get_vector_store(settings)


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
    from .db import get_summary
    snap = event_store.snapshot()
    trades = snap["trades"]

    total_invested = sum(t.entry_price * t.qty for t in trades)
    total_pnl_amount = sum(t.entry_price * t.qty * t.pnl / 100 for t in trades)
    total_pnl_pct = (total_pnl_amount / total_invested * 100) if total_invested > 0 else 0
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)
    total = len(trades)

    # Merge with real wallet/DB data if in-memory is empty
    if total == 0:
        try:
            from .wallet import wallet as w
            db_summary = await get_summary()
            total = db_summary.get("total_trades", 0)
            wins = db_summary.get("wins", 0)
            losses = db_summary.get("losses", 0)
            # Use wallet for equity (same source as report page)
            snap_w = w.snapshot()
            total_invested = snap_w.get("initial_capital", 100000)
            total_pnl_amount = snap_w.get("total_pnl", 0)
            total_pnl_pct = snap_w.get("total_pnl_pct", 0)
        except Exception:
            pass

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


@router.get("/dash/all", response_model=dict)
async def dash_all(store: VectorStore = Depends(get_store), settings: Settings = Depends(get_settings)):
    """Single endpoint returning dash + wallet + services — 1 round-trip instead of 3."""
    # Dash data (same as /dash)
    snap = event_store.snapshot()
    trades = snap["trades"]
    total_invested = sum(t.entry_price * t.qty for t in trades)
    total_pnl_amount = sum(t.entry_price * t.qty * t.pnl / 100 for t in trades)

    # Wallet
    snap_w = wallet_instance.snapshot()

    # Merge with DB if in-memory is empty
    total = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl <= 0)
    if total == 0:
        try:
            from .db import get_summary
            db_summary = await get_summary()
            total = db_summary.get("total_trades", 0)
            wins = db_summary.get("wins", 0)
            losses = db_summary.get("losses", 0)
            total_invested = snap_w.get("initial_capital", 100000)
            total_pnl_amount = snap_w.get("total_pnl", 0)
        except Exception:
            pass

    return {
        "dash": {
            "trades": [t.model_dump() for t in list(trades)[:10]],
            "summary": {
                "invested": total_invested,
                "pnl": total_pnl_amount,
                "pnl_percent": (total_pnl_amount / total_invested * 100) if total_invested > 0 else 0,
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": (wins / total * 100) if total > 0 else 0,
            },
            "last_postmortem": snap["last_postmortem"],
            "events": [e.model_dump() for e in snap["events"][:5]],
            "provider": settings.llm_provider.value,
        },
        "wallet": snap_w,
        "services": await services_status(settings=settings),
    }


@router.get("/services", response_model=dict)
async def services_status(settings: Settings = Depends(get_settings)):
    import socket, os

    def _check_port(host: str, port: int) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            result = s.connect_ex((host, port)) == 0
            s.close()
            return result
        except Exception:
            return False

    async def _check_service(name: str, port: int) -> bool:
        hosts = [name, "localhost"] if os.getenv("DOCKER_MODE") else ["localhost"]
        for host in hosts:
            online = await asyncio.to_thread(_check_port, host, port)
            if online:
                return True
        return False

    redis_ok, engine_ok, orchestrator_ok = await asyncio.gather(
        _check_service("redis", 6379),
        _check_service("engine", 9001),
        _check_service("orchestrator", 8080),
        return_exceptions=True,
    )

    return {
        "memory": {"online": True, "port": 8000},
        "redis": {"online": bool(redis_ok), "port": 6379},
        "engine": {"online": bool(engine_ok), "port": 9001},
        "orchestrator": {"online": bool(orchestrator_ok), "port": 8080},
        "llm": {"online": True, "provider": settings.llm_provider.value},
    }


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
            trade.pnl or 0, trade.status, getattr(trade, 'reason', '') or '',
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
    from . import db
    wallet_instance = Wallet(initial_capital=capital)
    # Persist reset to DB so restart doesn't reload old state
    try:
        await db.save_wallet(capital, capital, 0.0, 0.0, {})
    except Exception as e:
        logger.warning(f"Wallet reset DB save skipped: {e}")
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


# === Watchlist ===

@router.get("/watchlist", response_model=dict)
async def get_watchlist():
    from .market_data import NSE_TICKERS
    return {
        "tickers": [t.replace(".NS", "").replace(".BO", "") for t in NSE_TICKERS]
    }


# === AI Research Analysis ===

@router.get("/research/analyze/{ticker}", response_model=dict)
async def ai_research_analysis(
    ticker: str,
    researcher: ResearcherAgent = Depends(get_researcher),
):
    from .main import strategy as strategy_agent
    from . import news_scraper, options_flow

    ticker_upper = ticker.upper()
    ticker_ns = ticker_upper + ".NS" if not ticker_upper.endswith(".NS") else ticker_upper

    ind = strategy_agent.get_indicators(ticker_upper)
    news_items = news_scraper.get_news_for_ticker(ticker_upper, limit=5)
    opt = options_flow.get_option_sentiment(ticker_upper)
    market_pcr = options_flow.get_market_pcr()

    reg = ind.get("regime", {})
    macd = ind.get("macd", {})
    bb = ind.get("bb", {})
    rsi_mtf = ind.get("rsi_mtf", {})

    tech_context = (
        f"Price: ₹{ind.get('price', 0)} ({ind.get('change_pct', 0):.2f}%)\n"
        f"RSI: 1m={ind.get('rsi', '--')}, 5m={rsi_mtf.get('5m', '--')}, 15m={rsi_mtf.get('15m', '--')}\n"
        f"MACD: line={macd.get('line', '--')}, signal={macd.get('signal', '--')}, hist={macd.get('histogram', '--')}\n"
        f"Bollinger: lower={bb.get('lower', '--')}, mid={bb.get('mid', '--')}, upper={bb.get('upper', '--')}\n"
        f"Regime: {reg.get('regime', '--')}, ADX={reg.get('adx', '--')}, Volatility={reg.get('volatility', '--')}, ATR%={reg.get('atr_pct', '--')}\n"
        f"Momentum 5d: {ind.get('momentum_5', 0)}%"
    )

    news_context = "\n".join([f"- {n['title']}" for n in news_items[:5]]) if news_items else "No recent news."
    pcr_context = f"Market PCR: {market_pcr.get('pcr', 'N/A')}, Sentiment: {market_pcr.get('sentiment', 'neutral')}"
    ticker_opt = f"Ticker Options: {opt.get('status', 'no_data')}"

    context = f"Technical Analysis:\n{tech_context}\n\nRecent News:\n{news_context}\n\nOptions Data:\n{pcr_context}\n{ticker_opt}"

    result = researcher.analyze(ResearchRequest(
        ticker=ticker_upper,
        sector="N/A",
        context=context,
    ))

    return {
        "ticker": ticker_upper,
        "price": ind.get("price"),
        "change_pct": ind.get("change_pct"),
        "indicators": ind,
        "news": news_items[:5],
        "options": {**opt, "market_pcr": market_pcr},
        "ai": {
            "sentiment": result.sentiment.value,
            "confidence": result.confidence,
            "summary": result.summary,
            "key_factors": result.key_factors,
            "risk_flags": result.risk_flags,
            "recommendation": result.trade_recommendation,
            "reasoning": result.reasoning,
        }
    }


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
        items = news_scraper.get_latest_news(limit=50)
    return {"ticker": ticker, "count": len(items), "items": items}


@router.post("/news/refresh", response_model=dict)
async def refresh_news():
    items = await news_scraper.fetch_all_news()
    return {"count": len(items), "items": items[:5]}


# === LLM Health ===

@router.get("/llm/check", response_model=dict)
async def llm_health():
    health = check_llm_health()
    available = get_available_providers()
    active = get_active_provider()
    return {"providers": health, "available": available, "active": active, "total_configured": len(available)}


@router.get("/llm/traces", response_model=dict)
async def llm_traces(limit: int = 100):
    from .llm.providers import get_traces_with_db
    traces = await get_traces_with_db(limit)
    # Aggregate stats
    agents = {}
    total_calls = len(traces)
    total_ok = sum(1 for t in traces if t["success"])
    total_prompt = sum(t["prompt_tokens_est"] for t in traces)
    total_response = sum(t["response_tokens_est"] for t in traces)
    for t in traces:
        a = t["agent"]
        if a not in agents:
            agents[a] = {"calls": 0, "errors": 0, "prompt_tokens": 0, "response_tokens": 0, "total_latency_ms": 0}
        agents[a]["calls"] += 1
        if not t["success"]:
            agents[a]["errors"] += 1
        agents[a]["prompt_tokens"] += t["prompt_tokens_est"]
        agents[a]["response_tokens"] += t["response_tokens_est"]
        agents[a]["total_latency_ms"] += t["latency_ms"]
    for a in agents:
        agents[a]["avg_latency_ms"] = round(agents[a]["total_latency_ms"] / agents[a]["calls"], 1)
    return {
        "summary": {
            "total_calls": total_calls,
            "success": total_ok,
            "errors": total_calls - total_ok,
            "prompt_tokens_est": total_prompt,
            "response_tokens_est": total_response,
        },
        "by_agent": agents,
        "traces": traces,
    }


# === History (PostgreSQL) ===

@router.get("/history", response_model=dict)
async def trade_history(ticker: str = "", limit: int = 50):
    from . import db
    trades = await db.get_trades(limit=limit, ticker=ticker)
    summary = await db.get_summary(ticker=ticker)
    return {"trades": trades, "summary": summary, "ticker": ticker}


# === Daily Report ===

@router.get("/report/daily", response_model=dict)
async def daily_report(days: int = 30):
    from . import db as _db
    from .wallet import wallet as w

    summaries = await _db.get_daily_summaries(days)
    equity = await _db.get_daily_equity_curve(days)

    total_pnl = sum(s["pnl"] for s in summaries)
    total_trades = sum(s["total_trades"] for s in summaries)
    total_wins = sum(s["wins"] for s in summaries)
    total_losses = sum(s["losses"] for s in summaries)

    snap = w.snapshot()
    today_summary = next((s for s in summaries if s["date"] == datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")), None)

    return {
        "current_equity": snap["total_equity"],
        "current_pnl": snap["total_pnl"],
        "current_pnl_pct": snap["total_pnl_pct"],
        "initial_capital": snap["initial_capital"],
        "overall": {
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round((total_wins / total_trades * 100) if total_trades > 0 else 0, 1),
            "total_pnl": round(total_pnl, 2),
            "best_day": max(summaries, key=lambda s: s["pnl"]) if summaries else None,
            "worst_day": min(summaries, key=lambda s: s["pnl"]) if summaries else None,
        },
        "today": today_summary,
        "daily_history": summaries,
        "equity_curve": equity,
        "tickers": await _db.get_ticker_stats(days),
        "hourly": await _db.get_hourly_stats(days),
        "strategies": await _db.get_strategy_stats(days),
        "weekly": await _db.get_weekly_summary(12),
        "drawdown": max((e.get("drawdown_pct", 0) for e in equity), default=0),
    }


@router.get("/report/day/{date}")
async def day_detail(date: str):
    from . import db as _db
    return JSONResponse(content=await _db.get_day_detail(date))


# === Indicators (debug) ===

@router.get("/indicators/{ticker}", response_model=dict)
async def get_indicators(ticker: str):
    from .main import strategy
    return strategy.get_indicators(ticker.upper())


# === Backtesting ===

@router.post("/backtest", response_model=dict)
async def run_backtest(request: dict):
    from .backtest import BacktestEngine
    from .settings_store import current as get_settings

    cfg = get_settings()
    tickers_raw = request.get("tickers", cfg.get("tickers", "RELIANCE.NS,TCS.NS"))
    tickers = [t.strip() for t in tickers_raw.split(",") if t.strip()][:10]
    period = request.get("period", "6mo")
    interval = request.get("interval", "1h")

    engine = BacktestEngine(
        initial_capital=float(request.get("initial_capital", cfg.get("initial_capital", 100000))),
        max_positions=int(request.get("max_positions", cfg.get("max_positions", 3))),
        position_size_pct=float(request.get("position_size_pct", cfg.get("position_size_pct", 5))),
        take_profit_pct=float(request.get("take_profit_pct", cfg.get("take_profit_pct", 2.0))),
        stop_loss_pct=float(request.get("stop_loss_pct", cfg.get("stop_loss_pct", 3.0))),
        rsi_period=int(request.get("rsi_period", cfg.get("rsi_period", 14))),
        rsi_oversold=float(request.get("rsi_oversold", cfg.get("rsi_oversold", 55))),
        rsi_overbought=float(request.get("rsi_overbought", cfg.get("rsi_overbought", 70))),
    )

    result = await asyncio.to_thread(engine.run, tickers, period, interval)
    result["params"] = {"tickers": tickers, "period": period, "interval": interval}
    return result


@router.get("/llm/bedrock-models", response_model=dict)
async def bedrock_models():
    """List available Bedrock ON_DEMAND models grouped by provider."""
    try:
        import boto3
        from .config import get_settings
        settings = get_settings()
        client = boto3.client(
            "bedrock",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        models = []
        resp = client.list_foundation_models()
        for m in resp.get("modelSummaries", []):
                status = m.get("modelLifecycle", {}).get("status", "")
                if status != "ACTIVE":
                    continue
                types = m.get("inferenceTypesSupported", [])
                if "ON_DEMAND" not in types:
                    continue
                mid = m["modelId"]
                provider = m.get("providerName", "Other")
                # Short label
                label = mid.replace(".", " ").replace("-", " ").replace(":", "")
                label = " ".join(w.capitalize() if i == 0 else w for i, w in enumerate(label.split()))[:40]
                models.append({
                    "id": mid,
                    "label": label,
                    "provider": provider,
                    "provider_short": provider.split()[0],
                })
        # Sort by provider then model
        models.sort(key=lambda x: (x["provider"], x["id"]))
        providers = sorted(set(m["provider_short"] for m in models))
        return {"models": models, "providers": providers, "count": len(models)}
    except Exception as e:
        return {"models": [], "providers": [], "count": 0, "error": str(e)}


# === Options Flow ===

@router.get("/options/{ticker}", response_model=dict)
async def option_sentiment(ticker: str):
    from .options_flow import get_option_sentiment, get_market_pcr
    sentiment = get_option_sentiment(ticker.upper())
    pcr = get_market_pcr()
    sentiment["market_pcr"] = pcr
    return sentiment


@router.post("/options/scan", response_model=dict)
async def scan_options(request: dict):
    from .options_flow import scan_ticker_options
    tickers = request.get("tickers", "RELIANCE.NS,TCS.NS")
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    results = {}
    for t in ticker_list:
        r = await scan_ticker_options(t)
        if r:
            results[t] = r
    return {"scanned": len(results), "results": results}


# === AI Optimizer ===

@router.post("/optimize", response_model=dict)
async def optimize_strategy(
    request: dict,
    background_tasks: BackgroundTasks,
):
    from .optimizer import OptimizerAgent
    from .db import get_trades
    from .settings_store import current as get_config
    from .config import get_settings

    settings = get_settings()
    days = request.get("days", 7)
    trades = await get_trades(limit=500)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [t for t in trades if t.get("time") and t["time"] > cutoff.isoformat()]

    if not recent:
        return {"trades_analyzed": 0, "period_days": days, "optimization": {"analysis": {"main_issue": "No recent trades"}, "suggestions": [], "confidence": 0}}

    current_params = get_config()
    background_tasks.add_task(_run_optimizer, recent, current_params, days)

    return {
        "trades_analyzed": len(recent),
        "period_days": days,
        "optimization": {"analysis": {"main_issue": "Optimization running in background..."}, "suggestions": [], "confidence": 0},
    }


async def _run_optimizer(recent: list, current_params: dict, days: int):
    from .optimizer import OptimizerAgent
    from .config import get_settings
    from .optimizer_bridge import optimizer_bridge

    settings = get_settings()
    agent = OptimizerAgent(settings)
    try:
        result = await agent.analyze_week(recent, current_params)
        suggestions = result.get("suggestions", [])
        if suggestions:
            _recommendations.clear()
            for s in suggestions:
                _recommendations.append({
                    "parameter": s.get("parameter"),
                    "current": s.get("current"),
                    "suggested": s.get("suggested"),
                    "reason": s.get("reason", ""),
                    "status": "pending",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        optimizer_bridge.push(result)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background optimizer failed: {e}")
        optimizer_bridge.push({"analysis": {"main_issue": f"Error: {str(e)}"}, "suggestions": [], "confidence": 0})


# === Recommendations (approve/reject optimizer suggestions) ===

_recommendations: list[dict] = []


@router.get("/recommendations", response_model=dict)
async def get_recommendations():
    return {"recommendations": _recommendations}


@router.post("/recommendations/approve", response_model=dict)
async def approve_recommendation(request: dict):
    idx = request.get("index", -1)
    if 0 <= idx < len(_recommendations):
        rec = _recommendations[idx]
        rec["status"] = "approved"
        param = rec.get("parameter")
        suggested = rec.get("suggested")
        if param and suggested is not None:
            cfg = settings_store.current()
            cfg[param] = suggested
            settings_store.save(cfg)
            logger.info(f"Applied recommendation: {param} = {suggested}")
        return {"ok": True, "recommendation": rec}
    return {"ok": False, "error": "Invalid index"}


@router.post("/recommendations/reject", response_model=dict)
async def reject_recommendation(request: dict):
    idx = request.get("index", -1)
    if 0 <= idx < len(_recommendations):
        _recommendations[idx]["status"] = "rejected"
        return {"ok": True, "recommendation": _recommendations[idx]}
    return {"ok": False, "error": "Invalid index"}


@router.post("/recommendations/approve-all", response_model=dict)
async def approve_all_recommendations():
    applied = 0
    cfg = settings_store.current()
    for rec in _recommendations:
        if rec.get("status") == "pending":
            param = rec.get("parameter")
            suggested = rec.get("suggested")
            if param and suggested is not None:
                cfg[param] = suggested
                rec["status"] = "approved"
                applied += 1
    if applied > 0:
        settings_store.save(cfg)
        logger.info(f"Applied {applied} recommendations")
    return {"ok": True, "applied": applied}


# === Strategy Debug Status ===

@router.get("/strategy/status", response_model=dict)
async def strategy_status():
    """Debug endpoint: shows why signals are/aren't firing, guard states, and trading conditions."""
    from .main import strategy as strat
    from .wallet import wallet as w
    import time

    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    market_open = strat._is_market_open()
    loop_now = asyncio.get_event_loop().time()

    # Per-ticker signal readiness
    ticker_status = {}
    for ticker, prices in strat.price_history.items():
        n = len(prices)
        current = prices[-1] if n > 0 else 0
        rsi = strat._calc_rsi(list(prices)) if n >= 2 else 50
        last_sig = strat.last_signal.get(ticker, 0)
        cooldown_remaining = max(0, strat.signal_cooldown - (loop_now - last_sig)) if last_sig > 0 else 0

        in_position = ticker in w.positions
        pos_pnl = 0.0
        if in_position:
            pos = w.positions[ticker]
            pos_pnl = ((current - pos.avg_price) / pos.avg_price * 100) if pos.avg_price > 0 else 0

        ticker_status[ticker] = {
            "data_points": n,
            "min_required": strat.rsi_period,
            "ready": n >= strat.rsi_period,
            "last_price": round(current, 2),
            "rsi": round(rsi, 1),
            "rsi_oversold_threshold": strat.rsi_oversold,
            "rsi_overbought_threshold": strat.rsi_overbought,
            "in_position": in_position,
            "position_pnl_pct": round(pos_pnl, 2),
            "last_signal_sec_ago": round(loop_now - last_sig, 1) if last_sig > 0 else None,
            "cooldown_remaining_sec": round(cooldown_remaining, 1),
        }

    wallet = w.snapshot()

    return {
        "timestamp": ist.isoformat(),
        "market": {
            "is_open": market_open,
            "day": ist.strftime("%A"),
            "hour": ist.hour,
            "minute": ist.minute,
        },
        "wallet": {
            "equity": round(wallet["total_equity"], 2),
            "available": round(wallet["available"], 2),
            "invested": round(wallet["invested"], 2),
            "pnl": round(wallet["total_pnl"], 2),
            "pnl_pct": round(wallet["total_pnl_pct"], 2),
            "positions_open": len(wallet.get("positions", {})),
            "max_positions": strat.max_positions,
        },
        "risk_gates": {
            "consecutive_losses": strat._consecutive_losses,
            "loss_cooldown_active": strat._loss_cooldown_until > 0,
            "loss_cooldown_remaining_sec": round(max(0, strat._loss_cooldown_until - loop_now), 1) if strat._loss_cooldown_until > 0 else 0,
            "daily_loss_pct": round(strat._daily_loss, 2),
            "daily_loss_limit_pct": strat.daily_loss_limit_pct,
        },
        "tickers": ticker_status,
        "signal_config": {
            "rsi_oversold": strat.rsi_oversold,
            "rsi_overbought": strat.rsi_overbought,
            "min_drop_pct": strat.min_drop_pct,
            "signal_cooldown_sec": strat.signal_cooldown,
            "force_trade_sec": strat.force_trade_sec,
            "short_enabled": strat.short_enabled,
            "take_profit_pct": strat.take_profit_pct,
            "stop_loss_pct": strat.stop_loss_pct,
        },
    }

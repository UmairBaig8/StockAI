import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from pathlib import Path
from contextlib import asynccontextmanager
import time

from .config import get_settings
from .market_data import MarketDataBridge
from .router import router, set_bridge
from .strategy import StrategyAgent
from .news_scraper import start_news_poller
from .options_flow import options_poller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bridge = MarketDataBridge()
set_bridge(bridge)
strategy = StrategyAgent()
bridge.callbacks.append(strategy.feed_quote)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .wallet import wallet as w
    await w.load_from_db()
    asyncio.create_task(bridge.start())
    asyncio.create_task(strategy.run())
    asyncio.create_task(start_news_poller(900))
    asyncio.create_task(options_poller(1800))  # Options every 30 min
    logger.info("StockAI Memory Service ready (market + strategy + news + critic + memory)")
    yield
    bridge.stop()
    logger.info("StockAI Memory Service shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="StockAI Memory Service",
        version="0.3.0",
        description="Auto-trading strategy + market data + critic + vector memory",
        lifespan=lifespan,
    )

    app.include_router(router, prefix="/api/v1")

    # SEBI audit: log every API action
    @app.middleware("http")
    async def audit_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        if request.url.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
            try:
                from .vector_store import vector_store
                body = await request.body()
                payload = body.decode()[:500] if body else ""
                vector_store.audit_log(
                    f"api_{request.method.lower()}",
                    request.url.path.split("/")[-1][:20],
                    {"path": request.url.path, "method": request.method, "status": response.status_code, "duration_ms": round(duration*1000)},
                )
            except Exception:
                pass
        return response

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dash_path = Path(__file__).parent / "templates" / "dashboard.html"
        return dash_path.read_text()

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page():
        settings_path = Path(__file__).parent / "templates" / "settings.html"
        return settings_path.read_text()

    @app.get("/news", response_class=HTMLResponse)
    async def news_page():
        return (Path(__file__).parent / "templates" / "news.html").read_text()

    @app.get("/research", response_class=HTMLResponse)
    async def research_page():
        return (Path(__file__).parent / "templates" / "research.html").read_text()

    @app.get("/history", response_class=HTMLResponse)
    async def history_page():
        return (Path(__file__).parent / "templates" / "history.html").read_text()

    @app.get("/backtest", response_class=HTMLResponse)
    async def backtest_page():
        return (Path(__file__).parent / "templates" / "backtest.html").read_text()

    @app.get("/report", response_class=HTMLResponse)
    async def report_page():
        return (Path(__file__).parent / "templates" / "report.html").read_text()

    @app.get("/llm", response_class=HTMLResponse)
    async def llm_page():
        return (Path(__file__).parent / "templates" / "llm.html").read_text()

    @app.get("/base.css", response_class=Response)
    async def base_css():
        css = (Path(__file__).parent / "templates" / "base.css").read_text()
        return Response(content=css, media_type="text/css")

    @app.get("/favicon.ico")
    async def favicon():
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="4" fill="#0b0b10"/><text x="16" y="22" text-anchor="middle" fill="#00ff88" font-family="monospace" font-size="18" font-weight="bold">S</text></svg>'
        return Response(content=svg, media_type="image/svg+xml")

    @app.websocket("/ws/market")
    async def market_ws(ws: WebSocket):
        await ws.accept()
        bridge.add_client(ws)
        logger.info(f"Market data client connected (total: {len(bridge.clients)})")
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            bridge.remove_client(ws)
            logger.info(f"Market data client disconnected (total: {len(bridge.clients)})")

    @app.post("/orders")
    async def place_order(request: Request):
        import uuid
        body = await request.json()
        ticker = body.get("ticker", "?")
        side = body.get("side", "?")
        qty = body.get("quantity", 0)
        order_id = str(uuid.uuid4())[:8]
        logger.info(f"Paper order: {ticker} {side} qty={qty} id={order_id}")
        return JSONResponse({"order_id": order_id, "status": "Open", "message": "Order accepted"})

    @app.delete("/orders/{order_id}")
    async def cancel_order(order_id: str):
        return JSONResponse({"order_id": order_id, "status": "Cancelled", "message": "Order cancelled"})

    return app


app = create_app()

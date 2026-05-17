import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from pathlib import Path
from contextlib import asynccontextmanager

from .config import get_settings
from .market_data import MarketDataBridge
from .router import router
from .strategy import StrategyAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bridge = MarketDataBridge()
strategy = StrategyAgent()
bridge.callbacks.append(strategy.feed_quote)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(bridge.start())
    asyncio.create_task(strategy.run())
    logger.info("StockAI Memory Service ready (market + strategy + critic + memory)")
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

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        dash_path = Path(__file__).parent / "templates" / "dashboard.html"
        return dash_path.read_text()

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

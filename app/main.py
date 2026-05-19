import asyncio
import logging
import re

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
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

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def render_page(template_name: str, title: str, active: str) -> str:
    raw = (TEMPLATE_DIR / template_name).read_text()
    if "{% block content %}" in raw:
        block = raw.split("{% block content %}", 1)[1]
        content, tail = block.split("{% endblock %}", 1)
        content += "\n" + "\n".join(re.findall(r"<script[\s\S]*?</script>", tail))
    else:
        match = re.search(r"<main[^>]*>([\s\S]*?)</main>", raw)
        content = match.group(1) if match else raw
        content += "\n" + "\n".join(re.findall(r"<script[\s\S]*?</script>", raw))
    content = content.replace("</body>", "").replace("</html>", "")
    links = [
        ("/", "Cockpit", "cockpit"),
        ("/research", "Research", "research"),
        ("/news", "News", "news"),
        ("/backtest", "Backtest", "backtest"),
        ("/history", "History", "history"),
        ("/report", "Report", "report"),
        ("/settings", "Settings", "settings"),
        ("/llm", "LLM", "llm"),
    ]
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for href, label, key in links
    )
    mobile_nav = nav
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="icon" href="/static/img/app-icon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/css/system.css">
</head>
<body>
  <a href="#main-content" class="skip-link">Skip to main content</a>
  <div class="app-shell">
    <aside class="sidebar" aria-label="Main navigation">
      <a class="brand" href="/"><img src="/static/img/app-icon.svg" alt="" width="28" height="28"><span>StockAI</span></a>
      {nav}
      <a href="http://3.85.55.232:8080" rel="noopener">2FA Relay</a>
    </aside>
    <div class="page-shell">
      <nav class="mobile-nav" aria-label="Mobile navigation">{mobile_nav}</nav>
      <main class="main" id="main-content">{content}</main>
    </div>
  </div>
  <div id="toast" class="toast success" style="display:none" role="alert" aria-live="polite"></div>
</body>
</html>"""


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
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
        return render_page("dashboard.html", "StockAI — Cockpit", "cockpit")

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page():
        return render_page("settings.html", "StockAI — Settings", "settings")

    @app.get("/news", response_class=HTMLResponse)
    async def news_page():
        return render_page("news.html", "StockAI — Market News", "news")

    @app.get("/research", response_class=HTMLResponse)
    async def research_page():
        return render_page("research.html", "StockAI — Research", "research")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page():
        return render_page("history.html", "StockAI — Trade History", "history")

    @app.get("/backtest", response_class=HTMLResponse)
    async def backtest_page():
        return render_page("backtest.html", "StockAI — Backtest", "backtest")

    @app.get("/report", response_class=HTMLResponse)
    async def report_page():
        return render_page("report.html", "StockAI — Daily Report", "report")

    @app.get("/llm", response_class=HTMLResponse)
    async def llm_page():
        return render_page("llm.html", "StockAI — LLM Providers", "llm")

    @app.get("/base.css", response_class=Response)
    async def base_css():
        css = (Path(__file__).parent / "templates" / "base.css").read_text()
        return Response(content=css, media_type="text/css")

    @app.get("/favicon.ico")
    async def favicon():
        svg = (STATIC_DIR / "img" / "app-icon.svg").read_text()
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

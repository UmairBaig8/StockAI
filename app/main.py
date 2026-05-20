import asyncio
import gzip
import json
import logging
import re
from functools import lru_cache

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
from contextlib import asynccontextmanager
import time

from .config import get_settings
from .llm import LLMProvider
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

_NAV_LINKS = [
    ("/", "Cockpit", "cockpit"),
    ("/research", "Research", "research"),
    ("/news", "News", "news"),
    ("/backtest", "Backtest", "backtest"),
    ("/history", "History", "history"),
    ("/report", "Report", "report"),
    ("/settings", "Settings", "settings"),
    ("/llm", "LLM", "llm"),
]


@lru_cache(maxsize=16)
def _cached_content(template_name: str) -> str:
    """Extract content block from template — cached to avoid disk I/O per request."""
    raw = (TEMPLATE_DIR / template_name).read_text()
    if "{% block content %}" in raw:
        block = raw.split("{% block content %}", 1)[1]
        content, tail = block.split("{% endblock %}", 1)
        content += "\n" + "\n".join(re.findall(r"<script[\s\S]*?</script>", tail))
    else:
        match = re.search(r"<main[^>]*>([\s\S]*?)</main>", raw)
        content = match.group(1) if match else raw
        content += "\n" + "\n".join(re.findall(r"<script[\s\S]*?</script>", raw))
    return content.replace("</body>", "").replace("</html>", "")


_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="28" height="28" role="img" aria-label="StockAI"><defs><linearGradient id="a" x1="12" y1="8" x2="52" y2="58"><stop stop-color="#00ff88"/><stop offset="1" stop-color="#52a8ff"/></linearGradient></defs><rect width="64" height="64" rx="18" fill="#0b0b10"/><path d="M17 43.5 27.5 33l7 6.8L48 20" fill="none" stroke="url(#a)" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 49h34" stroke="#263044" stroke-width="3" stroke-linecap="round"/><circle cx="48" cy="20" r="4" fill="#00ff88"/></svg>'


def render_page(template_name: str, title: str, active: str) -> str:
    content = _cached_content(template_name)
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for href, label, key in _NAV_LINKS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="icon" href="/static/img/app-icon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/css/system.css?v=3">
</head>
<body>
  <a href="#main-content" class="skip-link">Skip to main content</a>
  <div class="app-shell">
    <aside class="sidebar" aria-label="Main navigation">
      <a class="brand" href="/">{_ICON_SVG}<span>StockAI</span></a>
      {nav}
      <a href="http://52.91.29.172:8080" rel="noopener">2FA Relay</a>
    </aside>
    <div class="page-shell">
      <nav class="mobile-nav" aria-label="Mobile navigation">{nav}</nav>
      <main class="main" id="main-content">{content}</main>
    </div>
  </div>
  <div id="toast" class="toast success" style="display:none" role="alert" aria-live="polite"></div>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .wallet import wallet as w
    from .dashboard_bridge import services_bridge, dashboard_bridge, wallet_bridge
    await w.load_from_db()
    asyncio.create_task(bridge.start())
    asyncio.create_task(strategy.run())
    asyncio.create_task(start_news_poller(900))
    asyncio.create_task(options_poller(1800))
    asyncio.create_task(services_bridge.run())
    asyncio.create_task(dashboard_bridge.run())
    asyncio.create_task(wallet_bridge.run())
    logger.info("StockAI Memory Service ready (market + strategy + news + critic + memory)")
    yield
    bridge.stop()
    logger.info("StockAI Memory Service shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    # Bridge settings_store per-agent LLM overrides into config.Settings
    try:
        from .settings_store import load as load_store
        store = load_store()
        provider_map = {
            "critic": ("llm_critic_provider", "llm_critic_model"),
            "researcher": ("llm_researcher_provider", "llm_researcher_model"),
            "advocate": ("llm_advocate_provider", "llm_advocate_model"),
            "sentiment": ("llm_sentiment_provider", "llm_sentiment_model"),
            "macro": ("llm_macro_provider", "llm_macro_model"),
        }
        for agent, (prov_key, model_key) in provider_map.items():
            prov_val = store.get(prov_key, "").strip()
            if prov_val:
                try:
                    setattr(settings, f"{agent}_llm_provider", LLMProvider(prov_val))
                except ValueError:
                    pass
            model_val = store.get(model_key, "").strip()
            if model_val:
                setattr(settings, f"{agent}_llm_model", model_val)
    except Exception:
        pass

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

    # Gzip compression for text responses
    class GzipMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            accept = request.headers.get("accept-encoding", "")
            if "gzip" in accept and response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if any(t in content_type for t in ("text/", "json", "javascript", "css", "svg", "xml")):
                    body = b""
                    async for chunk in response.body_iterator:
                        body += chunk if isinstance(chunk, bytes) else chunk.encode()
                    if len(body) > 512:
                        compressed = gzip.compress(body, compresslevel=6)
                        if len(compressed) < len(body):
                            return Response(content=compressed, status_code=response.status_code,
                                headers={**response.headers, "content-encoding": "gzip", "content-length": str(len(compressed)), "vary": "Accept-Encoding"},
                                media_type=response.headers.get("content-type"))
            return response

    app.add_middleware(GzipMiddleware)

    # Cache headers for static assets
    @app.middleware("http")
    async def cache_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["Vary"] = "Accept-Encoding"
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

    @app.websocket("/ws/dashboard")
    async def dashboard_ws(ws: WebSocket):
        from .dashboard_bridge import dashboard_bridge as b
        await ws.accept()
        b.add(ws)
        await _ws_handler(ws, b, "dashboard")

    @app.websocket("/ws/services")
    async def services_ws(ws: WebSocket):
        from .dashboard_bridge import services_bridge as b
        await ws.accept()
        b.add(ws)
        await b.send_initial(ws)
        await _ws_listen(ws, b, "services")

    @app.websocket("/ws/wallet")
    async def wallet_ws(ws: WebSocket):
        from .dashboard_bridge import wallet_bridge as b
        await ws.accept()
        b.add(ws)
        await b.send_initial(ws)
        await _ws_listen(ws, b, "wallet")

    @app.websocket("/ws/optimizer")
    async def optimizer_ws(ws: WebSocket):
        from .optimizer_bridge import optimizer_bridge as b
        await ws.accept()
        b.add(ws)
        if b.last_result:
            await ws.send_text(json.dumps({"type": "optimizer", "result": b.last_result}))
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            b.remove(ws)

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


async def _ws_listen(ws: WebSocket, bridge, name: str):
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        bridge.remove(ws)
        logger.info(f"WS {name} client disconnected (total: {len(bridge.clients)})")


async def _ws_handler(ws: WebSocket, bridge, name: str):
    try:
        await bridge.send_initial(ws)
    except Exception:
        pass
    await _ws_listen(ws, bridge, name)


app = create_app()

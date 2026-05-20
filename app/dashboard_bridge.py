import asyncio
import json
import logging
import time

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class DashboardBridge:
    """Pushes live dashboard state to connected WebSocket clients on every trade/event."""

    def __init__(self):
        self.clients: list[WebSocket] = []
        self._dirty = False
        self._last_services: dict | None = None
        self._last_services_time = 0.0

    def add_client(self, ws: WebSocket):
        self.clients.append(ws)
        logger.info(f"Dashboard WS client connected (total: {len(self.clients)})")

    def remove_client(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)
            logger.info(f"Dashboard WS client disconnected (total: {len(self.clients)})")

    def mark_dirty(self):
        self._dirty = True

    async def start_broadcast_loop(self):
        """Background loop: pushes dashboard state to clients when dirty (max 200ms interval)."""
        logger.info("Dashboard broadcast loop started")
        while True:
            try:
                await asyncio.sleep(0.2)
                if not self._dirty or not self.clients:
                    continue
                self._dirty = False
                await self._broadcast()
            except Exception as e:
                logger.error(f"Dashboard broadcast loop error: {e}")

    async def _broadcast(self):
        try:
            state = await self._build_state()
        except Exception as e:
            logger.error(f"Dashboard _build_state failed: {e}")
            return
        payload = json.dumps(state)
        dead = []
        for ws in self.clients:
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=2.0)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_client(ws)

    async def send_initial(self, ws: WebSocket):
        """Send full state to a newly connected client. Never crashes the handler."""
        try:
            state = await self._build_state()
            await ws.send_text(json.dumps(state))
            logger.info(f"Dashboard initial state sent to client")
        except Exception as e:
            logger.error(f"Dashboard send_initial failed: {e}")

    async def _build_state(self) -> dict:
        from .events import store as event_store
        from .wallet import wallet as wallet_instance

        snap = event_store.snapshot()
        trades = snap["trades"]
        total_invested = sum(t.entry_price * t.qty for t in trades)
        total_pnl_amount = sum(t.entry_price * t.qty * t.pnl / 100 for t in trades)
        total = len(trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl <= 0)

        if total == 0:
            try:
                from .db import get_summary
                from .wallet import wallet as w
                db_summary = await get_summary()
                total = db_summary.get("total_trades", 0)
                wins = db_summary.get("wins", 0)
                losses = db_summary.get("losses", 0)
                snap_w = w.snapshot()
                total_invested = snap_w.get("initial_capital", 100000)
                total_pnl_amount = snap_w.get("total_pnl", 0)
            except Exception:
                pass

        wallet = wallet_instance.snapshot()
        services = await self._services_cached()

        return {
            "type": "dashboard",
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
                "events": [e.model_dump() for e in snap["events"][:5]],
                "last_postmortem": snap["last_postmortem"],
            },
            "wallet": wallet,
            "services": services,
        }

    async def _services_cached(self) -> dict:
        """Return cached service status (refreshed every 10s, avoids socket spam)."""
        now = time.monotonic()
        if self._last_services and (now - self._last_services_time) < 10:
            return self._last_services
        try:
            svc = await self._check_services()
        except Exception:
            svc = self._last_services or _default_services()
        self._last_services = svc
        self._last_services_time = now
        return svc

    async def _check_services(self) -> dict:
        import os
        docker = bool(os.getenv("DOCKER_MODE"))
        redis_ok, engine_ok, orch_ok = await asyncio.gather(
            asyncio.to_thread(_port_check, "redis" if docker else "localhost", 6379),
            asyncio.to_thread(_port_check, "engine" if docker else "localhost", 9001),
            asyncio.to_thread(_port_check, "orchestrator" if docker else "localhost", 8080),
            return_exceptions=True,
        )
        return {
            "memory": {"online": True, "port": 8000},
            "redis": {"online": bool(redis_ok), "port": 6379},
            "engine": {"online": bool(engine_ok), "port": 9001},
            "orchestrator": {"online": bool(orchestrator_ok), "port": 8080},
            "llm": {"online": True, "provider": "active"},
        }


def _port_check(host: str, port: int) -> bool:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        result = s.connect_ex((host, port)) == 0
        s.close()
        return result
    except Exception:
        return False


def _default_services() -> dict:
    return {
        "memory": {"online": True, "port": 8000},
        "redis": {"online": False, "port": 6379},
        "engine": {"online": False, "port": 9001},
        "orchestrator": {"online": False, "port": 8080},
        "llm": {"online": True, "provider": "active"},
    }


dashboard_bridge = DashboardBridge()

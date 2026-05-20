import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _check_sync(host: str, port: int) -> bool:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.15)
        result = s.connect_ex((host, port)) == 0
        s.close()
        return result
    except Exception:
        return False


class DashboardBridge:
    """Pushes live dashboard state to connected WebSocket clients on every trade/event."""

    def __init__(self):
        self.clients: list[WebSocket] = []
        self._dirty = False
        self._broadcast_task: asyncio.Task | None = None

    def add_client(self, ws: WebSocket):
        self.clients.append(ws)

    def remove_client(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    def mark_dirty(self):
        """Called by event_store / wallet when state changes. Triggers broadcast."""
        self._dirty = True

    async def start_broadcast_loop(self):
        """Background loop: pushes dashboard state to all clients when dirty, every 200ms max."""
        while True:
            await asyncio.sleep(0.2)
            if not self._dirty or not self.clients:
                continue
            self._dirty = False
            await self._broadcast()

    async def _broadcast(self):
        state = await self._build_state()
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
        """Send full state to a newly connected client."""
        state = await self._build_state()
        try:
            await ws.send_text(json.dumps(state))
        except Exception:
            pass

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

        # Merge with DB if in-memory is empty
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
        services = await self._service_status_async()

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

    async def _check_service_async(self, name: str, port: int) -> bool:
        import os
        hosts = [name, "localhost"] if os.getenv("DOCKER_MODE") else ["localhost"]
        for host in hosts:
            ok = await asyncio.to_thread(_check_sync, host, port)
            if ok:
                return True
        return False

    async def _service_status_async(self) -> dict:
        redis_ok, engine_ok, orch_ok = await asyncio.gather(
            self._check_service_async("redis", 6379),
            self._check_service_async("engine", 9001),
            self._check_service_async("orchestrator", 8080),
            return_exceptions=True,
        )
        return {
            "memory": {"online": True, "port": 8000},
            "redis": {"online": bool(redis_ok), "port": 6379},
            "engine": {"online": bool(engine_ok), "port": 9001},
            "orchestrator": {"online": bool(orchestrator_ok), "port": 8080},
            "llm": {"online": True, "provider": "active"},
        }


dashboard_bridge = DashboardBridge()

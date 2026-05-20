import asyncio
import json
import logging
import os
import socket
import time

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── Low-level helpers ──

_DOCKER = bool(os.getenv("DOCKER_MODE"))


def _port_check(host: str, port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        r = s.connect_ex((host, port)) == 0
        s.close()
        return r
    except Exception:
        return False


def _check_services_sync() -> dict:
    hosts = {
        "redis": ("redis" if _DOCKER else "localhost", 6379),
        "engine": ("engine" if _DOCKER else "localhost", 9001),
        "orchestrator": ("orchestrator" if _DOCKER else "localhost", 8080),
    }
    return {
        "memory": {"online": True, "port": 8000},
        "redis": {"online": _port_check(*hosts["redis"]), "port": 6379},
        "engine": {"online": _port_check(*hosts["engine"]), "port": 9001},
        "orchestrator": {"online": _port_check(*hosts["orchestrator"]), "port": 8080},
        "llm": {"online": True, "provider": "active"},
    }


# ── Service status bridge (periodic push every 5s) ──

class ServicesBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []

    def add(self, ws: WebSocket):
        self.clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def send_initial(self, ws: WebSocket):
        try:
            svc = await asyncio.to_thread(_check_services_sync)
            await ws.send_text(json.dumps({"type": "services", "services": svc}))
        except Exception as e:
            logger.error(f"ServicesBridge send_initial: {e}")

    async def run(self):
        logger.info("ServicesBridge loop started")
        last_state = None
        while True:
            await asyncio.sleep(30)
            if not self.clients:
                continue
            try:
                svc = await asyncio.to_thread(_check_services_sync)
                state_hash = json.dumps(svc, sort_keys=True)
                if state_hash == last_state:
                    continue
                last_state = state_hash
                payload = json.dumps({"type": "services", "services": svc})
            except Exception as e:
                logger.error(f"ServicesBridge check: {e}")
                continue
            dead = []
            for ws in self.clients:
                try:
                    await asyncio.wait_for(ws.send_text(payload), timeout=1.0)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove(ws)


# ── Dashboard data bridge (trades + equity + events on state change) ──

class DashboardDataBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self._dirty = False

    def add(self, ws: WebSocket):
        self.clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    def mark_dirty(self):
        self._dirty = True

    async def send_initial(self, ws: WebSocket):
        try:
            state = await self._build()
            await ws.send_text(json.dumps(state))
        except Exception as e:
            logger.error(f"DashboardBridge send_initial: {e}")

    async def run(self):
        logger.info("DashboardDataBridge loop started")
        last_push = 0.0
        last_payload = None
        while True:
            await asyncio.sleep(0.2)
            if not self.clients:
                continue
            now = asyncio.get_event_loop().time()
            if not self._dirty and (now - last_push) < 5.0:
                continue
            self._dirty = False
            last_push = now
            try:
                state = await self._build()
                payload = json.dumps(state)
                if payload == last_payload:
                    continue
                last_payload = payload
            except Exception as e:
                logger.error(f"DashboardBridge build: {e}")
                continue
            dead = []
            for ws in self.clients:
                try:
                    await asyncio.wait_for(ws.send_text(payload), timeout=1.0)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove(ws)

    async def _build(self) -> dict:
        from .events import store as event_store
        from .wallet import wallet as wallet_instance

        snap = event_store.snapshot()
        trades = snap["trades"]
        inv = sum(t.entry_price * t.qty for t in trades)
        pnl = sum(t.entry_price * t.qty * t.pnl / 100 for t in trades)
        n = len(trades)
        w = sum(1 for t in trades if t.pnl > 0)
        l = sum(1 for t in trades if t.pnl <= 0)

        if n == 0:
            try:
                from .db import get_summary
                s = await get_summary()
                n = s.get("total_trades", 0)
                w = s.get("wins", 0)
                l = s.get("losses", 0)
                snap_w = wallet_instance.snapshot()
                inv = snap_w.get("initial_capital", 100000)
                pnl = snap_w.get("total_pnl", 0)
            except Exception:
                pass

        return {
            "type": "dashboard",
            "dash": {
                "trades": [t.model_dump() for t in list(trades)[:10]],
                "summary": {
                    "invested": inv,
                    "pnl": pnl,
                    "pnl_percent": (pnl / inv * 100) if inv > 0 else 0,
                    "total_trades": n,
                    "wins": w,
                    "losses": l,
                    "win_rate": (w / n * 100) if n > 0 else 0,
                },
                "events": [e.model_dump() for e in snap["events"][:5]],
                "last_postmortem": snap["last_postmortem"],
            },
        }


# ── Wallet bridge (positions + P&L on change + periodic) ──

class WalletBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self._dirty = True  # initial push

    def add(self, ws: WebSocket):
        self.clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    def mark_dirty(self):
        self._dirty = True

    async def send_initial(self, ws: WebSocket):
        try:
            state = await self._build()
            await ws.send_text(json.dumps(state))
        except Exception as e:
            logger.error(f"WalletBridge send_initial: {e}")

    async def run(self):
        logger.info("WalletBridge loop started")
        while True:
            await asyncio.sleep(1)
            if not self.clients:
                continue
            if not self._dirty:
                continue
            self._dirty = False
            try:
                state = await self._build()
                payload = json.dumps(state)
            except Exception as e:
                logger.error(f"WalletBridge build: {e}")
                continue
            dead = []
            for ws in self.clients:
                try:
                    await asyncio.wait_for(ws.send_text(payload), timeout=1.0)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.remove(ws)

    async def _build(self) -> dict:
        from .wallet import wallet as wallet_instance
        w = wallet_instance.snapshot()
        return {"type": "wallet", "wallet": w}


# ── Global instances ──

services_bridge = ServicesBridge()
dashboard_bridge = DashboardDataBridge()
wallet_bridge = WalletBridge()

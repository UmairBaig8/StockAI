import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class OptimizerBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self.last_result = None

    def add(self, ws: WebSocket):
        self.clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    def push(self, result: dict):
        self.last_result = result
        payload = json.dumps({"type": "optimizer", "result": result})
        dead = []
        for ws in self.clients:
            try:
                import asyncio
                asyncio.create_task(ws.send_text(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)

optimizer_bridge = OptimizerBridge()

import json
import logging
import os
from pathlib import Path
from fastapi import WebSocket

logger = logging.getLogger(__name__)

OPTIMIZER_PATH = Path(os.getenv("OPTIMIZER_PATH", str(Path(__file__).parent.parent / "data" / "optimizer.json")))
OPTIMIZER_PATH.parent.mkdir(parents=True, exist_ok=True)


class OptimizerBridge:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self.last_result = None
        self._load()

    def _load(self):
        """Load last optimization result from JSON file."""
        try:
            if OPTIMIZER_PATH.exists():
                self.last_result = json.loads(OPTIMIZER_PATH.read_text())
                logger.info(f"Optimizer state loaded from {OPTIMIZER_PATH}")
        except Exception as e:
            logger.warning(f"Failed to load optimizer state: {e}")

    def _save(self):
        """Persist last optimization result to JSON file."""
        try:
            OPTIMIZER_PATH.write_text(json.dumps(self.last_result, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save optimizer state: {e}")

    def add(self, ws: WebSocket):
        self.clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    def push(self, result: dict):
        self.last_result = result
        self._save()
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

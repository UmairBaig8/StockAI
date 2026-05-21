import asyncio
from collections import deque
from datetime import datetime

from .models import DashEvent, DashTrade


class EventStore:
    def __init__(self, max_len: int = 50):
        self.trades: deque[DashTrade] = deque(maxlen=max_len)
        self.events: deque[DashEvent] = deque(maxlen=max_len)
        self.last_postmortem: str = ""
        self.recent_rules: deque[str] = deque(maxlen=10)

    def add_trade(self, trade: DashTrade):
        self.trades.appendleft(trade)
        self._persist_trade(trade)
        _notify_dashboard()

    def add_event(self, msg: str, level: str = "info", ticker: str = ""):
        self.events.appendleft(DashEvent(msg=msg, level=level))
        self._persist_event(msg, level, ticker)
        _notify_dashboard()

    def add_postmortem(self, rule: str):
        self.last_postmortem = datetime.utcnow().strftime("%H:%M:%S UTC")
        self.recent_rules.appendleft(rule)
        self._persist_postmortem(rule)
        _notify_dashboard()

    async def load_from_db(self):
        """Restore events from PostgreSQL on startup."""
        try:
            from .db import load_events, load_recent_rules
            db_events = await load_events(50)
            for e in reversed(db_events):
                if e.get("level") == "postmortem":
                    self.recent_rules.appendleft(e["msg"].replace("RULE: ", ""))
                else:
                    self.events.append(DashEvent(msg=e["msg"], level=e["level"]))
            rules = await load_recent_rules(10)
            self.recent_rules = deque(rules, maxlen=10)
            if self.recent_rules:
                self.last_postmortem = datetime.utcnow().strftime("%H:%M:%S UTC")
        except Exception as e:
            from . import logging as log
            log.getLogger(__name__).warning(f"Failed to load events from DB: {e}")

    def _persist_trade(self, trade: DashTrade):
        try:
            from .db import save_event
            asyncio.ensure_future(save_event(
                f"Trade: {trade.ticker} {trade.dir} @ {trade.entry_price:.2f} PnL={trade.pnl:+.2f}%",
                "trade",
                trade.ticker,
            ))
        except Exception:
            pass

    def _persist_event(self, msg: str, level: str, ticker: str = ""):
        try:
            from .db import save_event
            asyncio.ensure_future(save_event(msg, level, ticker))
        except Exception:
            pass

    def _persist_postmortem(self, rule: str):
        try:
            from .db import save_postmortem
            asyncio.ensure_future(save_postmortem(rule))
        except Exception:
            pass

    def snapshot(self) -> dict:
        return {
            "trades": list(self.trades)[:10],
            "events": list(self.events)[:5],
            "last_postmortem": self.last_postmortem,
            "recent_rules": list(self.recent_rules),
        }


def _notify_dashboard():
    try:
        from .dashboard_bridge import dashboard_bridge as b
        b.mark_dirty()
    except Exception:
        pass


store = EventStore()

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

    def add_event(self, msg: str, level: str = "info"):
        self.events.appendleft(DashEvent(msg=msg, level=level))

    def add_postmortem(self, rule: str):
        self.last_postmortem = datetime.utcnow().strftime("%H:%M:%S UTC")
        self.recent_rules.appendleft(rule)

    def snapshot(self) -> dict:
        return {
            "trades": list(self.trades)[:10],
            "events": list(self.events)[:5],
            "last_postmortem": self.last_postmortem,
            "recent_rules": list(self.recent_rules),
        }


store = EventStore()

import lancedb
import numpy as np
from pathlib import Path
from typing import Optional, List
import logging
from datetime import datetime, timezone

from .config import Settings
from .models import MemoryEntry, PreTradeResult, MarketState

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path = Path(settings.lance_db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.db_path))
        self._ensure_table()

    def _ensure_table(self):
        if "trading_memory" not in self.db.table_names():
            self.db.create_table(
                "trading_memory",
                [
                    {
                        "id": "init",
                        "ticker": "",
                        "vector": [0.0] * self.settings.vector_dim,
                        "payload": "{}",
                        "timestamp": "2026-01-01T00:00:00Z",
                    }
                ],
            )
        self.table = self.db.open_table("trading_memory")

        # Audit trail — SEBI 5-year compliant append-only log
        if "audit_trail" not in self.db.table_names():
            import pyarrow as pa
            self.db.create_table(
                "audit_trail",
                [{"event": "init", "ticker": "", "data": "{}", "timestamp": "2026-01-01T00:00:00Z"}],
            )
        self.audit = self.db.open_table("audit_trail")

    def store(self, entry: MemoryEntry) -> str:
        rows = [
            {
                "id": entry.id or f"{entry.ticker}-{entry.timestamp.timestamp()}",
                "ticker": entry.ticker,
                "vector": entry.market_vector,
                "payload": entry.model_dump_json(),
                "timestamp": entry.timestamp.isoformat(),
            }
        ]
        self.table.add(rows)
        logger.info(f"Stored memory: {entry.ticker} {entry.analysis.mistake_category}")
        return rows[0]["id"]

    def query(
        self, ticker: str, market_state: MarketState, limit: int = 5
    ) -> list[MemoryEntry]:
        query_vec = np.array(market_state.to_vector(), dtype=np.float32)
        try:
            results = (
                self.table.search(query_vec)
                .where(f"ticker = '{ticker}'", prefilter=True)
                .limit(limit)
                .to_list()
            )
        except Exception as e:
            logger.warning(f"Vector query fallback (no prefilter): {e}")
            results = self.table.search(query_vec).limit(limit).to_list()

        entries = []
        for r in results:
            dist = r.get("_distance", 1.0)
            try:
                entry = MemoryEntry.model_validate_json(r["payload"])
                entry.id = r.get("id")
                entries.append((dist, entry))
            except Exception as e:
                logger.error(f"Failed to parse entry: {e}")

        entries.sort(key=lambda x: x[0])
        return [e for _, e in entries]

    def pre_trade_check(self, ticker: str, market_state: MarketState) -> PreTradeResult:
        entries = self.query(ticker, market_state, limit=3)
        if not entries:
            return PreTradeResult(matched=False, similarity=0.0)

        best = entries[0]
        dist = self._distance(best.market_vector, market_state.to_vector())

        if dist <= self.settings.similarity_threshold:
            return PreTradeResult(
                matched=True,
                similarity=dist,
                correction_rule=best.evolutionary_overlay.correction_rule
                if best.evolutionary_overlay
                else None,
                past_mistake=best.analysis.root_cause if best.analysis else None,
            )
        return PreTradeResult(matched=False, similarity=dist)

    def _distance(self, a: list[float], b: list[float]) -> float:
        return float(np.linalg.norm(np.array(a) - np.array(b)))

    def count(self) -> int:
        try:
            return self.table.count_rows() - 1
        except Exception:
            return 0

    def audit_log(self, event: str, ticker: str, data: dict) -> None:
        """SEBI audit trail — append-only log of all trading events."""
        import json
        try:
            self.audit.add([{
                "event": event,
                "ticker": ticker,
                "data": json.dumps(data),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }])
        except Exception as e:
            logger.error(f"Audit log failed: {e}")

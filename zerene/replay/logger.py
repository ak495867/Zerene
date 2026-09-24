"""
Append-Only Event Logger for ZERENE simulation runs.
Records high-speed deterministic binary event stream for exact market replay and strategy backtesting.
"""

import os
import json
import gzip
from typing import Dict, Any, List, Optional
from zerene.models import OrderEvent, Order, Trade, EventType


class EventLogger:
    """
    Append-only event recorder for simulation event streams.
    Saves event streams into compressed JSON-Lines or binary format (.zlog.gz).
    """

    def __init__(self, filepath: str, compressed: bool = True):
        self.filepath = filepath
        self.compressed = compressed
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        if compressed:
            self._file = gzip.open(filepath, "at", encoding="utf-8")
        else:
            self._file = open(filepath, "a", encoding="utf-8")
        self.recorded_count = 0

    def log_event(
        self,
        timestamp: float,
        event_type: str,
        symbol: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Logs a single market event into the binary/compressed log stream."""
        record = {
            "seq": self.recorded_count + 1,
            "ts": timestamp,
            "type": event_type,
            "sym": symbol,
            "data": data or {},
        }
        self._file.write(json.dumps(record) + "\n")
        self.recorded_count += 1

    def flush(self) -> None:
        if self._file and not self._file.closed:
            self._file.flush()

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

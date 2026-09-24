"""
Deterministic Market Replay Engine for ZERENE.
Replays saved event streams (.zlog / .zlog.gz) tick-by-tick to backtest strategies against exact historical market microstructure.
"""

import gzip
import json
import os
from typing import List, Dict, Any, Optional, Iterator
from zerene.models import Order, Side, OrderType, TimeInForce
from zerene.exchange.venue import ExchangeVenue
from zerene.strategies.base import Strategy


class MarketReplayEngine:
    """
    Replays historical event logs through simulated matching engines.
    Injects strategy updates at exact historical timestamps without look-ahead bias.
    """

    def __init__(self, log_filepath: str, exchange: Optional[ExchangeVenue] = None):
        self.log_filepath = log_filepath
        self.exchange = exchange or ExchangeVenue("REPLAY-X")
        self.strategies: List[Strategy] = []
        self.current_time = 0.0

    def add_strategy(self, strategy: Strategy) -> None:
        self.strategies.append(strategy)

    def _read_records(self) -> Iterator[Dict[str, Any]]:
        """Yields records from event log file."""
        if self.log_filepath.endswith(".gz"):
            f = gzip.open(self.log_filepath, "rt", encoding="utf-8")
        else:
            f = open(self.log_filepath, "r", encoding="utf-8")

        with f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def run_replay(self) -> Dict[str, Any]:
        """
        Executes full deterministic market replay.
        Returns execution and PnL metrics summary.
        """
        replayed_events = 0
        total_trades = 0

        for rec in self._read_records():
            replayed_events += 1
            ts = rec.get("ts", 0.0)
            self.current_time = ts
            ev_type = rec.get("type")
            sym = rec.get("sym", "BTC-USD")
            data = rec.get("data", {})

            engine = self.exchange.engines.get(sym)
            if not engine:
                engine = self.exchange.add_symbol(sym)

            if ev_type == "ORDER_SUBMIT":
                o_data = data.get("order", {})
                if o_data:
                    side_str = o_data.get("side", "BUY")
                    side = Side.BUY if side_str == "BUY" else Side.SELL
                    type_str = o_data.get("order_type", "LIMIT")
                    order_type = (
                        OrderType[type_str]
                        if type_str in OrderType.__members__
                        else OrderType.LIMIT
                    )

                    order = Order(
                        order_id=o_data.get("order_id", f"R-{replayed_events}"),
                        client_order_id=o_data.get("client_order_id", "CR"),
                        symbol=sym,
                        side=side,
                        order_type=order_type,
                        price=o_data.get("price"),
                        quantity=o_data.get("quantity", 1.0),
                        timestamp=ts,
                        owner_id=o_data.get("owner_id", "HISTORICAL_REPLAY"),
                    )
                    _, trades = self.exchange.submit_order(order)
                    total_trades += len(trades)

            elif ev_type == "ORDER_CANCEL":
                oid = data.get("order_id")
                if oid:
                    self.exchange.cancel_order(sym, oid)

            # Trigger strategy hooks on snapshot update
            snapshot = self.exchange.get_order_book_snapshot(sym, ts)
            if snapshot:
                for strat in self.strategies:
                    if sym in strat.symbols:
                        new_orders = strat.on_market_data(
                            sym, ts, snapshot, self.exchange
                        )
                        for o in new_orders:
                            o.timestamp = ts
                            _, strat_trades = self.exchange.submit_order(o)
                            total_trades += len(strat_trades)

        return {
            "replayed_events": replayed_events,
            "total_trades": total_trades,
            "final_timestamp": self.current_time,
        }

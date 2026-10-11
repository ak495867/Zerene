"""
Exchange Data Adapters for Level 2 / Level 3 market data feeds.
Normalizes raw trade, quote, and depth events into standard structures for calibration and replay.
"""

import json
import csv
from dataclasses import dataclass
from typing import List, Optional, Generator, Dict, Any
from zerene.models import Side, OrderType, Order
from zerene.pools import GLOBAL_ORDER_POOL


@dataclass(slots=True)
class ExchangeTick:
    """Normalized tick structure representing an execution or quote update."""

    timestamp: float  # Epoch in seconds
    price: float
    quantity: float
    side: Side  # Side.BUY or Side.SELL (taker side for trades)
    is_buyer_maker: bool = False
    trade_id: Optional[str] = None
    order_id: Optional[str] = None
    is_trade: bool = True  # True for trade execution, False for top-of-book / quote


class BinanceDataParser:
    """
    Parser for Binance trade and bookTicker feeds (REST or WebSocket dump).
    Supports JSON and CSV formats.
    """

    @staticmethod
    def parse_trades_json(records: List[Dict[str, Any]]) -> List[ExchangeTick]:
        """
        Parses Binance historical trades:
        [{"id": 12345, "price": "65000.50", "qty": "0.15", "quoteQty": "...", "time": 1672531199000, "isBuyerMaker": true, "isBestMatch": true}, ...]
        """
        ticks: List[ExchangeTick] = []
        for r in records:
            ts = float(r.get("time", 0.0)) / 1000.0  # Convert ms to sec
            price = float(r.get("price", 0.0))
            qty = float(r.get("qty", 0.0))
            is_buyer_maker = bool(r.get("isBuyerMaker", False))
            # If buyer was maker, taker was seller (SELL order executed)
            side = Side.SELL if is_buyer_maker else Side.BUY
            trade_id = str(r.get("id", ""))

            ticks.append(
                ExchangeTick(
                    timestamp=ts,
                    price=price,
                    quantity=qty,
                    side=side,
                    is_buyer_maker=is_buyer_maker,
                    trade_id=trade_id,
                    is_trade=True,
                )
            )
        return ticks

    @staticmethod
    def parse_trades_csv(filepath: str) -> Generator[ExchangeTick, None, None]:
        """
        Parses standard Binance public data archive trade CSV:
        id,price,qty,quote_qty,time,is_buyer_maker,is_best_match
        """
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = float(r.get("time", 0.0)) / 1000.0
                price = float(r.get("price", 0.0))
                qty = float(r.get("qty", 0.0))
                ibm_str = str(r.get("is_buyer_maker", "false")).lower()
                is_buyer_maker = ibm_str in ("true", "1", "t")
                side = Side.SELL if is_buyer_maker else Side.BUY
                trade_id = str(r.get("id", ""))

                yield ExchangeTick(
                    timestamp=ts,
                    price=price,
                    quantity=qty,
                    side=side,
                    is_buyer_maker=is_buyer_maker,
                    trade_id=trade_id,
                    is_trade=True,
                )


class StandardL3Parser:
    """
    Parser for standardized Level 3 (order-by-order) historical feeds.
    Format: timestamp,order_id,action(INSERT|CANCEL|MODIFY|EXECUTE),side,price,quantity
    """

    @staticmethod
    def parse_file(
        filepath: str, symbol: str = "BTC-USD"
    ) -> Generator[Order, None, None]:
        """Yields ZERENE Order objects from standard L3 CSV events."""
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, r in reader:
                ts = float(r.get("timestamp", 0.0))
                oid = str(r.get("order_id", f"L3-{idx}"))
                side_str = str(r.get("side", "BUY")).upper()
                side = Side.BUY if side_str == "BUY" else Side.SELL
                action = str(r.get("action", "INSERT")).upper()
                price_val = r.get("price")
                price = float(price_val) if price_val and price_val != "" else None
                qty = float(r.get("quantity", 1.0))

                otype = OrderType.MARKET if action == "EXECUTE" else OrderType.LIMIT

                yield GLOBAL_ORDER_POOL.acquire(
                    order_id=oid,
                    client_order_id=f"CL3-{idx}",
                    symbol=symbol,
                    side=side,
                    order_type=otype,
                    price=price,
                    quantity=qty,
                    timestamp=ts,
                    owner_id="HISTORICAL_L3",
                )

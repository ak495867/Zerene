"""
Abstract base class for modular strategy plugins.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from zerene.models import Order, Trade, OrderEvent
from zerene.exchange.venue import ExchangeVenue


class Strategy(ABC):
    """
    Modular strategy plugin for ZERENE.
    """
    def __init__(self, owner_id: str, symbols: List[str]):
        self.owner_id = owner_id
        self.symbols = symbols
        self.active_orders: Dict[str, Order] = {}
        self.positions: Dict[str, float] = {sym: 0.0 for sym in symbols}
        self.realized_pnl = 0.0

    @abstractmethod
    def on_market_data(self, symbol: str, timestamp: float, book_snapshot: Any, exchange: ExchangeVenue) -> List[Order]:
        """Called upon new market data update or book snapshot. Returns new orders to submit."""
        pass

    @abstractmethod
    def on_order_fill(self, trade: Trade, exchange: ExchangeVenue) -> List[Order]:
        """Called when an order owned by this strategy is filled or partially filled."""
        pass

    @abstractmethod
    def on_timer(self, timestamp: float, exchange: ExchangeVenue) -> List[Order]:
        """Called periodically on discrete timer ticks."""
        pass

    def track_order(self, order: Order) -> None:
        if order.order_id:
            self.active_orders[order.order_id] = order

    def remove_order(self, order_id: str) -> None:
        if order_id in self.active_orders:
            del self.active_orders[order_id]

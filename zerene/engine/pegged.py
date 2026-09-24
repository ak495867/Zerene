"""
Institutional Pegged Order Manager for ZERENE.
Supports MIDPOINT_PEG, PRIMARY_PEG, and MARKET_PEG with discretionary price offsets.
Dynamically re-indexes orders as top-of-book market prices drift.
"""

from typing import Dict, List, Optional, Tuple
from zerene.models import Order, Side, OrderType
from zerene.orderbook.book import OrderBook


class PeggedOrderManager:
    """
    Manages Pegged orders and dynamically updates prices when best bid / best ask / mid price shifts.
    """

    def __init__(self):
        self.pegged_orders: Dict[str, Order] = {}
        self.offsets: Dict[str, float] = {}  # order_id -> discretionary price offset

    def add_pegged_order(self, order: Order, offset: float = 0.0) -> None:
        """Registers a pegged order with discretionary offset."""
        self.pegged_orders[order.order_id] = order
        self.offsets[order.order_id] = offset

    def add_order(self, order: Order, offset: float = 0.0) -> None:
        """Alias for add_pegged_order."""
        self.add_pegged_order(order, offset)

    def remove_pegged_order(self, order_id: str) -> Optional[Order]:
        """Removes a pegged order from tracking."""
        self.offsets.pop(order_id, None)
        return self.pegged_orders.pop(order_id, None)

    def remove_order(self, order_id: str) -> Optional[Order]:
        """Alias for remove_pegged_order."""
        return self.remove_pegged_order(order_id)

    def calculate_pegged_price(
        self, order: Order, best_bid: Optional[float], best_ask: Optional[float]
    ) -> Optional[float]:
        """Calculates the dynamic price for a pegged order given current top-of-book quotes."""
        offset = self.offsets.get(order.order_id, 0.0)

        if order.order_type == OrderType.MIDPOINT_PEG:
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0
                return round(mid + offset, 4)
            return best_bid or best_ask

        elif order.order_type == OrderType.PRIMARY_PEG:
            if order.side == Side.BUY:
                base = best_bid or best_ask
                return round(base + offset, 4) if base is not None else None
            else:
                base = best_ask or best_bid
                return round(base - offset, 4) if base is not None else None

        elif order.order_type == OrderType.MARKET_PEG:
            if order.side == Side.BUY:
                base = best_ask or best_bid
                return round(base + offset, 4) if base is not None else None
            else:
                base = best_bid or best_ask
                return round(base - offset, 4) if base is not None else None

        return order.price

    def update_pegged_orders(
        self, book: OrderBook, timestamp: float
    ) -> List[Tuple[Order, float]]:
        """
        Evaluates all registered pegged orders against current book state.
        Returns list of (order, new_price) pairs that require re-indexing.
        """
        bb = book.best_bid()
        ba = book.best_ask()
        repriced: List[Tuple[Order, float]] = []

        for oid, order in list(self.pegged_orders.items()):
            new_p = self.calculate_pegged_price(order, bb, ba)
            if new_p is not None and (order.price is None or abs(order.price - new_p) > 1e-6):
                repriced.append((order, new_p))

        return repriced

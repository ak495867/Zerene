"""
Stop and Stop-Limit conditional order manager.
Conforms to RFC-001 Section 4.8.
"""

from typing import List, Dict, Optional, Tuple, Any
import heapq
from zerene.models import Order, Side, OrderType, OrderStatus


class StopManager:
    """
    Manages conditional STOP and STOP_LIMIT orders until triggered by market price action.
    Uses twin priority min/max heaps with O(1) lazy deletion for institutional performance.
    """
    def __init__(self):
        self.buy_stops: List[Tuple[float, float, str, Order]] = []   # Min-heap sorted by (stop_price, timestamp, order_id, order)
        self.sell_stops: List[Tuple[float, float, str, Order]] = []  # Max-heap sorted by (-stop_price, timestamp, order_id, order)
        self.order_map: Dict[str, Order] = {}

    def add_order(self, order: Order) -> None:
        """Registers a conditional stop order."""
        if order.stop_price is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "MISSING_STOP_PRICE"
            return

        self.order_map[order.order_id] = order
        if order.side == Side.BUY:
            heapq.heappush(self.buy_stops, (order.stop_price, order.timestamp, order.order_id, order))
        else:
            heapq.heappush(self.sell_stops, (-order.stop_price, order.timestamp, order.order_id, order))

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancels a resting stop order in O(1) via lazy heap deletion."""
        if order_id not in self.order_map:
            return None
        order = self.order_map.pop(order_id)
        order.status = OrderStatus.CANCELED
        return order

    def check_triggers(self, last_trade_price: float, current_timestamp: float) -> List[Order]:
        """
        Evaluates active stop orders against `last_trade_price` in O(log M) time.
        Returns orders triggered into active MARKET or LIMIT orders.
        """
        triggered: List[Order] = []

        # Check buy stops (trigger if last_trade_price >= stop_price)
        while self.buy_stops and self.buy_stops[0][0] <= last_trade_price:
            _, _, order_id, order = heapq.heappop(self.buy_stops)
            if order_id not in self.order_map:
                continue  # Order was lazily canceled
            del self.order_map[order_id]
            order.status = OrderStatus.TRIGGERED
            order.timestamp = current_timestamp
            if order.order_type == OrderType.STOP:
                order.order_type = OrderType.MARKET
            elif order.order_type == OrderType.STOP_LIMIT:
                order.order_type = OrderType.LIMIT
            triggered.append(order)

        # Check sell stops (trigger if last_trade_price <= stop_price, meaning -stop_price >= -last_trade_price)
        while self.sell_stops and self.sell_stops[0][0] <= -last_trade_price:
            _, _, order_id, order = heapq.heappop(self.sell_stops)
            if order_id not in self.order_map:
                continue  # Order was lazily canceled
            del self.order_map[order_id]
            order.status = OrderStatus.TRIGGERED
            order.timestamp = current_timestamp
            if order.order_type == OrderType.STOP:
                order.order_type = OrderType.MARKET
            elif order.order_type == OrderType.STOP_LIMIT:
                order.order_type = OrderType.LIMIT
            triggered.append(order)

        return triggered

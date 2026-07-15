"""
Institutional Memory Pooling (`OrderPool`, `EventPool`) for zero-allocation object recycling.
Eliminates Python garbage collection (`gc`) pauses during high-throughput multi-million order simulations.
"""

from collections import deque
from typing import Optional, List
from zerene.models import (
    Order,
    Trade,
    OrderEvent,
    Side,
    OrderType,
    OrderStatus,
    TimeInForce,
    EventType,
)
from zerene.orderbook.level import Node


class OrderPool:
    """
    Object recycler for Order instances.
    When an order is canceled or completely filled and cleaned up, it can be returned to the pool
    to be reset and re-issued instead of allocating heap memory.
    """

    def __init__(self, initial_capacity: int = 50_000):
        self.pool: deque[Order] = deque()
        self._preallocate(initial_capacity)

    def _preallocate(self, capacity: int) -> None:
        for i in range(capacity):
            o = Order(
                order_id=f"POOL-{i}",
                client_order_id="POOL",
                symbol="",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=0.0,
            )
            o._in_pool = True
            self.pool.append(o)

    def acquire(
        self,
        order_id: str,
        client_order_id: str,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        display_quantity: Optional[float] = None,
        hidden_quantity: float = 0.0,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        timestamp: float = 0.0,
        owner_id: str = "DEFAULT",
    ) -> Order:
        """Acquires a reset Order from the pool or allocates a preallocated chunk if exhausted."""
        if not self.pool:
            self._preallocate(1024)

        from zerene.models import get_next_internal_id

        order = self.pool.popleft()
        order._in_pool = False
        order.internal_id = get_next_internal_id()
        order.order_id = order_id
        order.client_order_id = client_order_id
        order.symbol = symbol
        order.side = side
        order.order_type = order_type
        order.quantity = quantity
        order.price = price
        order.filled_quantity = 0.0
        order.display_quantity = (
            display_quantity if display_quantity is not None else quantity
        )
        order.hidden_quantity = hidden_quantity
        order.stop_price = stop_price
        order.time_in_force = time_in_force
        order.timestamp = timestamp
        order.owner_id = owner_id
        order.status = OrderStatus.NEW
        order.reject_reason = None
        if order_type == OrderType.ICEBERG:
            if order.display_quantity <= 0:
                order.display_quantity = quantity
            order.hidden_quantity = max(0.0, quantity - order.display_quantity)
            order.iceberg_slice = order.display_quantity
        elif order_type == OrderType.HIDDEN:
            order.display_quantity = 0.0
            order.hidden_quantity = quantity
            order.iceberg_slice = 0.0
        else:
            order.iceberg_slice = order.display_quantity
        return order

    def release(self, order: Order) -> None:
        """Returns a spent order to the pool for reuse after wiping leftover state."""
        if order._in_pool:
            return
        order._in_pool = True
        order.recycle_epoch += 1
        order.iceberg_slice = 0.0
        order.filled_quantity = 0.0
        order.status = OrderStatus.NEW
        order.reject_reason = None
        order.display_quantity = None
        order.stop_price = None
        order.price = None
        self.pool.append(order)


class EventPool:
    """
    Object recycler for OrderEvent envelopes inside the latency gateways.
    """

    def __init__(self, initial_capacity: int = 50_000):
        self.pool: deque[OrderEvent] = deque()
        self._preallocate(initial_capacity)

    def _preallocate(self, capacity: int) -> None:
        for i in range(capacity):
            ev = OrderEvent(
                event_id=f"EVPOOL-{i}",
                event_type=EventType.ORDER_SUBMIT,
                timestamp=0.0,
                symbol="",
            )
            ev._in_pool = True
            self.pool.append(ev)

    def acquire(
        self,
        event_id: str,
        event_type: EventType,
        timestamp: float,
        symbol: str,
        order: Optional[Order] = None,
        trade: Optional[Trade] = None,
        message: Optional[str] = None,
    ) -> OrderEvent:
        if not self.pool:
            self._preallocate(1024)

        from zerene.models import get_next_internal_id

        ev = self.pool.popleft()
        ev._in_pool = False
        ev.sequence_number = get_next_internal_id()
        ev.event_id = event_id
        ev.event_type = event_type
        ev.timestamp = timestamp
        ev.symbol = symbol
        ev.order = order
        ev.trade = trade
        ev.message = message
        if ev.metadata is not None:
            ev.metadata.clear()
        return ev

    def release(self, event: OrderEvent) -> None:
        if event._in_pool:
            return
        event._in_pool = True
        event.recycle_epoch += 1
        event.order = None
        event.trade = None
        event.message = None
        if event.metadata is not None:
            event.metadata.clear()
        self.pool.append(event)


class TradePool:
    """
    Object recycler for Trade instances to eliminate allocation/GC overhead during high-throughput matching.
    """

    def __init__(self, initial_capacity: int = 50_000):
        self.pool: deque[Trade] = deque()
        self._preallocate(initial_capacity)

    def _preallocate(self, capacity: int) -> None:
        for i in range(capacity):
            t = Trade(
                trade_id=f"TPOOL-{i}",
                maker_order_id="",
                taker_order_id="",
                symbol="",
                price=0.0,
                quantity=0.0,
                aggressor_side=Side.BUY,
                timestamp=0.0,
                maker_owner_id="",
                taker_owner_id="",
            )
            t._in_pool = True
            self.pool.append(t)

    def acquire(
        self,
        trade_id: str,
        maker_order_id: str,
        taker_order_id: str,
        symbol: str,
        price: float,
        quantity: float,
        aggressor_side: Side,
        timestamp: float,
        maker_owner_id: str = "",
        taker_owner_id: str = "",
    ) -> Trade:
        if not self.pool:
            self._preallocate(1024)

        from zerene.models import get_next_internal_id

        trade = self.pool.popleft()
        trade._in_pool = False
        trade.internal_id = get_next_internal_id()
        trade.trade_id = trade_id
        trade.maker_order_id = maker_order_id
        trade.taker_order_id = taker_order_id
        trade.symbol = symbol
        trade.price = price
        trade.quantity = quantity
        trade.aggressor_side = aggressor_side
        trade.timestamp = timestamp
        trade.maker_owner_id = maker_owner_id
        trade.taker_owner_id = taker_owner_id
        return trade

    def release(self, trade: Trade) -> None:
        if trade._in_pool:
            return
        trade._in_pool = True
        trade.recycle_epoch += 1
        trade.maker_order_id = ""
        trade.taker_order_id = ""
        trade.symbol = ""
        trade.maker_owner_id = ""
        trade.taker_owner_id = ""
        self.pool.append(trade)


class OrderNodePool:
    """
    Object recycler for Node (intrusive doubly-linked list wrappers) inside PriceLevel.
    Eliminates Node wrapper allocations on the heap every time an order is inserted or replaced.
    """

    def __init__(self, initial_capacity: int = 100_000):
        self.pool: deque[Node] = deque()
        self._preallocate(initial_capacity)

    def _preallocate(self, capacity: int) -> None:
        for _ in range(capacity):
            node = Node(order=None)
            node._in_pool = True
            self.pool.append(node)

    def acquire(self, order: Order) -> Node:
        if not self.pool:
            self._preallocate(1024)
        node = self.pool.popleft()
        node._in_pool = False
        node.order = order
        node.prev = None
        node.next = None
        return node

    def release(self, node: Node) -> None:
        if node._in_pool:
            return
        node._in_pool = True
        node.recycle_epoch += 1
        node.order = None
        node.prev = None
        node.next = None
        self.pool.append(node)


# Global default instance pools for high-throughput execution
GLOBAL_ORDER_POOL = OrderPool(initial_capacity=50_000)
GLOBAL_EVENT_POOL = EventPool(initial_capacity=50_000)
GLOBAL_TRADE_POOL = TradePool(initial_capacity=50_000)
GLOBAL_NODE_POOL = OrderNodePool(initial_capacity=100_000)

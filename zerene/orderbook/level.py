"""
Price Level data structure maintaining time priority FIFO order queue.
Uses an intrusive doubly linked list + dictionary index (`order_nodes`) to guarantee strict O(1) order removal and cancellation without linear scanning (`O(M)`).
Also provides precise Iceberg replenishment using `iceberg_slice`.
"""

from typing import List, Optional, Dict, Iterator
from zerene.models import Order, OrderType


class Node:
    """Node in intrusive doubly linked list representing an active order at a price level."""
    __slots__ = ("order", "prev", "next", "_in_pool", "recycle_epoch")

    def __init__(self, order: Optional[Order] = None):
        self.order = order
        self.prev: Optional["Node"] = None
        self.next: Optional["Node"] = None
        self._in_pool: bool = False
        self.recycle_epoch: int = 0


class DoublyLinkedList:
    """O(1) doubly linked FIFO queue."""
    __slots__ = ("head_node", "tail_node")

    def __init__(self):
        self.head_node: Optional[Node] = None
        self.tail_node: Optional[Node] = None

    def append(self, node: Node) -> None:
        if not self.tail_node:
            self.head_node = node
            self.tail_node = node
            node.prev = None
            node.next = None
        else:
            node.prev = self.tail_node
            node.next = None
            self.tail_node.next = node
            self.tail_node = node

    def remove(self, node: Node) -> None:
        if node.prev:
            node.prev.next = node.next
        else:
            self.head_node = node.next

        if node.next:
            node.next.prev = node.prev
        else:
            self.tail_node = node.prev

        node.prev = None
        node.next = None

    def pop_head(self) -> Optional[Node]:
        if not self.head_node:
            return None
        node = self.head_node
        self.remove(node)
        return node

    def __iter__(self) -> Iterator[Order]:
        curr = self.head_node
        while curr:
            yield curr.order
            curr = curr.next


class PriceLevel:
    """
    Represents a single price level in the Limit Order Book.
    Maintains strict FIFO queue of orders resting at this price via O(1) doubly linked list.
    Tracks both visible (display) and hidden volumes.
    """
    __slots__ = ("price", "price_ticks", "queue", "order_nodes", "total_volume", "hidden_volume")

    def __init__(self, price: float):
        self.price = price if isinstance(price, float) else price / 10000.0
        self.price_ticks = int(round(price * 10000)) if isinstance(price, float) else int(price)
        self.queue: DoublyLinkedList = DoublyLinkedList()
        self.order_nodes: Dict[int, Node] = {}
        self.total_volume: float = 0.0   # Visible display volume
        self.hidden_volume: float = 0.0  # Hidden / iceberg remaining volume

    @property
    def orders(self) -> List[Order]:
        """Returns list of orders in arrival order. Used for introspection and queue position calculation."""
        return list(self.queue)

    def append(self, order: Order) -> None:
        """Adds an order to the tail of the FIFO queue in strict O(1)."""
        from zerene.pools import GLOBAL_NODE_POOL
        node = GLOBAL_NODE_POOL.acquire(order)
        self.queue.append(node)
        self.order_nodes[order.internal_id] = node
        if order.display_quantity is not None:
            self.total_volume += order.display_quantity
        self.hidden_volume += order.hidden_quantity

    def remove(self, order: Order) -> bool:
        """Removes a specific resting order from the queue in strict O(1) without linear scans."""
        node = self.order_nodes.pop(order.internal_id, None)
        if not node:
            return False
        self.queue.remove(node)
        if order.display_quantity is not None:
            self.total_volume = max(0.0, self.total_volume - order.display_quantity)
        self.hidden_volume = max(0.0, self.hidden_volume - order.hidden_quantity)
        from zerene.pools import GLOBAL_NODE_POOL
        GLOBAL_NODE_POOL.release(node)
        return True

    def head(self) -> Optional[Order]:
        """Returns the first order in line without removing it in O(1)."""
        return self.queue.head_node.order if self.queue.head_node else None

    def pop_head(self) -> Optional[Order]:
        """Removes and returns the first order in line in strict O(1)."""
        node = self.queue.pop_head()
        if not node:
            return None
        order = node.order
        self.order_nodes.pop(order.internal_id, None)
        if order.display_quantity is not None:
            self.total_volume = max(0.0, self.total_volume - order.display_quantity)
        self.hidden_volume = max(0.0, self.hidden_volume - order.hidden_quantity)
        from zerene.pools import GLOBAL_NODE_POOL
        GLOBAL_NODE_POOL.release(node)
        return order

    def update_volume_after_fill(self, order: Order, filled_qty: float) -> None:
        """
        Updates level volume when the head order is partially filled.
        Also handles exact Iceberg visible replenishment (`iceberg_slice`) if visible tranche is exhausted.
        """
        if order.order_type == OrderType.ICEBERG:
            deducted = min(order.display_quantity or 0.0, filled_qty)
            if order.display_quantity is not None:
                order.display_quantity -= deducted
                self.total_volume = max(0.0, self.total_volume - deducted)

            # If display quantity hits zero and hidden quantity remains, replenish exact iceberg_slice!
            if (order.display_quantity or 0.0) <= 1e-9 and order.hidden_quantity > 1e-9:
                replenish = min(order.hidden_quantity, max(1.0, order.iceberg_slice or (order.quantity * 0.1)))
                order.display_quantity = replenish
                order.hidden_quantity -= replenish
                self.total_volume += replenish
                self.hidden_volume = max(0.0, self.hidden_volume - replenish)

                # Iceberg replenishment moves this order to the tail of the FIFO queue in O(1)!
                node = self.order_nodes.get(order.internal_id)
                if node and self.queue.tail_node != node:
                    self.queue.remove(node)
                    self.queue.append(node)
        elif order.order_type == OrderType.HIDDEN:
            order.hidden_quantity = max(0.0, order.hidden_quantity - filled_qty)
            self.hidden_volume = max(0.0, self.hidden_volume - filled_qty)
        else:
            if order.display_quantity is not None:
                order.display_quantity = max(0.0, order.display_quantity - filled_qty)
                self.total_volume = max(0.0, self.total_volume - filled_qty)

    def is_empty(self) -> bool:
        return self.queue.head_node is None and self.total_volume <= 1e-9 and self.hidden_volume <= 1e-9

    def __len__(self) -> int:
        return len(self.order_nodes)

"""
Limit Order Book implementation conforming to RFC-002.
Maintains bids (descending) and asks (ascending) with O(log N) tick-indexed order lookup via bisect binary search trees,
and atomic Cancel-Replace priority preservation rules (`FIX 35=G`).
"""

from sortedcontainers import SortedList
import bisect
from typing import Dict, List, Optional, Tuple, Any
from zerene.models import Order, Side, OrderStatus, OrderType
from zerene.orderbook.level import PriceLevel


class TickDict(dict):
    """
    Dictionary subclass that automatically normalizes floating point price keys to fixed integer ticks (`TICK_SCALE=10000`)
    while preserving standard float lookup ergonomics for introspection, reporting, and backwards compatibility.
    """
    def _normalize_key(self, key):
        if isinstance(key, float):
            return int(round(key * 10000))
        return key

    def __getitem__(self, key):
        return super().__getitem__(self._normalize_key(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._normalize_key(key), value)

    def __delitem__(self, key):
        super().__delitem__(self._normalize_key(key))

    def __contains__(self, key):
        return super().__contains__(self._normalize_key(key))

    def get(self, key, default=None):
        return super().get(self._normalize_key(key), default)

    def pop(self, key, default=...):
        k = self._normalize_key(key)
        if default is ...:
            return super().pop(k)
        return super().pop(k, default)


class OrderBook:
    """
    Limit Order Book tracking bids and asks.
    Provides fast O(log N) price level insertion/deletion via B-Tree indexed `SortedList`,
    fast order access, queue position indexing, and atomic order modification (`FIX 35=G`).
    Uses integer ticks (`price * 10000`) for zero floating-point drift.
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: TickDict[int, PriceLevel] = TickDict()
        self.asks: TickDict[int, PriceLevel] = TickDict()
        self.sorted_bids: SortedList = SortedList(key=lambda x: -x)  # Sorted descending via B-Tree (integer ticks)
        self.sorted_asks: SortedList = SortedList()                  # Sorted ascending via B-Tree (integer ticks)
        self.order_map: Dict[str, Order] = {}
        self._order_map_int: Dict[int, Order] = {}

    def insert_order(self, order: Order) -> None:
        """Inserts an order onto the book at its specified price level in O(log N)."""
        if order.price is None:
            return
        price = round(order.price, 8) if isinstance(order.price, float) else order.price
        order.price = price
        price_ticks = int(round(price * 10000)) if isinstance(price, float) else int(price)

        if order.side == Side.BUY:
            if price_ticks not in self.bids:
                self.bids[price_ticks] = PriceLevel(price)
                self.sorted_bids.add(price_ticks)
            self.bids[price_ticks].append(order)
        else:
            if price_ticks not in self.asks:
                self.asks[price_ticks] = PriceLevel(price)
                self.sorted_asks.add(price_ticks)
            self.asks[price_ticks].append(order)

        self.order_map[order.order_id] = order
        self._order_map_int[order.internal_id] = order

    def remove_order(self, order_id: str) -> Optional[Order]:
        """Removes an order by ID from its price level and the global map in O(1) level removal + O(log N) tree discard."""
        if order_id not in self.order_map:
            return None
        order = self.order_map.pop(order_id)
        self._order_map_int.pop(order.internal_id, None)
        if order.price is None:
            return order

        price_ticks = int(round(order.price * 10000)) if isinstance(order.price, float) else int(order.price)
        if order.side == Side.BUY and price_ticks in self.bids:
            level = self.bids[price_ticks]
            level.remove(order)
            if level.is_empty():
                del self.bids[price_ticks]
                self.sorted_bids.discard(price_ticks)
        elif order.side == Side.SELL and price_ticks in self.asks:
            level = self.asks[price_ticks]
            level.remove(order)
            if level.is_empty():
                del self.asks[price_ticks]
                self.sorted_asks.discard(price_ticks)

        return order

    def remove_order_by_int(self, internal_id: int) -> Optional[Order]:
        """Fast hot-path O(1) order removal using uint64 sequence IDs to avoid string hashing overhead."""
        if internal_id not in self._order_map_int:
            return None
        order = self._order_map_int.pop(internal_id)
        self.order_map.pop(order.order_id, None)
        if order.price is None:
            return order

        price_ticks = int(round(order.price * 10000)) if isinstance(order.price, float) else int(order.price)
        if order.side == Side.BUY and price_ticks in self.bids:
            level = self.bids[price_ticks]
            level.remove(order)
            if level.is_empty():
                del self.bids[price_ticks]
                self.sorted_bids.discard(price_ticks)
        elif order.side == Side.SELL and price_ticks in self.asks:
            level = self.asks[price_ticks]
            level.remove(order)
            if level.is_empty():
                del self.asks[price_ticks]
                self.sorted_asks.discard(price_ticks)

        return order

    def modify_order(
        self,
        order_id: str,
        new_quantity: float,
        new_price: Optional[float] = None,
        timestamp: float = 0.0,
    ) -> Tuple[bool, Optional[Order], Optional[str]]:
        """
        Atomic Modify/Replace order (`FIX 35=G`).
        Enforces institutional priority preservation rules:
        1. If price changes or quantity increases -> loses priority (removed & re-inserted at tail of queue).
        2. If quantity decreases and price unchanged -> preserves exact time priority in queue!
        """
        order = self.order_map.get(order_id)
        if not order or order.price is None:
            return False, None, "ORDER_NOT_FOUND"

        if new_quantity <= 0.0:
            # If new quantity is zero, equivalent to cancel
            canceled = self.remove_order(order_id)
            if canceled:
                canceled.status = OrderStatus.CANCELED
            return True, canceled, "CANCEL_ON_ZERO_QUANTITY"

        if new_quantity <= order.filled_quantity + 1e-9:
            # If modified quantity is less than what's already filled, the remainder is canceled
            canceled = self.remove_order(order_id)
            if canceled:
                canceled.status = OrderStatus.CANCELED
            return True, canceled, "CANCEL_ON_QUANTITY_BELOW_FILLED"

        current_price = order.price
        target_price = new_price if new_price is not None else current_price

        # Check if priority must be lost
        if target_price != current_price or new_quantity > order.quantity:
            # Remove from book and re-insert at tail with new priority
            self.remove_order(order_id)
            order.price = target_price
            order.quantity = new_quantity
            if order.display_quantity is not None:
                order.display_quantity = min(order.display_quantity, new_quantity)
            if order.order_type == OrderType.ICEBERG:
                order.hidden_quantity = max(0.0, order.quantity - (order.display_quantity or 0.0))
            elif order.order_type == OrderType.HIDDEN:
                order.hidden_quantity = order.quantity
            order.timestamp = timestamp
            order.status = OrderStatus.REPLACED
            self.insert_order(order)
            return True, order, "PRIORITY_LOST_REPLACED"
        else:
            # Priority preserved! Modify in-place without queue relocation.
            delta_qty = order.quantity - new_quantity
            order.quantity = new_quantity
            if order.display_quantity is not None:
                deduct_display = min(order.display_quantity, delta_qty)
                order.display_quantity -= deduct_display
            else:
                deduct_display = 0.0
            order.status = OrderStatus.REPLACED

            level = self.bids[current_price] if order.side == Side.BUY else self.asks[current_price]
            level.total_volume = max(0.0, level.total_volume - deduct_display)
            if order.order_type == OrderType.ICEBERG:
                if order.display_quantity is not None:
                    order.hidden_quantity = max(0.0, order.quantity - order.display_quantity)
                level.hidden_volume = max(0.0, level.hidden_volume - (delta_qty - deduct_display))
            elif order.order_type == OrderType.HIDDEN:
                order.hidden_quantity = order.quantity
                level.hidden_volume = max(0.0, level.hidden_volume - delta_qty)

            return True, order, "PRIORITY_PRESERVED_REPLACED"

    def best_bid(self) -> Optional[float]:
        """Returns the highest resting buy price (`float` for external consumption)."""
        return (self.sorted_bids[0] / 10000.0 if isinstance(self.sorted_bids[0], int) else self.sorted_bids[0]) if self.sorted_bids else None

    def best_bid_ticks(self) -> Optional[int]:
        """Returns the highest resting buy price in exact integer ticks for internal engine matching."""
        return self.sorted_bids[0] if self.sorted_bids else None

    def best_ask(self) -> Optional[float]:
        """Returns the lowest resting sell price (`float` for external consumption)."""
        return (self.sorted_asks[0] / 10000.0 if isinstance(self.sorted_asks[0], int) else self.sorted_asks[0]) if self.sorted_asks else None

    def best_ask_ticks(self) -> Optional[int]:
        """Returns the lowest resting sell price in exact integer ticks for internal engine matching."""
        return self.sorted_asks[0] if self.sorted_asks else None

    def mid_price(self) -> Optional[float]:
        """Returns the midpoint between best bid and best ask."""
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return bb or ba

    def spread(self) -> Optional[float]:
        """Returns the quoted spread (best_ask - best_bid)."""
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is not None and ba is not None:
            return ba - bb
        return None

    def get_depth(self, levels: int = 10) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """
        Returns (bids_depth, asks_depth) up to `levels`.
        Each entry is (price, visible_volume). Hidden volume is excluded.
        """
        b_depth = []
        for p in self.sorted_bids[:levels]:
            lvl = self.bids.get(p)
            if lvl and lvl.total_volume > 1e-9:
                p_disp = p / 10000.0 if isinstance(p, int) else p
                b_depth.append((p_disp, lvl.total_volume))

        a_depth = []
        for p in self.sorted_asks[:levels]:
            lvl = self.asks.get(p)
            if lvl and lvl.total_volume > 1e-9:
                p_disp = p / 10000.0 if isinstance(p, int) else p
                a_depth.append((p_disp, lvl.total_volume))

        return b_depth, a_depth

    def get_volume_profile(self, bins: int = 10) -> Dict[str, Any]:
        """Returns aggregated resting visible volume distribution across bids and asks."""
        b_vol = sum(lvl.total_volume for lvl in self.bids.values())
        a_vol = sum(lvl.total_volume for lvl in self.asks.values())
        return {
            "total_bid_volume": b_vol,
            "total_ask_volume": a_vol,
            "bid_levels_count": len(self.sorted_bids),
            "ask_levels_count": len(self.sorted_asks),
        }

    def imbalance(self, levels: int = 5) -> float:
        """
        Calculates order imbalance across the top N levels.
        Range [-1.0, 1.0], where positive is buy pressure.
        """
        b_depth, a_depth = self.get_depth(levels)
        b_vol = sum(vol for _, vol in b_depth)
        a_vol = sum(vol for _, vol in a_depth)
        total = b_vol + a_vol
        if total <= 1e-9:
            return 0.0
        return (b_vol - a_vol) / total

    def get_queue_position(self, order_id: str) -> Optional[Tuple[int, float, int]]:
        """
        Returns (price_level_rank, volume_ahead, orders_ahead) for an active order using O(log N) rank search.
        """
        order = self.order_map.get(order_id)
        if not order or order.price is None:
            return None

        price = order.price
        price_ticks = int(round(price * 10000)) if isinstance(price, float) else int(price)
        if order.side == Side.BUY:
            if price_ticks not in self.bids:
                return None
            level = self.bids[price_ticks]
            rank = self.sorted_bids.index(price_ticks) if price_ticks in self.sorted_bids else None
        else:
            if price_ticks not in self.asks:
                return None
            level = self.asks[price_ticks]
            rank = self.sorted_asks.index(price_ticks) if price_ticks in self.sorted_asks else None

        if rank is None:
            return None

        volume_ahead = 0.0
        orders_ahead = 0
        for o in level.queue:
            if o.order_id == order_id:
                break
            orders_ahead += 1
            if o.display_quantity is not None:
                volume_ahead += o.display_quantity
            volume_ahead += o.hidden_quantity

        return (rank, volume_ahead, orders_ahead)

    def clean_empty_level(self, price: float, side: Side) -> None:
        """Cleans up empty price level if needed."""
        price_ticks = int(round(price * 10000)) if isinstance(price, float) else int(price)
        if side == Side.BUY and price_ticks in self.bids:
            if self.bids[price_ticks].is_empty():
                del self.bids[price_ticks]
                self.sorted_bids.discard(price_ticks)
        elif side == Side.SELL and price_ticks in self.asks:
            if self.asks[price_ticks].is_empty():
                del self.asks[price_ticks]
                self.sorted_asks.discard(price_ticks)

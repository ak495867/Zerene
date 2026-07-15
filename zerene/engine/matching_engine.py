"""
Deterministic Price-Time Priority Matching Engine.
Conforms to RFC-001 and RFC-002.
Supports MARKET, LIMIT, IOC, FOK, POST_ONLY, REDUCE_ONLY, ICEBERG, HIDDEN, STOP, STOP_LIMIT.
"""

from collections import deque
import uuid
from typing import List, Dict, Optional, Tuple
from zerene.models import Order, Trade, Side, OrderType, OrderStatus, TimeInForce
from zerene.orderbook.book import OrderBook
from zerene.engine.stop_manager import StopManager
from zerene.pools import GLOBAL_TRADE_POOL


class MatchingEngine:
    """
    Deterministic matching engine for a single symbol.
    Executes trades in strict price-time priority (FIFO).
    Uses bounded history (`maxlen=100_000`) and iterative stop order processing without recursion.
    """
    def __init__(self, symbol: str, max_history_len: int = 100_000):
        self.symbol = symbol
        self.order_book = OrderBook(symbol)
        self.stop_manager = StopManager()
        self.max_history_len = max_history_len
        self.trade_history: deque[Trade] = deque(maxlen=max_history_len)
        self.order_history: Dict[str, Order] = {}
        self._order_history_keys: deque[str] = deque(maxlen=max_history_len)
        self.last_trade_price: Optional[float] = None
        self._trade_counter: int = 0
        self._pending_orders: deque[Order] = deque()
        self._processing_active: bool = False

    def _record_order(self, order: Order) -> None:
        if order.order_id not in self.order_history:
            self._order_history_keys.append(order.order_id)
            if len(self.order_history) >= self.max_history_len:
                oldest = self._order_history_keys.popleft()
                self.order_history.pop(oldest, None)
        self.order_history[order.order_id] = order

    def process_order(self, order: Order) -> Tuple[Order, List[Trade]]:
        """
        Main entry point for processing an incoming order.
        Returns the updated Order and a list of Trades generated.
        Iteratively drains pending stop order cascades without recursion.
        """
        self._pending_orders.append(order)
        if self._processing_active:
            return order, []

        self._processing_active = True
        all_trades: List[Trade] = []
        try:
            while self._pending_orders:
                curr = self._pending_orders.popleft()
                _, trades = self._process_single_order(curr)
                all_trades.extend(trades)
        finally:
            self._processing_active = False

        return order, all_trades

    def _process_single_order(self, order: Order) -> Tuple[Order, List[Trade]]:
        self._record_order(order)

        # Basic validation
        if order.quantity <= 0.0:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "INVALID_QUANTITY"
            return order, []

        # Route conditional orders to StopManager
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            self.stop_manager.add_order(order)
            return order, []

        # Handle FOK validation pre-check
        if order.order_type == OrderType.FOK or order.time_in_force == TimeInForce.FOK:
            if not self._can_fill_completely(order):
                order.status = OrderStatus.REJECTED
                order.reject_reason = "INSUFFICIENT_LIQUIDITY_FOR_FOK"
                return order, []

        # Handle Post-Only pre-check
        if order.order_type == OrderType.POST_ONLY:
            if self._would_cross(order):
                order.status = OrderStatus.REJECTED
                order.reject_reason = "POST_ONLY_WOULD_CROSS"
                return order, []

        # Execute matching
        trades = self._match(order)

        # Handle remaining quantity based on order type / TIF
        if order.remaining_quantity > 1e-9:
            if order.order_type == OrderType.MARKET or order.time_in_force in (TimeInForce.IOC, TimeInForce.FOK) or order.order_type == OrderType.IOC:
                order.status = OrderStatus.PARTIALLY_FILLED if order.filled_quantity > 0 else OrderStatus.CANCELED
            else:
                # Place residual on limit order book
                if order.status == OrderStatus.NEW and order.filled_quantity > 0:
                    order.status = OrderStatus.PARTIALLY_FILLED
                self.order_book.insert_order(order)
        else:
            order.status = OrderStatus.FILLED

        # Check and trigger stop orders if trades occurred
        if self.last_trade_price is not None and trades:
            triggered_orders = self.stop_manager.check_triggers(self.last_trade_price, order.timestamp)
            if triggered_orders:
                self._pending_orders.extend(triggered_orders)

        return order, trades

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancels a resting order from the order book or stop manager."""
        order = self.order_book.remove_order(order_id)
        if order is None:
            order = self.stop_manager.cancel_order(order_id)
        else:
            order.status = OrderStatus.CANCELED
        return order

    def cancel_all_for_participant(self, owner_id: str) -> List[Order]:
        """Cancels all resting limit orders and stop orders belonging to `owner_id`."""
        canceled_orders: List[Order] = []
        # Find all resting limit orders for this participant
        resting_ids = [oid for oid, o in self.order_book.order_map.items() if o.owner_id == owner_id]
        for oid in resting_ids:
            c = self.cancel_order(oid)
            if c:
                canceled_orders.append(c)

        # Find all resting stop orders for this participant
        stop_ids = [oid for oid, o in self.stop_manager.order_map.items() if o.owner_id == owner_id]
        for oid in stop_ids:
            c = self.cancel_order(oid)
            if c:
                canceled_orders.append(c)

        return canceled_orders

    def modify_order(
        self,
        order_id: str,
        new_quantity: float,
        new_price: Optional[float] = None,
        timestamp: float = 0.0,
    ) -> Tuple[bool, Optional[Order], Optional[str]]:
        """
        Atomic Modify/Replace order passing through to OrderBook (`FIX 35=G`).
        Checks for crossing pre-insertion to avoid invalid crossed book state.
        """
        existing = self.order_book.order_map.get(order_id)
        if existing and new_price is not None:
            would_cross = (
                (existing.side == Side.BUY and self.order_book.best_ask() is not None and round(new_price, 8) >= self.order_book.best_ask()) or
                (existing.side == Side.SELL and self.order_book.best_bid() is not None and round(new_price, 8) <= self.order_book.best_bid())
            )
            if would_cross:
                removed = self.order_book.remove_order(order_id)
                if removed:
                    removed.price = round(new_price, 8)
                    removed.quantity = new_quantity
                    if removed.display_quantity is not None:
                        removed.display_quantity = min(removed.display_quantity, new_quantity)
                    removed.timestamp = timestamp
                    removed.status = OrderStatus.REPLACED
                    self.process_order(removed)
                    return True, removed, "PRIORITY_LOST_REPLACED_CROSSED"

        return self.order_book.modify_order(order_id, new_quantity, new_price, timestamp)

    def _match(self, incoming: Order) -> List[Trade]:
        """Core matching loop crossing incoming order against opposite resting book."""
        trades: List[Trade] = []

        while incoming.remaining_quantity > 1e-9:
            # Get best opposite price
            if incoming.side == Side.BUY:
                best_price = self.order_book.best_ask()
                # Check price limits
                if best_price is None:
                    break
                if incoming.order_type != OrderType.MARKET and incoming.price is not None and incoming.price < best_price:
                    break
                level = self.order_book.asks[best_price]
            else:
                best_price = self.order_book.best_bid()
                if best_price is None:
                    break
                if incoming.order_type != OrderType.MARKET and incoming.price is not None and incoming.price > best_price:
                    break
                level = self.order_book.bids[best_price]

            # Match against FIFO queue at this price level
            while not level.is_empty() and incoming.remaining_quantity > 1e-9:
                resting = level.head()
                if not resting:
                    break

                # Calculate match quantity
                match_qty = min(incoming.remaining_quantity, resting.remaining_quantity)
                if match_qty <= 1e-9:
                    break

                # Create trade with preallocated deterministic counter ID from GLOBAL_TRADE_POOL
                self._trade_counter += 1
                trade_id = f"TRD-{self._trade_counter}"
                trade = GLOBAL_TRADE_POOL.acquire(
                    trade_id=trade_id,
                    maker_order_id=resting.order_id,
                    taker_order_id=incoming.order_id,
                    symbol=self.symbol,
                    price=best_price,
                    quantity=match_qty,
                    aggressor_side=incoming.side,
                    timestamp=incoming.timestamp,
                    maker_owner_id=resting.owner_id,
                    taker_owner_id=incoming.owner_id,
                )
                trades.append(trade)
                self.trade_history.append(trade)
                self.last_trade_price = best_price

                # Update quantities
                incoming.filled_quantity += match_qty
                resting.filled_quantity += match_qty
                if resting.status == OrderStatus.NEW and resting.filled_quantity > 0:
                    resting.status = OrderStatus.PARTIALLY_FILLED

                # Update level volume
                level.update_volume_after_fill(resting, match_qty)

                # Check if resting order is completely filled
                if resting.remaining_quantity <= 1e-9:
                    resting.status = OrderStatus.FILLED
                    level.pop_head()
                    if resting.order_id in self.order_book.order_map:
                        del self.order_book.order_map[resting.order_id]

            # Clean empty price level
            self.order_book.clean_empty_level(best_price, incoming.side.opposite)
            if self.order_book.bids.get(best_price) is not None and self.order_book.bids[best_price].is_empty():
                self.order_book.clean_empty_level(best_price, Side.BUY)
            if self.order_book.asks.get(best_price) is not None and self.order_book.asks[best_price].is_empty():
                self.order_book.clean_empty_level(best_price, Side.SELL)

        return trades

    def _can_fill_completely(self, order: Order) -> bool:
        """Checks if total available liquidity within limit price >= order.quantity using exact integer ticks."""
        required = order.quantity
        available = 0.0
        order_ticks = int(round(order.price * 10000)) if isinstance(order.price, float) else (int(order.price) if order.price is not None else None)

        if order.side == Side.BUY:
            for price_ticks in self.order_book.sorted_asks:
                if order.order_type != OrderType.MARKET and order_ticks is not None and price_ticks > order_ticks:
                    break
                lvl = self.order_book.asks.get(price_ticks)
                if lvl:
                    available += lvl.total_volume + lvl.hidden_volume
                if available >= required:
                    return True
        else:
            for price_ticks in self.order_book.sorted_bids:
                if order.order_type != OrderType.MARKET and order_ticks is not None and price_ticks < order_ticks:
                    break
                lvl = self.order_book.bids.get(price_ticks)
                if lvl:
                    available += lvl.total_volume + lvl.hidden_volume
                if available >= required:
                    return True

        return available >= required

    def _would_cross(self, order: Order) -> bool:
        """Checks if a POST_ONLY order would cross existing resting liquidity."""
        if order.price is None:
            return True  # A Post-Only market order without limit price always attempts to take liquidity or is invalid!
        if order.side == Side.BUY:
            ba = self.order_book.best_ask()
            return ba is not None and order.price >= ba
        else:
            bb = self.order_book.best_bid()
            return bb is not None and order.price <= bb

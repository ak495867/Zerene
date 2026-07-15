"""
Avellaneda-Stoikov & Inventory-Skewed Market Maker strategy.
Places dynamic quotes around mid price adjusted for inventory risk.
Uses zero-allocation object pooling (`GLOBAL_ORDER_POOL`).
"""

from typing import List, Dict, Any, Optional
from zerene.models import Order, Side, OrderType, Trade
from zerene.strategies.base import Strategy
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL


class MarketMakerStrategy(Strategy):
    """
    Inventory-sensitive market making strategy quoting bids and asks
    around the midpoint with reservation price skew:
    Reservation Price r(s, q) = s - q * gamma * sigma^2
    """

    def __init__(
        self,
        symbol: str,
        owner_id: str = "MM_01",
        spread_bps: float = 10.0,
        quote_quantity: float = 1.0,
        max_inventory: float = 10.0,
        gamma: float = 0.1,  # Risk aversion parameter
        sigma: float = 0.02,  # Volatility estimate
    ):
        super().__init__(owner_id, [symbol])
        self.symbol = symbol
        self.spread_bps = spread_bps
        self.quote_quantity = quote_quantity
        self.max_inventory = max_inventory
        self.gamma = gamma
        self.sigma = sigma
        self.last_bid_id: Optional[str] = None
        self.last_ask_id: Optional[str] = None
        self._order_counter: int = 0

    def on_market_data(
        self, symbol: str, timestamp: float, book_snapshot: Any, exchange: ExchangeVenue
    ) -> List[Order]:
        if symbol != self.symbol or book_snapshot.mid_price is None:
            return []

        mid = book_snapshot.mid_price
        q = self.positions.get(self.symbol, 0.0)

        # Cancel existing resting quotes before requoting
        orders_to_submit: List[Order] = []
        if self.last_bid_id:
            exchange.cancel_order(self.symbol, self.last_bid_id)
            self.remove_order(self.last_bid_id)
            self.last_bid_id = None
        if self.last_ask_id:
            exchange.cancel_order(self.symbol, self.last_ask_id)
            self.remove_order(self.last_ask_id)
            self.last_ask_id = None

        # Calculate reservation price skew based on inventory
        reservation_price = mid - (q * self.gamma * (self.sigma**2))
        half_spread = (mid * self.spread_bps / 10000.0) / 2.0

        bid_price = round(reservation_price - half_spread, 2)
        ask_price = round(reservation_price + half_spread, 2)

        # Place new quotes unless at max inventory limit
        if q < self.max_inventory and bid_price > 0:
            self._order_counter += 1
            bid_id = f"MM-B-{self.owner_id}-{self._order_counter}"
            bid_order = GLOBAL_ORDER_POOL.acquire(
                order_id=bid_id,
                client_order_id=f"C-{bid_id}",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=bid_price,
                quantity=self.quote_quantity,
                timestamp=timestamp,
                owner_id=self.owner_id,
            )
            orders_to_submit.append(bid_order)
            self.track_order(bid_order)
            self.last_bid_id = bid_id

        if q > -self.max_inventory and ask_price > bid_price:
            self._order_counter += 1
            ask_id = f"MM-A-{self.owner_id}-{self._order_counter}"
            ask_order = GLOBAL_ORDER_POOL.acquire(
                order_id=ask_id,
                client_order_id=f"C-{ask_id}",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=ask_price,
                quantity=self.quote_quantity,
                timestamp=timestamp,
                owner_id=self.owner_id,
            )
            orders_to_submit.append(ask_order)
            self.track_order(ask_order)
            self.last_ask_id = ask_id

        return orders_to_submit

    def on_order_fill(self, trade: Trade, exchange: ExchangeVenue) -> List[Order]:
        if trade.symbol == self.symbol:
            maker_side = Side.BUY if trade.aggressor_side == Side.SELL else Side.SELL
            taker_side = trade.aggressor_side
            if trade.maker_owner_id == self.owner_id:
                delta = trade.quantity if maker_side == Side.BUY else -trade.quantity
                self.positions[self.symbol] = (
                    self.positions.get(self.symbol, 0.0) + delta
                )
            if (
                trade.taker_owner_id == self.owner_id
                and trade.taker_owner_id != trade.maker_owner_id
            ):
                delta = trade.quantity if taker_side == Side.BUY else -trade.quantity
                self.positions[self.symbol] = (
                    self.positions.get(self.symbol, 0.0) + delta
                )
        return []

    def on_timer(self, timestamp: float, exchange: ExchangeVenue) -> List[Order]:
        return []

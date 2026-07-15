"""
Mean Reversion statistical strategy based on Bollinger Bands of spread / mid-price.
Uses zero-allocation object pooling (`GLOBAL_ORDER_POOL`) and fast pure-python statistics.
"""

import math
from typing import List, Any
from zerene.models import Order, Side, OrderType, Trade
from zerene.strategies.base import Strategy
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL


class MeanReversionStrategy(Strategy):
    """
    Mean reversion strategy tracking rolling mean and standard deviation z-score.
    Enters opposite to extreme deviations and exits when mean reverting.
    """
    def __init__(
        self,
        symbol: str,
        owner_id: str = "MR_01",
        window_size: int = 20,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        trade_quantity: float = 1.0,
    ):
        super().__init__(owner_id, [symbol])
        self.symbol = symbol
        self.window_size = window_size
        self.z_entry = z_entry
        self.z_exit = z_exit
        self.trade_quantity = trade_quantity
        self.price_history: List[float] = []
        self._order_counter: int = 0

    def on_market_data(self, symbol: str, timestamp: float, book_snapshot: Any, exchange: ExchangeVenue) -> List[Order]:
        if symbol != self.symbol or book_snapshot.mid_price is None:
            return []

        mid = book_snapshot.mid_price
        self.price_history.append(mid)
        if len(self.price_history) > self.window_size:
            self.price_history.pop(0)

        n = len(self.price_history)
        if n < self.window_size:
            return []

        mean = sum(self.price_history) / n
        variance = sum((x - mean) ** 2 for x in self.price_history) / n
        if variance <= 1e-18:
            return []
        std = math.sqrt(variance)

        z_score = (mid - mean) / std
        pos = self.positions.get(self.symbol, 0.0)
        orders: List[Order] = []

        # High price deviation -> short
        if z_score > self.z_entry and pos >= 0:
            self._order_counter += 1
            order_id = f"MR-SELL-{self.owner_id}-{self._order_counter}"
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=order_id,
                client_order_id=f"C-{order_id}",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=self.trade_quantity + abs(pos),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))
        # Low price deviation -> long
        elif z_score < -self.z_entry and pos <= 0:
            self._order_counter += 1
            order_id = f"MR-BUY-{self.owner_id}-{self._order_counter}"
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=order_id,
                client_order_id=f"C-{order_id}",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=self.trade_quantity + abs(pos),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))
        # Reversion to mean -> close position
        elif abs(z_score) < self.z_exit and abs(pos) > 1e-9:
            side = Side.SELL if pos > 0 else Side.BUY
            self._order_counter += 1
            order_id = f"MR-CLOSE-{self.owner_id}-{self._order_counter}"
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=order_id,
                client_order_id=f"C-{order_id}",
                symbol=self.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=abs(pos),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))

        return orders

    def on_order_fill(self, trade: Trade, exchange: ExchangeVenue) -> List[Order]:
        if trade.symbol == self.symbol:
            maker_side = Side.BUY if trade.aggressor_side == Side.SELL else Side.SELL
            taker_side = trade.aggressor_side
            if trade.maker_owner_id == self.owner_id:
                delta = trade.quantity if maker_side == Side.BUY else -trade.quantity
                self.positions[self.symbol] = self.positions.get(self.symbol, 0.0) + delta
            if trade.taker_owner_id == self.owner_id and trade.taker_owner_id != trade.maker_owner_id:
                delta = trade.quantity if taker_side == Side.BUY else -trade.quantity
                self.positions[self.symbol] = self.positions.get(self.symbol, 0.0) + delta
        return []

    def on_timer(self, timestamp: float, exchange: ExchangeVenue) -> List[Order]:
        return []

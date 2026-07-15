"""
Momentum and Trend Following strategy.
Trades based on short-term vs long-term EMA crossover and order book imbalance.
Uses zero-allocation object pooling (`GLOBAL_ORDER_POOL`).
"""

from typing import List, Any, Optional
from zerene.models import Order, Side, OrderType, Trade
from zerene.strategies.base import Strategy
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL


class MomentumStrategy(Strategy):
    """
    Momentum strategy riding price trend using exponential moving average (EMA)
    crossover combined with order book imbalance signaling.
    """

    def __init__(
        self,
        symbol: str,
        owner_id: str = "MOM_01",
        short_window: float = 0.2,  # EMA alpha
        long_window: float = 0.05,
        imbalance_threshold: float = 0.3,
        trade_quantity: float = 1.0,
    ):
        super().__init__(owner_id, [symbol])
        self.symbol = symbol
        self.short_alpha = short_window
        self.long_alpha = long_window
        self.imbalance_threshold = imbalance_threshold
        self.trade_quantity = trade_quantity
        self.short_ema: Optional[float] = None
        self.long_ema: Optional[float] = None
        self._order_counter: int = 0

    def on_market_data(
        self, symbol: str, timestamp: float, book_snapshot: Any, exchange: ExchangeVenue
    ) -> List[Order]:
        if symbol != self.symbol or book_snapshot.mid_price is None:
            return []

        mid = book_snapshot.mid_price
        imbalance = book_snapshot.imbalance

        if self.short_ema is None:
            self.short_ema = mid
            self.long_ema = mid
            return []

        # Update EMAs
        self.short_ema = (
            self.short_alpha * mid + (1.0 - self.short_alpha) * self.short_ema
        )
        self.long_ema = self.long_alpha * mid + (1.0 - self.long_alpha) * self.long_ema

        orders: List[Order] = []
        pos = self.positions.get(self.symbol, 0.0)

        # Bullish signal
        if (
            self.short_ema > self.long_ema
            and imbalance > self.imbalance_threshold
            and pos <= 0
        ):
            self._order_counter += 1
            order_id = f"MOM-BUY-{self.owner_id}-{self._order_counter}"
            orders.append(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=order_id,
                    client_order_id=f"C-{order_id}",
                    symbol=self.symbol,
                    side=Side.BUY,
                    order_type=OrderType.MARKET,
                    quantity=self.trade_quantity + abs(pos),
                    timestamp=timestamp,
                    owner_id=self.owner_id,
                )
            )

        # Bearish signal
        elif (
            self.short_ema < self.long_ema
            and imbalance < -self.imbalance_threshold
            and pos >= 0
        ):
            self._order_counter += 1
            order_id = f"MOM-SELL-{self.owner_id}-{self._order_counter}"
            orders.append(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=order_id,
                    client_order_id=f"C-{order_id}",
                    symbol=self.symbol,
                    side=Side.SELL,
                    order_type=OrderType.MARKET,
                    quantity=self.trade_quantity + abs(pos),
                    timestamp=timestamp,
                    owner_id=self.owner_id,
                )
            )

        return orders

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

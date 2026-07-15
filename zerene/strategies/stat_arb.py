"""
Statistical Arbitrage / Cointegration Pairs Trading strategy across two correlated symbols.
Uses zero-allocation object pooling (`GLOBAL_ORDER_POOL`).
"""

from typing import List, Any, Dict
from zerene.models import Order, Side, OrderType, Trade
from zerene.strategies.base import Strategy
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL


class StatArbPairsStrategy(Strategy):
    """
    Pairs trading strategy tracking the cointegrated spread between two symbols:
    Spread = Price_A - (beta * Price_B)
    """
    def __init__(
        self,
        symbol_a: str,
        symbol_b: str,
        owner_id: str = "STATARB_01",
        beta: float = 1.0,
        spread_mean: float = 0.0,
        spread_std: float = 10.0,
        z_entry: float = 2.0,
        trade_qty: float = 1.0,
    ):
        super().__init__(owner_id, [symbol_a, symbol_b])
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        self.beta = beta
        self.spread_mean = spread_mean
        self.spread_std = spread_std
        self.z_entry = z_entry
        self.trade_qty = trade_qty
        self.last_prices: Dict[str, float] = {}
        self._order_counter: int = 0

    def on_market_data(self, symbol: str, timestamp: float, book_snapshot: Any, exchange: ExchangeVenue) -> List[Order]:
        if book_snapshot.mid_price is not None:
            self.last_prices[symbol] = book_snapshot.mid_price

        if self.symbol_a not in self.last_prices or self.symbol_b not in self.last_prices:
            return []

        pa = self.last_prices[self.symbol_a]
        pb = self.last_prices[self.symbol_b]
        spread = pa - (self.beta * pb)
        z_score = (spread - self.spread_mean) / max(1e-9, self.spread_std)

        orders: List[Order] = []
        pos_a = self.positions.get(self.symbol_a, 0.0)
        pos_b = self.positions.get(self.symbol_b, 0.0)

        # Spread high -> Short A, Long B
        if z_score > self.z_entry and pos_a >= 0:
            self._order_counter += 1
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=f"SA-S-{self.owner_id}-{self._order_counter}",
                client_order_id=f"C-SA-S-{self._order_counter}",
                symbol=self.symbol_a,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=self.trade_qty + abs(pos_a),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))
            self._order_counter += 1
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=f"SA-B-{self.owner_id}-{self._order_counter}",
                client_order_id=f"C-SA-B-{self._order_counter}",
                symbol=self.symbol_b,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=(self.trade_qty * self.beta) + abs(pos_b),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))

        # Spread low -> Long A, Short B
        elif z_score < -self.z_entry and pos_a <= 0:
            self._order_counter += 1
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=f"SA-B-{self.owner_id}-{self._order_counter}",
                client_order_id=f"C-SA-B-{self._order_counter}",
                symbol=self.symbol_a,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=self.trade_qty + abs(pos_a),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))
            self._order_counter += 1
            orders.append(GLOBAL_ORDER_POOL.acquire(
                order_id=f"SA-S-{self.owner_id}-{self._order_counter}",
                client_order_id=f"C-SA-S-{self._order_counter}",
                symbol=self.symbol_b,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=(self.trade_qty * self.beta) + abs(pos_b),
                timestamp=timestamp,
                owner_id=self.owner_id,
            ))

        return orders

    def on_order_fill(self, trade: Trade, exchange: ExchangeVenue) -> List[Order]:
        if trade.symbol in (self.symbol_a, self.symbol_b):
            maker_side = Side.BUY if trade.aggressor_side == Side.SELL else Side.SELL
            taker_side = trade.aggressor_side
            if trade.maker_owner_id == self.owner_id:
                delta = trade.quantity if maker_side == Side.BUY else -trade.quantity
                self.positions[trade.symbol] = self.positions.get(trade.symbol, 0.0) + delta
            if trade.taker_owner_id == self.owner_id and trade.taker_owner_id != trade.maker_owner_id:
                delta = trade.quantity if taker_side == Side.BUY else -trade.quantity
                self.positions[trade.symbol] = self.positions.get(trade.symbol, 0.0) + delta
        return []

    def on_timer(self, timestamp: float, exchange: ExchangeVenue) -> List[Order]:
        return []

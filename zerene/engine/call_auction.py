"""
Opening & Closing Call Auction Uncrossing Engine for ZERENE.
Conforms to institutional exchange specifications (NASDAQ / NYSE / LSE call auctions).
Calculates single clearing price that maximizes total match volume, minimizes order imbalance,
and resolves price ties against reference market prices.
"""

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from zerene.models import Order, Side, OrderType, Trade, OrderStatus
from zerene.orderbook.book import OrderBook
from zerene.pools import GLOBAL_TRADE_POOL


@dataclass(slots=True)
class AuctionResult:
    """Encapsulates the result of a Call Auction uncrossing run."""

    clearing_price: Optional[float]
    executable_volume: float
    imbalance_quantity: float
    imbalance_side: Optional[Side]
    trades: List[Trade]


class CallAuctionEngine:
    """
    Call Auction Uncrossing Engine.
    Accumulates orders during PRE_MARKET / AUCTION sessions without immediate execution,
    then executes an atomic uncrossing at the single clearing price that maximizes volume.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.orders: List[Order] = []
        self._trade_counter = 0

    def add_order(self, order: Order) -> None:
        """Adds an order to the auction queue without matching."""
        self.orders.append(order)

    def calculate_clearing_price(
        self, reference_price: Optional[float] = None
    ) -> AuctionResult:
        """
        Calculates the single equilibrium clearing price according to institutional priority:
        1. Maximize total executable volume.
        2. Minimize order volume imbalance at that volume.
        3. Minimize distance to reference price (last trade price or previous close).
        """
        if not self.orders:
            return AuctionResult(None, 0.0, 0.0, None, [])

        # Collect candidate price levels from limit orders
        prices = set()
        bids: List[Order] = []
        asks: List[Order] = []

        for order in self.orders:
            if order.side == Side.BUY:
                bids.append(order)
                if order.price is not None:
                    prices.add(round(order.price, 4))
            else:
                asks.append(order)
                if order.price is not None:
                    prices.add(round(order.price, 4))

        if not prices:
            if reference_price:
                prices.add(round(reference_price, 4))
            else:
                return AuctionResult(None, 0.0, 0.0, None, [])

        sorted_prices = sorted(prices)
        best_price = None
        max_volume = -1.0
        min_imbalance = float("inf")
        min_ref_dist = float("inf")
        best_imbalance_side = None

        for p in sorted_prices:
            # Calculate cumulative buy demand at price p (bids with price >= p or MARKET)
            cum_buy = sum(
                o.remaining_quantity
                for o in bids
                if o.order_type == OrderType.MARKET
                or (o.price is not None and o.price >= p)
            )

            # Calculate cumulative sell supply at price p (asks with price <= p or MARKET)
            cum_sell = sum(
                o.remaining_quantity
                for o in asks
                if o.order_type == OrderType.MARKET
                or (o.price is not None and o.price <= p)
            )

            executable_vol = min(cum_buy, cum_sell)
            imbalance = abs(cum_buy - cum_sell)
            imb_side = (
                Side.BUY
                if cum_buy > cum_sell
                else (Side.SELL if cum_sell > cum_buy else None)
            )

            ref_dist = abs(p - reference_price) if reference_price is not None else 0.0

            # Compare against best candidate
            if executable_vol > max_volume:
                max_volume = executable_vol
                min_imbalance = imbalance
                min_ref_dist = ref_dist
                best_price = p
                best_imbalance_side = imb_side
            elif abs(executable_vol - max_volume) < 1e-9:
                if imbalance < min_imbalance:
                    min_imbalance = imbalance
                    min_ref_dist = ref_dist
                    best_price = p
                    best_imbalance_side = imb_side
                elif abs(imbalance - min_imbalance) < 1e-9:
                    if ref_dist < min_ref_dist:
                        min_ref_dist = ref_dist
                        best_price = p
                        best_imbalance_side = imb_side

        return AuctionResult(
            clearing_price=best_price,
            executable_volume=max_volume if max_volume > 0 else 0.0,
            imbalance_quantity=min_imbalance if max_volume > 0 else 0.0,
            imbalance_side=best_imbalance_side,
            trades=[],
        )

    def execute_uncrossing(
        self, timestamp: float, reference_price: Optional[float] = None
    ) -> Tuple[AuctionResult, List[Order]]:
        """
        Executes the uncrossing at the calculated clearing price.
        Returns the AuctionResult containing generated trades, and leftover unexecuted orders.
        """
        result = self.calculate_clearing_price(reference_price)
        if not result.clearing_price or result.executable_volume <= 1e-9:
            return result, self.orders

        clearing_price = result.clearing_price
        trades: List[Trade] = []

        # Sort bids (MARKET first, then highest price first, then earliest timestamp)
        eligible_bids = [
            o
            for o in self.orders
            if o.side == Side.BUY
            and (
                o.order_type == OrderType.MARKET
                or (o.price is not None and o.price >= clearing_price)
            )
        ]
        eligible_bids.sort(
            key=lambda o: (
                0 if o.order_type == OrderType.MARKET else 1,
                -(o.price or 0.0),
                o.timestamp,
            )
        )

        # Sort asks (MARKET first, then lowest price first, then earliest timestamp)
        eligible_asks = [
            o
            for o in self.orders
            if o.side == Side.SELL
            and (
                o.order_type == OrderType.MARKET
                or (o.price is not None and o.price <= clearing_price)
            )
        ]
        eligible_asks.sort(
            key=lambda o: (
                0 if o.order_type == OrderType.MARKET else 1,
                (o.price or float("inf")),
                o.timestamp,
            )
        )

        bid_idx = 0
        ask_idx = 0

        while bid_idx < len(eligible_bids) and ask_idx < len(eligible_asks):
            b_order = eligible_bids[bid_idx]
            a_order = eligible_asks[ask_idx]

            match_qty = min(b_order.remaining_quantity, a_order.remaining_quantity)
            if match_qty <= 1e-9:
                break

            self._trade_counter += 1
            trade_id = f"AUC-TRD-{self._trade_counter}"
            trade = GLOBAL_TRADE_POOL.acquire(
                trade_id=trade_id,
                maker_order_id=a_order.order_id,
                taker_order_id=b_order.order_id,
                symbol=self.symbol,
                price=clearing_price,
                quantity=match_qty,
                aggressor_side=Side.BUY,
                timestamp=timestamp,
                maker_owner_id=a_order.owner_id,
                taker_owner_id=b_order.owner_id,
            )
            trades.append(trade)

            b_order.filled_quantity += match_qty
            a_order.filled_quantity += match_qty

            if b_order.remaining_quantity <= 1e-9:
                b_order.status = OrderStatus.FILLED
                bid_idx += 1
            else:
                b_order.status = OrderStatus.PARTIALLY_FILLED

            if a_order.remaining_quantity <= 1e-9:
                a_order.status = OrderStatus.FILLED
                ask_idx += 1
            else:
                a_order.status = OrderStatus.PARTIALLY_FILLED

        result.trades = trades

        # Remaining orders that were not filled or partially filled
        remaining_orders = [o for o in self.orders if o.remaining_quantity > 1e-9]
        self.orders = []
        return result, remaining_orders

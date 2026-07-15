"""
Exchange Venue integrating matching engines, order gateways, fee schedules, and pre/post-trade risk checks.
"""

from typing import Dict, List, Optional, Tuple, Any
from zerene.models import Order, Trade, OrderEvent, EventType, Side
from zerene.engine.matching_engine import MatchingEngine
from zerene.risk.engine import RiskEngine
from zerene.latency.gateway import LatencyGateway


class ExchangeVenue:
    """
    Simulated Exchange Venue hosting matching engines across multiple symbols.
    Manages order ingestion, latency routing, fee schedules, and risk reconciliation.
    """
    def __init__(
        self,
        venue_name: str = "ZERENE-X",
        symbols: Optional[List[str]] = None,
        maker_fee_bps: float = -0.5,   # Maker rebate (-0.5 bps)
        taker_fee_bps: float = 2.0,    # Taker fee (+2.0 bps)
        risk_engine: Optional[RiskEngine] = None,
        latency_gateway: Optional[LatencyGateway] = None,
    ):
        self.venue_name = venue_name
        self.engines: Dict[str, MatchingEngine] = {}
        for sym in (symbols or ["BTC-USD", "ETH-USD"]):
            self.engines[sym] = MatchingEngine(sym)

        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.risk_engine = risk_engine or RiskEngine()
        self.latency_gateway = latency_gateway or LatencyGateway()
        self.risk_engine.on_kill_switch_callback = self.cancel_all_for_participant

    def add_symbol(self, symbol: str) -> MatchingEngine:
        if symbol not in self.engines:
            self.engines[symbol] = MatchingEngine(symbol)
        return self.engines[symbol]

    def cancel_all_for_participant(self, owner_id: str, reason: str = "KILL_SWITCH") -> List[Order]:
        """Cancels all resting orders across all symbol engines when a kill switch or mass cancel trips."""
        canceled: List[Order] = []
        for engine in self.engines.values():
            for o in engine.cancel_all_for_participant(owner_id):
                if o.reject_reason is None:
                    o.reject_reason = reason
                canceled.append(o)
        return canceled

    def submit_order(self, order: Order) -> Tuple[Order, List[Trade]]:
        """
        Submits an order through pre-trade risk validation and into the target matching engine.
        Also calculates exchange fee rebates and charges.
        """
        engine = self.engines.get(order.symbol)
        if not engine:
            engine = self.add_symbol(order.symbol)

        # Pre-trade risk validation
        is_valid, reject_reason = self.risk_engine.validate_order(order)
        if not is_valid:
            from zerene.models import OrderStatus
            order.status = OrderStatus.REJECTED
            order.reject_reason = reject_reason
            return order, []

        # Execute order in matching engine
        order, trades = engine.process_order(order)

        # Post-trade risk reconciliation and fee attribution
        for trade in trades:
            self.risk_engine.update_market_price(trade.symbol, trade.price)
            self.risk_engine.on_trade_fill(trade)

        return order, trades

    def cancel_order(self, symbol: str, order_id: str) -> Optional[Order]:
        engine = self.engines.get(symbol)
        if not engine:
            return None
        return engine.cancel_order(order_id)

    def modify_order(
        self,
        symbol: str,
        order_id: str,
        new_quantity: float,
        new_price: Optional[float] = None,
        timestamp: float = 0.0,
    ) -> Tuple[bool, Optional[Order], Optional[str]]:
        """Atomic Modify/Replace order passing through to venue's matching engine (`FIX 35=G`)."""
        engine = self.engines.get(symbol)
        if not engine:
            return False, None, "VENUE_ENGINE_NOT_FOUND"
        return engine.modify_order(order_id, new_quantity, new_price, timestamp)

    def get_order_book_snapshot(self, symbol: str, timestamp: float, levels: int = 10):
        engine = self.engines.get(symbol)
        if not engine:
            return None
        from zerene.orderbook.snapshots import OrderBookSnapshot
        return OrderBookSnapshot.from_book(engine.order_book, timestamp, levels)

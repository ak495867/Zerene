"""
Reactive Adverse Selection & Endogenous Liquidity Evaporation Agent.
Simulates predatory flow and background liquidity withdrawal when informed/toxic
participant orders cross the spread or execute large blocks.
"""

from dataclasses import dataclass
from typing import List, Optional
from zerene.models import Trade
from zerene.engine.matching_engine import MatchingEngine


@dataclass(slots=True)
class EvaporationEvent:
    timestamp: float
    trigger_trade_id: str
    withdrawn_volume: float
    spread_widened_ticks: int


class AdverseSelectionAgent:
    """
    Monitors executions in the MatchingEngine. When a participant sweeps liquidity
    or trades aggressively, this agent models real-world market maker defense:
    1. Cancels passive quotes sitting in the line of fire (liquidity evaporation).
    2. Widens quoted spread by shifting quotes outward.
    3. Increases subsequent quote replenishment latency (alpha decay).
    """

    def __init__(
        self,
        symbol: str,
        sensitivity_threshold_qty: float = 5.0,  # Block size triggering retreat
        evaporation_pct: float = 0.50,            # Cancel 50% of resting queue
        spread_widening_ticks: int = 2,           # Shift new quotes 2 ticks back
    ):
        self.symbol = symbol
        self.threshold = sensitivity_threshold_qty
        self.evaporation_pct = evaporation_pct
        self.spread_widening_ticks = spread_widening_ticks
        self.retreat_active: bool = False
        self.retreat_until_timestamp: float = 0.0

    def on_trade(
        self, trade: Trade, engine: MatchingEngine, current_time: float
    ) -> Optional[EvaporationEvent]:
        """
        Triggered when a trade occurs. If trade exceeds threshold, evaporates liquidity.
        """
        if trade.quantity < self.threshold:
            return None

        # Determine vulnerable side of the order book
        # If aggressive buyer bought, asks got hit -> resting sellers retreat
        side_to_prune = engine.order_book.asks if trade.taker_order_id else engine.order_book.bids

        withdrawn = 0.0
        # Evaporate top-of-book passive orders
        if side_to_prune:
            best_level_price = next(iter(side_to_prune.keys()))
            level = side_to_prune[best_level_price]

            # Collect orders at this level to cancel
            to_cancel: List[str] = []
            curr = level.head()
            while curr is not None and withdrawn < (trade.quantity * self.evaporation_pct):
                # Don't cancel participant's own orders
                if curr.owner_id != "PARTICIPANT":
                    to_cancel.append(curr.order_id)
                    withdrawn += curr.remaining_quantity
                curr = getattr(curr, "next_order", None)

            for oid in to_cancel:
                engine.cancel_order(oid)

        self.retreat_active = True
        self.retreat_until_timestamp = current_time + 1.0  # Retreat for 1 second

        return EvaporationEvent(
            timestamp=current_time,
            trigger_trade_id=trade.trade_id,
            withdrawn_volume=withdrawn,
            spread_widened_ticks=self.spread_widening_ticks,
        )

    def is_retreating(self, current_time: float) -> bool:
        """Returns True if background market makers are currently backing off."""
        if self.retreat_active and current_time >= self.retreat_until_timestamp:
            self.retreat_active = False
        return self.retreat_active

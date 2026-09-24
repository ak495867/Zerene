"""
Order Queue Position Tracking & Probability of Fill Estimator for ZERENE.
Calculates queue rank, volume ahead, and estimates probability of fill (P_fill)
given trade execution rate and cancellation intensity ahead in queue.
"""

import math
from dataclasses import dataclass
from typing import Optional
from zerene.orderbook.book import OrderBook


@dataclass(slots=True)
class QueueEstimate:
    """Estimated order queue metrics and probability of fill."""

    order_id: str
    price_level_rank: int  # 0 = Best Bid / Best Ask level
    orders_ahead: int
    volume_ahead: float
    my_display_quantity: float
    estimated_fill_time_sec: float
    prob_fill_10s: float
    prob_fill_60s: float


class OrderQueueEstimator:
    """
    Microstructure model tracking order queue dynamics and fill probability.
    """

    def __init__(self, default_trade_rate_per_sec: float = 2.0):
        self.default_trade_rate = default_trade_rate_per_sec

    def estimate_queue_position(
        self,
        book: OrderBook,
        order_id: str,
        trade_rate_per_sec: Optional[float] = None,
    ) -> Optional[QueueEstimate]:
        """
        Calculates exact queue rank and estimates probability of fill.
        """
        order = book.order_map.get(order_id)
        if not order or order.price is None:
            return None

        q_pos = book.get_queue_position(order_id)
        if not q_pos:
            return None

        rank, vol_ahead, orders_ahead = q_pos
        my_qty = order.display_quantity or order.quantity
        lambda_t = trade_rate_per_sec or self.default_trade_rate

        # Estimated fill time = volume ahead / trade rate
        est_fill_time = (vol_ahead + (my_qty * 0.5)) / max(0.01, lambda_t)

        # Probability of fill P(T) = 1 - exp(- (lambda * T) / (vol_ahead + my_qty))
        tot_vol_req = max(0.1, vol_ahead + my_qty)
        p_10s = 1.0 - math.exp(-(lambda_t * 10.0) / tot_vol_req)
        p_60s = 1.0 - math.exp(-(lambda_t * 60.0) / tot_vol_req)

        return QueueEstimate(
            order_id=order_id,
            price_level_rank=rank,
            orders_ahead=orders_ahead,
            volume_ahead=vol_ahead,
            my_display_quantity=my_qty,
            estimated_fill_time_sec=round(est_fill_time, 2),
            prob_fill_10s=min(1.0, max(0.0, p_10s)),
            prob_fill_60s=min(1.0, max(0.0, p_60s)),
        )

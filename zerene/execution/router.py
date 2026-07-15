"""
Institutional Smart Order Router (SOR) across multiple simulated exchange venues.
Optimizes execution using Level II/III depth snapshots, fee/rebate schedules, queue fill probability, and adverse selection risk.
Uses zero-allocation object pooling (`GLOBAL_ORDER_POOL`).
"""

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from zerene.models import Order, Side, OrderType
from zerene.engine.matching_engine import MatchingEngine
from zerene.orderbook.snapshots import OrderBookSnapshot
from zerene.pools import GLOBAL_ORDER_POOL


@dataclass
class VenueFeeSchedule:
    """Venue fee structure expressed in basis points (1 bps = 0.0001)."""
    maker_fee_bps: float = 0.0   # Negative value indicates maker rebate (e.g. -0.5 bps)
    taker_fee_bps: float = 2.0   # Taker execution fee


class SmartOrderRouter:
    """
    Smart Order Router (SOR) splits parent institutional orders across multiple venues.
    Analyzes:
    - Immutable Level II/III order book snapshot feeds across venues (enforcing strict causality without memory peeking)
    - Queue efficiency and fill probability estimation
    - Fee/rebate optimization (routing passive liquidity to maker rebate venues)
    - Effective execution price taking fee impact and adverse selection into account
    """
    def __init__(self, venues: Dict[str, MatchingEngine], fee_schedules: Optional[Dict[str, VenueFeeSchedule]] = None):
        self.venues = venues  # venue_id -> MatchingEngine
        self.fee_schedules = fee_schedules or {vid: VenueFeeSchedule() for vid in venues}
        self.latest_snapshots: Dict[str, OrderBookSnapshot] = {}

    def _acquire_child_order(self, parent: Order, venue_id: str, quantity: float) -> Order:
        return GLOBAL_ORDER_POOL.acquire(
            order_id=f"{parent.order_id}-{venue_id[:3]}",
            client_order_id=f"{parent.client_order_id}-{venue_id[:3]}",
            symbol=parent.symbol,
            side=parent.side,
            order_type=parent.order_type,
            quantity=quantity,
            price=parent.price,
            display_quantity=quantity if parent.display_quantity is not None else None,
            hidden_quantity=0.0,
            stop_price=parent.stop_price,
            time_in_force=parent.time_in_force,
            timestamp=parent.timestamp,
            owner_id=parent.owner_id,
        )

    def update_snapshot(self, venue_id: str, snapshot: OrderBookSnapshot) -> None:
        """Ingests an immutable L2 snapshot feed for a specific venue."""
        self.latest_snapshots[venue_id] = snapshot

    def route_order(
        self,
        order: Order,
        urgency: float = 0.5,
        max_depth_levels: int = 10,
        snapshots: Optional[Dict[str, OrderBookSnapshot]] = None,
    ) -> List[Tuple[str, Order]]:
        """
        Splits and routes an order across multiple venues based on immutable snapshot feeds.
        `urgency`: [0.0, 1.0]. Low urgency (<= 0.3) favors passive posting on rebate venues with short queues.
        High urgency (> 0.3) sweeps Level II depth minimizing total taker cost + slippage.
        """
        child_orders: List[Tuple[str, Order]] = []
        if not self.venues or order.quantity <= 0:
            return child_orders

        # Resolve snapshots for all venues without peeking directly into live mutable orderbook data structures
        resolved_snapshots: Dict[str, OrderBookSnapshot] = {}
        for vid, engine in self.venues.items():
            if snapshots and vid in snapshots:
                resolved_snapshots[vid] = snapshots[vid]
            elif vid in self.latest_snapshots:
                resolved_snapshots[vid] = self.latest_snapshots[vid]
            else:
                # Generate snapshot across wire boundary to enforce immutability
                resolved_snapshots[vid] = OrderBookSnapshot.from_book(engine.order_book, order.timestamp, max_depth_levels)

        is_passive = (order.order_type == OrderType.POST_ONLY or urgency <= 0.3) and order.order_type != OrderType.MARKET

        if is_passive:
            return self._route_passive_rebate_optimized(order, max_depth_levels, resolved_snapshots)
        else:
            return self._route_aggressive_level_ii_sweep(order, max_depth_levels, resolved_snapshots)

    def _route_passive_rebate_optimized(
        self,
        order: Order,
        max_depth_levels: int,
        snapshots: Dict[str, OrderBookSnapshot],
    ) -> List[Tuple[str, Order]]:
        """
        Routes passive limit orders dynamically by evaluating maker rebates and Level II queue depth.
        Score = maker_fee_bps + queue_penalty * volume_ahead_at_best_level
        """
        venue_scores: List[Tuple[str, float]] = []
        for venue_id in self.venues.keys():
            snap = snapshots.get(venue_id)
            if not snap:
                continue
            fee_sched = self.fee_schedules.get(venue_id, VenueFeeSchedule())
            maker_fee = fee_sched.maker_fee_bps

            # Check queue volume right where we would join from snapshot
            best_bid = snap.bids[0][0] if snap.bids else None
            best_ask = snap.asks[0][0] if snap.asks else None
            target_price = order.price or (best_bid if order.side == Side.BUY else best_ask)
            queue_vol = 0.0
            if target_price is not None:
                depth_list = snap.bids if order.side == Side.BUY else snap.asks
                for p, vol in depth_list:
                    if abs(p - target_price) < 1e-6:
                        queue_vol = vol
                        break

            # Lower score is better: maker rebate (-bps) minus penalty for long queues
            score = maker_fee + (queue_vol * 0.05)
            venue_scores.append((venue_id, score))

        if not venue_scores:
            return []

        venue_scores.sort(key=lambda x: x[1])  # Best passive venue first

        child_orders = []
        remaining_qty = order.quantity
        if len(venue_scores) > 1 and remaining_qty > 2.0:
            best_score = venue_scores[0][1]
            max_score = venue_scores[-1][1]
            if max_score == best_score:
                weights = [1.0 for _ in venue_scores]
            else:
                weights = [max(0.1, max_score - score + 1.0) for _, score in venue_scores]
            total_w = sum(weights)

            allocated_sum = 0.0
            allocations = []
            for (vid, _), w in zip(venue_scores, weights):
                alloc = round(remaining_qty * (w / total_w), 4)
                allocations.append((vid, alloc))
                allocated_sum += alloc

            # Adjust residual rounding onto best venue
            diff = round(remaining_qty - allocated_sum, 4)
            if abs(diff) > 1e-9 and allocations:
                allocations[0] = (allocations[0][0], round(allocations[0][1] + diff, 4))

            for vid, alloc in allocations:
                if alloc > 1e-9:
                    child_orders.append((vid, self._acquire_child_order(order, vid, alloc)))
        else:
            best_vid = venue_scores[0][0]
            child_orders.append((best_vid, self._acquire_child_order(order, best_vid, remaining_qty)))

        return child_orders

    def _route_aggressive_level_ii_sweep(
        self,
        order: Order,
        max_depth_levels: int,
        snapshots: Dict[str, OrderBookSnapshot],
    ) -> List[Tuple[str, Order]]:
        """
        Routes aggressive orders across Level II depth of all venues from immutable snapshot feeds.
        Calculates effective price = price * (1 + side * taker_fee_bps / 10000).
        Consumes cheapest effective liquidity tranches across all venues up to target quantity.
        """
        all_tranches: List[Tuple[str, float, float, float]] = []  # (venue_id, raw_price, effective_price, volume)

        for venue_id in self.venues.keys():
            snap = snapshots.get(venue_id)
            if not snap:
                continue
            fee_sched = self.fee_schedules.get(venue_id, VenueFeeSchedule())
            taker_fee = fee_sched.taker_fee_bps

            depth_list = snap.asks if order.side == Side.BUY else snap.bids

            for raw_price, vol in depth_list:
                if order.price is not None:
                    if (order.side == Side.BUY and raw_price > order.price) or (order.side == Side.SELL and raw_price < order.price):
                        continue
                # Calculate effective cost/proceeds per share including venue taker fee
                if order.side == Side.BUY:
                    eff_price = raw_price * (1.0 + taker_fee / 10_000.0)
                else:
                    eff_price = raw_price * (1.0 - taker_fee / 10_000.0)
                all_tranches.append((venue_id, raw_price, eff_price, vol))

        # Sort all tranches: lowest effective price for buy, highest for sell
        if order.side == Side.BUY:
            all_tranches.sort(key=lambda x: x[2])
        else:
            all_tranches.sort(key=lambda x: x[2], reverse=True)

        venue_allocations: Dict[str, float] = {}
        remaining_qty = order.quantity

        for venue_id, raw_price, eff_price, vol in all_tranches:
            if remaining_qty <= 1e-9:
                break
            take_vol = min(remaining_qty, vol)
            venue_allocations[venue_id] = venue_allocations.get(venue_id, 0.0) + take_vol
            remaining_qty -= take_vol

        # If still unallocated residual (e.g. order larger than total Level II depth across all venues),
        # distribute residual across all venues proportionally to their depth allocation or evenly.
        if remaining_qty > 1e-9:
            total_allocated = sum(venue_allocations.values())
            if total_allocated > 1e-9:
                for vid in list(venue_allocations.keys()):
                    weight = venue_allocations[vid] / total_allocated
                    venue_allocations[vid] += round(remaining_qty * weight, 4)
            else:
                n_venues = max(1, len(self.venues))
                even_split = round(remaining_qty / n_venues, 4)
                for vid in self.venues.keys():
                    venue_allocations[vid] = venue_allocations.get(vid, 0.0) + even_split

        child_orders: List[Tuple[str, Order]] = []
        for venue_id, alloc in venue_allocations.items():
            if alloc > 1e-9:
                child_orders.append((venue_id, self._acquire_child_order(order, venue_id, alloc)))

        return child_orders

    def route_limit_order(self, order: Order, snapshots: Optional[Dict[str, OrderBookSnapshot]] = None) -> List[Tuple[str, Order]]:
        """Backward compatible wrapper around route_order."""
        return self.route_order(order, urgency=0.5, snapshots=snapshots)

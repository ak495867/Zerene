"""
Comprehensive Verification Test Suite for ZERENE Batch #2 Architecture Upgrades:
1. SymbolSpecification & PeggedOrderManager
2. SIP Feed Delay & Latency Arbitrage Simulator
3. Institutional Footprint & Volume Profile Tracker
4. Order Queue Position & Probability-of-Fill Estimator
5. Neural Hawkes Process Generator
"""

import pytest
from zerene.models import Order, Side, OrderType
from zerene.engine.symbol_rules import SymbolSpecification
from zerene.engine.pegged import PeggedOrderManager
from zerene.latency.sip_simulator import SIPFeedSimulator
from zerene.analytics.footprint import FootprintTracker
from zerene.execution.queue_model import OrderQueueEstimator
from zerene.datasets.neural_hawkes import NeuralHawkesGenerator
from zerene.orderbook.book import OrderBook
from zerene.orderbook.snapshots import OrderBookSnapshot
from zerene.pools import GLOBAL_ORDER_POOL


def test_symbol_specification_and_pegged_orders():
    spec = SymbolSpecification(symbol="BTC-USD", tick_size=0.01, lot_size=1.0)

    # Valid order rounding
    o = Order("O1", "C1", "BTC-USD", Side.BUY, OrderType.LIMIT, 1.55, price=100.006)
    valid, reason = spec.validate_and_round_order(o)

    assert valid is True
    assert o.price == 100.01

    # Pegged order repricing
    pegged_mgr = PeggedOrderManager()
    peg_o = Order("P1", "CP1", "BTC-USD", Side.BUY, OrderType.MIDPOINT_PEG, 1.0)
    pegged_mgr.add_order(peg_o, offset=0.01)

    p = pegged_mgr.calculate_pegged_price(peg_o, best_bid=100.0, best_ask=100.2)
    assert p == 100.11


def test_sip_feed_simulator():
    sip = SIPFeedSimulator(sip_consolidation_latency_sec=0.002)

    # Direct vs SIP snapshots
    snap_fast = OrderBookSnapshot(
        "BTC-USD", 1.0, [(101.0, 10.0)], [(101.5, 10.0)], 101.25, 0.5, 0.0
    )
    snap_slow = OrderBookSnapshot(
        "BTC-USD", 1.0, [(100.0, 10.0)], [(100.5, 10.0)], 100.25, 0.5, 0.0
    )

    sip.publish_snapshot("VENUE_B", "BTC-USD", snap_slow, current_time=1.0)

    due = sip.get_due_sip_updates(current_time=1.001)
    assert len(due) == 0  # Not due until 1.002

    due_after = sip.get_due_sip_updates(current_time=1.003)
    assert len(due_after) == 1

    arbs = sip.calculate_latency_arbitrage_opportunity(
        {"VENUE_B": snap_fast}, {"VENUE_B": snap_slow}
    )
    assert len(arbs) > 0


def test_footprint_tracker():
    tracker = FootprintTracker(bar_duration_sec=60.0)

    from zerene.models import Trade

    t1 = Trade(
        "T1",
        "M1",
        "TK1",
        "BTC-USD",
        price=100.0,
        quantity=5.0,
        aggressor_side=Side.BUY,
        timestamp=1.0,
    )
    t2 = Trade(
        "T2",
        "M2",
        "TK2",
        "BTC-USD",
        price=100.0,
        quantity=2.0,
        aggressor_side=Side.SELL,
        timestamp=2.0,
    )

    tracker.on_trade(t1)
    tracker.on_trade(t2)

    summary = tracker.get_summary()
    assert summary["cvd"] == 3.0  # +5 buy -2 sell
    assert summary["latest_poc"] == 100.0


def test_order_queue_estimator():
    book = OrderBook("BTC-USD")
    o1 = Order("O1", "C1", "BTC-USD", Side.BUY, OrderType.LIMIT, 5.0, price=100.0)
    o2 = Order("O2", "C2", "BTC-USD", Side.BUY, OrderType.LIMIT, 3.0, price=100.0)

    book.insert_order(o1)
    book.insert_order(o2)

    estimator = OrderQueueEstimator(default_trade_rate_per_sec=2.0)
    est = estimator.estimate_queue_position(book, "O2")

    assert est is not None
    assert est.orders_ahead == 1
    assert est.volume_ahead == 5.0
    assert est.prob_fill_60s > 0.0


def test_neural_hawkes_generator():
    nh = NeuralHawkesGenerator(symbol="BTC-USD", seed=42)
    orders = nh.generate_step(current_time=1.0, dt=1.0, mid_price=100.0)

    assert isinstance(orders, list)

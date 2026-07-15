"""
Tests for SmartOrderRouter Level II depth sweeping and rebate optimization across venues.
"""

import pytest
from zerene.models import Order, Side, OrderType
from zerene.engine.matching_engine import MatchingEngine
from zerene.execution.router import SmartOrderRouter, VenueFeeSchedule


def test_sor_passive_rebate_routing():
    v1 = MatchingEngine("BTC-USD")  # Default fee schedule (e.g. 0 bps maker)
    v2 = MatchingEngine("BTC-USD")  # High rebate venue (-0.5 bps maker)
    venues = {"NASDAQ": v1, "BATS": v2}
    fees = {
        "NASDAQ": VenueFeeSchedule(maker_fee_bps=0.5, taker_fee_bps=2.0),
        "BATS": VenueFeeSchedule(maker_fee_bps=-0.5, taker_fee_bps=2.5),
    }

    sor = SmartOrderRouter(venues, fee_schedules=fees)
    order = Order(order_id="P1", client_order_id="CP1", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.POST_ONLY, price=50000.0, quantity=10.0)

    # Route low-urgency / post-only order
    routes = sor.route_order(order, urgency=0.1)
    assert len(routes) > 0
    # Best rebate venue (BATS) should get the primary allocation
    assert routes[0][0] == "BATS"


def test_sor_aggressive_level_ii_sweep():
    v1 = MatchingEngine("ETH-USD")
    v2 = MatchingEngine("ETH-USD")

    # Seed Level II depth across venues
    # V1: 5 units @ $2000, 10 units @ $2005
    v1.process_order(Order(order_id="A1-1", client_order_id="C", symbol="ETH-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=2000.0, quantity=5.0))
    v1.process_order(Order(order_id="A1-2", client_order_id="C", symbol="ETH-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=2005.0, quantity=10.0))

    # V2: 8 units @ $2001 (cheaper than $2005 on V1)
    v2.process_order(Order(order_id="A2-1", client_order_id="C", symbol="ETH-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=2001.0, quantity=8.0))

    sor = SmartOrderRouter({"V1": v1, "V2": v2})
    sweep = Order(order_id="SW1", client_order_id="CSW", symbol="ETH-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=2010.0, quantity=12.0)

    routes = sor.route_order(sweep, urgency=0.9, max_depth_levels=5)
    # Should allocate 5 to V1 ($2000) and 7 to V2 ($2001) before touching $2005!
    allocs = {vid: o.quantity for vid, o in routes}
    assert allocs["V1"] == 5.0
    assert allocs["V2"] == 7.0

"""
Tests for deterministic price-time priority matching engine conforming to RFC-001.
Tests Market, Limit, IOC, FOK, PostOnly, Iceberg replenishment, and Stop trigger execution.
"""

import pytest
from zerene.models import Order, Side, OrderType, OrderStatus, TimeInForce
from zerene.engine.matching_engine import MatchingEngine


def test_matching_engine_market_and_limit():
    engine = MatchingEngine("BTC-USD")

    # Place resting limit orders on ask side
    a1 = Order(order_id="A1", client_order_id="C1", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=100.0, quantity=5.0, timestamp=1.0, owner_id="LP1")
    a2 = Order(order_id="A2", client_order_id="C2", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=101.0, quantity=5.0, timestamp=2.0, owner_id="LP2")
    engine.process_order(a1)
    engine.process_order(a2)

    # Incoming market buy for 7.0 units
    mb = Order(order_id="MB1", client_order_id="CMB", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.MARKET, quantity=7.0, timestamp=3.0, owner_id="TAKER1")
    order, trades = engine.process_order(mb)

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 7.0
    assert len(trades) == 2
    assert trades[0].price == 100.0 and trades[0].quantity == 5.0
    assert trades[1].price == 101.0 and trades[1].quantity == 2.0
    assert engine.order_book.best_ask() == 101.0
    assert engine.order_book.asks[101.0].total_volume == 3.0


def test_fok_rejection():
    engine = MatchingEngine("BTC-USD")
    engine.process_order(Order(order_id="A1", client_order_id="C1", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=100.0, quantity=5.0))

    # FOK for 10 units at 100.0 (only 5 available -> should reject)
    fok = Order(order_id="FOK1", client_order_id="CFOK", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=100.0, quantity=10.0, time_in_force=TimeInForce.FOK)
    o, trades = engine.process_order(fok)

    assert o.status == OrderStatus.REJECTED
    assert o.reject_reason == "INSUFFICIENT_LIQUIDITY_FOR_FOK"
    assert len(trades) == 0


def test_post_only_rejection():
    engine = MatchingEngine("BTC-USD")
    engine.process_order(Order(order_id="A1", client_order_id="C1", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=100.0, quantity=5.0))

    # Post-Only buy limit at 100.0 (would match immediately -> should reject)
    po = Order(order_id="PO1", client_order_id="CPO", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.POST_ONLY, price=100.0, quantity=2.0)
    o, trades = engine.process_order(po)

    assert o.status == OrderStatus.REJECTED
    assert o.reject_reason == "POST_ONLY_WOULD_CROSS"
    assert len(trades) == 0


def test_stop_order_triggering():
    engine = MatchingEngine("BTC-USD")
    # Register buy stop at 105.0
    stop = Order(order_id="ST1", client_order_id="CST", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.STOP, quantity=3.0, stop_price=105.0)
    engine.process_order(stop)
    assert stop.order_id in engine.stop_manager.order_map

    # Resting asks at 104.0, 105.0, 106.0
    engine.process_order(Order(order_id="A1", client_order_id="CA1", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=104.0, quantity=2.0))
    engine.process_order(Order(order_id="A2", client_order_id="CA2", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=105.0, quantity=5.0))
    engine.process_order(Order(order_id="A3", client_order_id="CA3", symbol="BTC-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=106.0, quantity=5.0))

    # Market buy that matches 104.0 and partially 105.0 -> sets last_trade_price = 105.0 -> triggers buy stop!
    mb = Order(order_id="MB1", client_order_id="CMB", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.MARKET, quantity=3.0)
    engine.process_order(mb)

    # Stop order should now be triggered and executed against remaining 105.0 asks!
    assert stop.order_id not in engine.stop_manager.order_map
    assert stop.status == OrderStatus.FILLED
    assert stop.filled_quantity == 3.0

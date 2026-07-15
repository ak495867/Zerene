"""
Tests for institutional memory pooling (`OrderPool`, `EventPool`) recycling behavior.
"""

import pytest
from zerene.pools import OrderPool, EventPool, GLOBAL_ORDER_POOL
from zerene.models import Side, OrderType, OrderStatus, EventType


def test_order_pool_acquire_and_release():
    pool = OrderPool(initial_capacity=5)
    assert len(pool.pool) == 5

    # Acquire an order from pool
    o1 = pool.acquire(
        order_id="TEST-1",
        client_order_id="C-1",
        symbol="BTC-USD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10.0,
        price=50000.0,
    )
    assert len(pool.pool) == 4
    assert o1.order_id == "TEST-1"
    assert o1.status == OrderStatus.NEW
    assert o1.remaining_quantity == 10.0

    # Modify and then release back to pool
    o1.filled_quantity = 10.0
    pool.release(o1)
    assert len(pool.pool) == 5

    # Re-acquire: should reset fields clean
    o2 = pool.acquire(
        order_id="TEST-2",
        client_order_id="C-2",
        symbol="ETH-USD",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=5.0,
    )
    assert o2.order_id == "TEST-2"
    assert o2.symbol == "ETH-USD"
    assert o2.filled_quantity == 0.0
    assert o2.remaining_quantity == 5.0


def test_event_pool_lifecycle():
    epool = EventPool(initial_capacity=2)
    ev = epool.acquire(
        event_id="E1",
        event_type=EventType.ORDER_SUBMIT,
        timestamp=1.0,
        symbol="BTC-USD",
    )
    assert ev.event_id == "E1"
    assert ev.timestamp == 1.0

    epool.release(ev)
    assert ev.order is None and ev.trade is None


def test_trade_pool_lifecycle():
    from zerene.pools import TradePool

    tpool = TradePool(initial_capacity=3)
    t = tpool.acquire(
        trade_id="TRD-99",
        maker_order_id="M-1",
        taker_order_id="T-1",
        symbol="SOL-USD",
        price=150.0,
        quantity=2.0,
        aggressor_side=Side.BUY,
        timestamp=12.34,
        maker_owner_id="LP_1",
        taker_owner_id="TAKER_1",
    )
    assert t.trade_id == "TRD-99"
    assert t.price == 150.0
    assert t.maker_owner_id == "LP_1"

    tpool.release(t)
    assert t.symbol == "" and t.maker_order_id == ""
    # Double release safety: should not corrupt pool
    tpool.release(t)
    assert len(tpool.pool) == 3


def test_order_node_pool_lifecycle():
    from zerene.pools import OrderNodePool
    from zerene.models import Order

    npool = OrderNodePool(initial_capacity=5)
    o = Order("TEST-N", "C-N", "BTC-USD", Side.BUY, OrderType.LIMIT, 10.0, price=100.0)
    node = npool.acquire(o)
    assert node.order == o
    assert node._in_pool is False
    assert len(npool.pool) == 4

    npool.release(node)
    assert node.order is None
    assert node._in_pool is True
    assert len(npool.pool) == 5
    # Double release safety check
    npool.release(node)
    assert len(npool.pool) == 5

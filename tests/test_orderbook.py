"""
Tests for FIFO limit order book, queue position indexing, and depth snapshots.
"""

import pytest
from zerene.models import Order, Side, OrderType
from zerene.orderbook.book import OrderBook
from zerene.orderbook.snapshots import OrderBookSnapshot


def test_orderbook_fifo_priority_and_depth():
    book = OrderBook("BTC-USD")

    # Insert buy orders at same price (100.0)
    o1 = Order(
        order_id="B1",
        client_order_id="CB1",
        symbol="BTC-USD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=100.0,
        quantity=5.0,
        timestamp=1.0,
    )
    o2 = Order(
        order_id="B2",
        client_order_id="CB2",
        symbol="BTC-USD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=100.0,
        quantity=3.0,
        timestamp=2.0,
    )
    book.insert_order(o1)
    book.insert_order(o2)

    assert book.best_bid() == 100.0
    assert book.bids[100.0].total_volume == 8.0

    # Queue position check
    rank, vol_ahead, orders_ahead = book.get_queue_position("B2")
    assert rank == 0
    assert vol_ahead == 5.0
    assert orders_ahead == 1

    # Insert asks
    a1 = Order(
        order_id="A1",
        client_order_id="CA1",
        symbol="BTC-USD",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=101.0,
        quantity=4.0,
        timestamp=1.5,
    )
    book.insert_order(a1)

    assert book.best_ask() == 101.0
    assert book.spread() == 1.0
    assert book.mid_price() == 100.5

    bids_depth, asks_depth = book.get_depth(levels=5)
    assert bids_depth == [(100.0, 8.0)]
    assert asks_depth == [(101.0, 4.0)]


def test_orderbook_snapshot():
    book = OrderBook("ETH-USD")
    book.insert_order(
        Order(
            order_id="E1",
            client_order_id="C1",
            symbol="ETH-USD",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=2000.0,
            quantity=10.0,
        )
    )
    book.insert_order(
        Order(
            order_id="E2",
            client_order_id="C2",
            symbol="ETH-USD",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=2010.0,
            quantity=5.0,
        )
    )

    snap = OrderBookSnapshot.from_book(book, timestamp=10.0)
    assert snap.mid_price == 2005.0
    assert snap.spread == 10.0
    assert snap.imbalance == (10.0 - 5.0) / 15.0
    assert snap.to_dict()["symbol"] == "ETH-USD"

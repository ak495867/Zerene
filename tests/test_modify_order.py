"""
Tests for atomic Modify/Replace order (`FIX 35=G`) and time priority preservation vs loss rules.
"""

import pytest
from zerene.models import Order, Side, OrderType, OrderStatus
from zerene.orderbook.book import OrderBook
from zerene.engine.matching_engine import MatchingEngine
from zerene.exchange.venue import ExchangeVenue


def test_priority_preservation_on_quantity_reduction():
    book = OrderBook("BTC-USD")
    # Insert two buy limit orders at same price $100.0
    o1 = Order(order_id="B1", client_order_id="CB1", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=100.0, quantity=10.0, timestamp=1.0)
    o2 = Order(order_id="B2", client_order_id="CB2", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=100.0, quantity=5.0, timestamp=2.0)
    book.insert_order(o1)
    book.insert_order(o2)

    # Check initial queue positions
    rank1, vol_ahead1, orders_ahead1 = book.get_queue_position("B1")
    rank2, vol_ahead2, orders_ahead2 = book.get_queue_position("B2")
    assert orders_ahead1 == 0
    assert orders_ahead2 == 1 and vol_ahead2 == 10.0

    # Modify B1: reduce quantity from 10.0 to 6.0 without changing price
    is_ok, modified, reason = book.modify_order("B1", new_quantity=6.0, new_price=None, timestamp=3.0)
    assert is_ok is True
    assert reason == "PRIORITY_PRESERVED_REPLACED"
    assert modified.quantity == 6.0
    assert modified.status == OrderStatus.REPLACED

    # B1 should STILL be head of the queue (priority preserved!)
    assert book.bids[100.0].orders[0].order_id == "B1"
    assert book.bids[100.0].total_volume == 11.0  # 6.0 + 5.0
    _, new_vol_ahead2, _ = book.get_queue_position("B2")
    assert new_vol_ahead2 == 6.0


def test_priority_loss_on_quantity_increase_or_price_change():
    book = OrderBook("BTC-USD")
    o1 = Order(order_id="B1", client_order_id="CB1", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=100.0, quantity=10.0, timestamp=1.0)
    o2 = Order(order_id="B2", client_order_id="CB2", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=100.0, quantity=5.0, timestamp=2.0)
    book.insert_order(o1)
    book.insert_order(o2)

    # Modify B1: increase quantity to 15.0 -> loses priority!
    is_ok, mod, reason = book.modify_order("B1", new_quantity=15.0, new_price=100.0, timestamp=4.0)
    assert reason == "PRIORITY_LOST_REPLACED"
    # B2 should now be at the front of the queue, and B1 at the rear!
    assert book.bids[100.0].orders[0].order_id == "B2"
    assert book.bids[100.0].orders[1].order_id == "B1"


def test_matching_engine_and_venue_modify_crossing():
    venue = ExchangeVenue("VENUE-MOD", symbols=["ETH-USD"])
    engine = venue.engines["ETH-USD"]
    # Resting ask at $2000.0
    engine.process_order(Order(order_id="A1", client_order_id="CA1", symbol="ETH-USD", side=Side.SELL, order_type=OrderType.LIMIT, price=2000.0, quantity=10.0))
    # Resting buy limit at $1990.0
    engine.process_order(Order(order_id="B1", client_order_id="CB1", symbol="ETH-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=1990.0, quantity=5.0))

    # Modify B1: change price upward to $2000.0 -> should immediately match against resting A1!
    is_ok, mod_order, reason = venue.modify_order("ETH-USD", "B1", new_quantity=5.0, new_price=2000.0)
    assert is_ok is True
    assert mod_order.status == OrderStatus.FILLED
    assert mod_order.filled_quantity == 5.0

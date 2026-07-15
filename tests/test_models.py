"""
Tests for core data models and order lifecycle enums.
"""

import pytest
from zerene.models import Order, Side, OrderType, OrderStatus, TimeInForce


def test_order_initialization_defaults():
    order = Order(
        order_id="ORD-1",
        client_order_id="CLIENT-1",
        symbol="BTC-USD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=50000.0,
        quantity=2.5,
    )
    assert order.display_quantity == 2.5
    assert order.hidden_quantity == 0.0
    assert order.remaining_quantity == 2.5
    assert order.is_active is True
    assert order.status == OrderStatus.NEW


def test_iceberg_order_split():
    order = Order(
        order_id="ICE-1",
        client_order_id="CLIENT-ICE",
        symbol="ETH-USD",
        side=Side.SELL,
        order_type=OrderType.ICEBERG,
        price=3000.0,
        quantity=10.0,
        display_quantity=2.0,
    )
    assert order.display_quantity == 2.0
    assert order.hidden_quantity == 8.0
    assert order.remaining_quantity == 10.0


def test_hidden_order():
    order = Order(
        order_id="HID-1",
        client_order_id="CLIENT-HID",
        symbol="BTC-USD",
        side=Side.BUY,
        order_type=OrderType.HIDDEN,
        price=50000.0,
        quantity=5.0,
    )
    assert order.display_quantity == 0.0
    assert order.hidden_quantity == 5.0

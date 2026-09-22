"""Regression tests for public input validation and order-book query contracts."""

import math

import pytest

from zerene.exchange.venue import ExchangeVenue
from zerene.models import Order, OrderStatus, OrderType, Side
from zerene.orderbook.book import OrderBook


def make_order(**overrides):
    values = {
        "order_id": "ORDER-1",
        "client_order_id": "CLIENT-1",
        "symbol": "BTC-USD",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": 1.0,
        "price": 100.0,
    }
    values.update(overrides)
    return Order(**values)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("quantity", 0.0, "INVALID_QUANTITY"),
        ("quantity", -1.0, "INVALID_QUANTITY"),
        ("quantity", math.nan, "INVALID_QUANTITY"),
        ("price", -1.0, "INVALID_PRICE"),
        ("price", math.inf, "INVALID_PRICE"),
        ("stop_price", 0.0, "INVALID_STOP_PRICE"),
    ],
)
def test_invalid_orders_are_rejected_before_matching(field, value, reason):
    venue = ExchangeVenue(symbols=["BTC-USD"])
    order, trades = venue.submit_order(make_order(**{field: value}))

    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == reason
    assert trades == []
    assert venue.engines["BTC-USD"].order_book.order_map == {}


def test_order_validation_accepts_normal_limit_order():
    order = make_order()

    assert order.validate() is None


def test_depth_rejects_negative_or_non_integer_levels():
    book = OrderBook("BTC-USD")

    with pytest.raises(ValueError, match="non-negative integer"):
        book.get_depth(-1)
    with pytest.raises(ValueError, match="non-negative integer"):
        book.get_depth(1.5)
    with pytest.raises(ValueError, match="non-negative integer"):
        book.get_depth(True)


def test_depth_zero_is_a_valid_empty_query():
    book = OrderBook("BTC-USD")

    assert book.get_depth(0) == ([], [])

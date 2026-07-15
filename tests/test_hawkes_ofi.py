"""
Tests for multi-kernel Hawkes processes, OFI conditioning, and Level III tick loaders.
"""

import pytest
from zerene.datasets.generator import SyntheticFlowGenerator
from zerene.datasets.loader import TickDataLoader
from zerene.models import Side, OrderType


def test_hawkes_and_ofi_conditioning():
    gen = SyntheticFlowGenerator(
        symbol="SOL-USD", base_rate_buy=10.0, base_rate_sell=10.0
    )
    assert gen.intensity_buy == 10.0 and gen.intensity_sell == 10.0

    # Inject strong positive OFI (heavy buying imbalance)
    gen.update_ofi(bid_vol_change=50.0, ask_vol_change=10.0)  # OFI = +40.0
    orders = gen.generate_batch(current_time=1.0, dt=1.0, mid_price=150.0)
    assert len(orders) > 0
    # Intensity should have increased due to self and cross excitation
    assert gen.intensity_buy > 10.0 or gen.intensity_sell > 10.0


def test_tick_loader_from_dicts():
    records = [
        {
            "timestamp": 0.1,
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 100.0,
            "quantity": 2.5,
            "order_id": "D1",
        },
        {
            "timestamp": 0.2,
            "side": "SELL",
            "order_type": "MARKET",
            "quantity": 1.0,
            "order_id": "D2",
        },
    ]
    orders = list(TickDataLoader.from_dicts(records, symbol="BTC-USD"))
    assert len(orders) == 2
    assert orders[0].price == 100.0 and orders[0].side == Side.BUY
    assert orders[1].order_type == OrderType.MARKET and orders[1].quantity == 1.0

"""
Tests for real-time risk tracking engine, VaR/CVaR, and automated kill switch.
"""

import pytest
from zerene.models import Order, Side, OrderType, Trade
from zerene.risk.limits import RiskLimits
from zerene.risk.engine import RiskEngine


def test_risk_engine_position_limit_rejection():
    risk = RiskEngine()
    limits = RiskLimits(max_position_per_symbol=10.0)
    risk.register_participant("TRADER1", limits=limits)

    # Order for 15 units exceeds max position limit
    order = Order(order_id="O1", client_order_id="C1", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=50000.0, quantity=15.0, owner_id="TRADER1")
    is_valid, reason = risk.validate_order(order)
    assert is_valid is False
    assert reason == "POSITION_LIMIT_EXCEEDED"


def test_kill_switch_on_drawdown():
    risk = RiskEngine()
    limits = RiskLimits(max_drawdown_pct=0.10)
    state = risk.register_participant("TRADER_DD", initial_capital=100_000.0, limits=limits)

    # Simulate heavy losing trade
    trade = Trade(
        trade_id="TRD1", maker_order_id="M1", taker_order_id="T1", symbol="BTC-USD",
        price=90.0, quantity=100.0, aggressor_side=Side.SELL, timestamp=1.0,
        maker_owner_id="TRADER_DD", taker_owner_id="OTHER"
    )
    # Suppose average price was 105.0 -> loss = 100 * (105 - 90) = $1500 (1.5% DD, passes)
    state.positions["BTC-USD"] = 100.0
    state.average_prices["BTC-USD"] = 105.0
    risk.on_trade_fill(trade)
    assert state.kill_switch_active is False

    # Simulate catastrophic loss ($12,000 loss -> > 10% DD -> trips kill switch)
    trade2 = Trade(
        trade_id="TRD2", maker_order_id="M2", taker_order_id="T2", symbol="BTC-USD",
        price=10.0, quantity=150.0, aggressor_side=Side.SELL, timestamp=2.0,
        maker_owner_id="TRADER_DD", taker_owner_id="OTHER"
    )
    state.positions["BTC-USD"] = 150.0
    state.average_prices["BTC-USD"] = 100.0
    risk.on_trade_fill(trade2)

    assert state.kill_switch_active is True
    assert "RISK_LIMIT_BREACH" in state.kill_switch_reason


def test_kill_switch_mass_cancel_resting_orders():
    from zerene.exchange.venue import ExchangeVenue
    from zerene.models import OrderStatus

    venue = ExchangeVenue(symbols=["BTC-USD"])
    limits = RiskLimits(max_drawdown_pct=0.10)
    state = venue.risk_engine.register_participant("TRADER_BLOWUP", initial_capital=100_000.0, limits=limits)

    # Place resting limit and stop orders on venue
    o_limit = Order(
        order_id="REST-1", client_order_id="C-R1", symbol="BTC-USD", side=Side.BUY,
        order_type=OrderType.LIMIT, price=45000.0, quantity=1.0, owner_id="TRADER_BLOWUP"
    )
    o_stop = Order(
        order_id="STOP-1", client_order_id="C-S1", symbol="BTC-USD", side=Side.SELL,
        order_type=OrderType.STOP, stop_price=40000.0, quantity=1.0, owner_id="TRADER_BLOWUP"
    )
    venue.submit_order(o_limit)
    venue.submit_order(o_stop)

    # Confirm both orders are resting
    engine = venue.engines["BTC-USD"]
    assert "REST-1" in engine.order_book.order_map
    assert len(engine.stop_manager.order_map) == 1

    # Trip kill switch via severe trade fill loss
    state.positions["BTC-USD"] = 10.0
    state.average_prices["BTC-USD"] = 50000.0
    loss_trade = Trade(
        trade_id="TRD-LOSS", maker_order_id="M-X", taker_order_id="T-X", symbol="BTC-USD",
        price=1000.0, quantity=10.0, aggressor_side=Side.SELL, timestamp=5.0,
        maker_owner_id="TRADER_BLOWUP", taker_owner_id="OTHER"
    )
    venue.risk_engine.on_trade_fill(loss_trade)

    # Confirm kill switch tripped and all resting orders were canceled right away!
    assert state.kill_switch_active is True
    assert "REST-1" not in engine.order_book.order_map
    assert len(engine.stop_manager.order_map) == 0
    assert o_limit.status == OrderStatus.CANCELED
    assert o_limit.reject_reason is not None and "RISK_LIMIT_BREACH" in o_limit.reject_reason

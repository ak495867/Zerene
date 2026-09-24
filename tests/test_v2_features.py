"""
Comprehensive Verification Test Suite for ZERENE Next-Gen Architecture Upgrades:
1. Call Auction Uncrossing Engine
2. Self-Trade Prevention (STP)
3. Event Logger & Market Replay Engine
4. Multi-Agent Reinforcement Learning Environment
5. SPAN Portfolio Margin & Liquidation Engine
"""

import os
import tempfile
import pytest
from zerene.models import Order, Side, OrderType, OrderStatus, STPMode
from zerene.engine.call_auction import CallAuctionEngine
from zerene.engine.matching_engine import MatchingEngine
from zerene.replay.logger import EventLogger
from zerene.replay.engine import MarketReplayEngine
from zerene.strategies.marl_env import MultiAgentRLMarketEnv
from zerene.risk.span import SPANPortfolioRiskEngine
from zerene.exchange.venue import ExchangeVenue


def test_call_auction_uncrossing():
    engine = CallAuctionEngine("BTC-USD")
    
    # Bids
    engine.add_order(Order("B1", "CB1", "BTC-USD", Side.BUY, OrderType.LIMIT, 10.0, price=105.0))
    engine.add_order(Order("B2", "CB2", "BTC-USD", Side.BUY, OrderType.LIMIT, 5.0, price=102.0))
    
    # Asks
    engine.add_order(Order("A1", "CA1", "BTC-USD", Side.SELL, OrderType.LIMIT, 8.0, price=100.0))
    engine.add_order(Order("A2", "CA2", "BTC-USD", Side.SELL, OrderType.LIMIT, 10.0, price=104.0))

    result, remaining = engine.execute_uncrossing(timestamp=1.0, reference_price=100.0)
    
    assert result.clearing_price == 104.0
    assert result.executable_volume == 10.0
    assert len(result.trades) > 0


def test_self_trade_prevention_cancel_newest():
    engine = MatchingEngine("BTC-USD")
    
    # Resting Buy Order from TRADER_A
    engine.process_order(Order("B1", "CB1", "BTC-USD", Side.BUY, OrderType.LIMIT, 5.0, price=100.0, owner_id="TRADER_A"))
    
    # Incoming Sell Order from same TRADER_A with CANCEL_NEWEST
    sell_order, trades = engine.process_order(
        Order("A1", "CA1", "BTC-USD", Side.SELL, OrderType.LIMIT, 5.0, price=100.0, owner_id="TRADER_A", stp_mode=STPMode.CANCEL_NEWEST)
    )
    
    assert len(trades) == 0
    assert sell_order.status == OrderStatus.CANCELED
    assert sell_order.reject_reason == "STP_CANCEL_NEWEST"


def test_self_trade_prevention_cancel_oldest():
    engine = MatchingEngine("BTC-USD")
    
    # Resting Buy Order from TRADER_A
    engine.process_order(Order("B1", "CB1", "BTC-USD", Side.BUY, OrderType.LIMIT, 5.0, price=100.0, owner_id="TRADER_A"))
    
    # Incoming Sell Order from same TRADER_A with CANCEL_OLDEST
    sell_order, trades = engine.process_order(
        Order("A1", "CA1", "BTC-USD", Side.SELL, OrderType.LIMIT, 5.0, price=100.0, owner_id="TRADER_A", stp_mode=STPMode.CANCEL_OLDEST)
    )
    
    assert len(trades) == 0
    assert "B1" not in engine.order_book.order_map


def test_event_logger_and_replay():
    with tempfile.TemporaryDirectory() as tmpdir:
        logfile = os.path.join(tmpdir, "test_replay.zlog.gz")
        
        # Log events
        with EventLogger(logfile) as logger:
            logger.log_event(1.0, "ORDER_SUBMIT", "BTC-USD", {
                "order": {"order_id": "O1", "side": "BUY", "order_type": "LIMIT", "price": 100.0, "quantity": 2.0}
            })
            logger.log_event(2.0, "ORDER_SUBMIT", "BTC-USD", {
                "order": {"order_id": "O2", "side": "SELL", "order_type": "MARKET", "quantity": 1.0}
            })

        # Replay events
        replay = MarketReplayEngine(logfile)
        res = replay.run_replay()
        
        assert res["replayed_events"] == 2
        assert res["total_trades"] == 1


def test_marl_environment():
    env = MultiAgentRLMarketEnv(agent_ids=["agent_0", "agent_1"], symbol="BTC-USD", max_steps=10)
    obs = env.reset()
    
    assert "agent_0" in obs
    assert "agent_1" in obs
    
    actions = {"agent_0": 1, "agent_1": 3}  # Agent 0 limit buy, Agent 1 market buy
    next_obs, rewards, terminateds, truncateds, info = env.step(actions)
    
    assert "agent_0" in rewards
    assert "agent_1" in rewards


def test_span_portfolio_risk_and_liquidation():
    span = SPANPortfolioRiskEngine()
    span.set_cash_balance("FUND_X", -10_000.0)  # Leveraged position with borrowed cash
    span.update_position("FUND_X", "BTC-USD", 100.0)  # Large long position
    
    market_prices = {"BTC-USD": 100.0}
    margin = span.calculate_portfolio_margin("FUND_X", market_prices)
    
    assert margin.initial_margin_required > 0
    
    # Price crash causing margin shortfall and liquidation
    market_prices_crash = {"BTC-USD": 50.0}
    exchange = ExchangeVenue("RISK-X")
    liq_orders = span.execute_liquidation_cascade("FUND_X", exchange, market_prices_crash)
    
    assert len(liq_orders) > 0
    assert liq_orders[0].side == Side.SELL

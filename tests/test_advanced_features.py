"""
Unit and integration tests for Pillar 1-4 advanced features:
- CircuitBreakers (LULD price collars)
- FeeSchedule (Maker rebates & Taker fee curves)
- Nasdaq ITCH 5.0 binary parser
- AdverseSelectionAgent (reactive liquidity evaporation)
- VectorRLTradingEnvironment (Gymnasium multi-env)
- GoldenVector matching hash reproducibility
- Benchmark visualizer HTML generation
"""

import io
import struct
import tempfile
import numpy as np
from zerene.engine.circuit_breaker import CircuitBreaker, CircuitBreakerState
from zerene.exchange.fees import FeeSchedule
from zerene.exchange.venue import ExchangeVenue
from zerene.datasets.itch_parser import ITCH50Parser
from zerene.strategies.adverse_selection import AdverseSelectionAgent
from zerene.strategies.vector_env import VectorRLTradingEnvironment
from zerene.benchmarks.golden_vector import GoldenVectorHarness
from zerene.benchmarks.visualizer import BenchmarkReportGenerator
from zerene.models import Order, Side, OrderType, Trade


def test_circuit_breaker_luld():
    cb = CircuitBreaker("BTC-USD", initial_reference_price=100.0, band_pct=0.05)
    # Lower band = 95.0, Upper band = 105.0
    assert cb.lower_band == 95.0
    assert cb.upper_band == 105.0

    # Order inside band -> passes
    valid_order = Order(
        "O1", "C1", "BTC-USD", Side.BUY, OrderType.LIMIT, price=102.0, quantity=1.0
    )
    ok, err = cb.validate_order(valid_order)
    assert ok is True
    assert err is None

    # Order outside band -> rejected
    violating_order = Order(
        "O2", "C2", "BTC-USD", Side.BUY, OrderType.LIMIT, price=108.0, quantity=1.0
    )
    ok, err = cb.validate_order(violating_order)
    assert ok is False
    assert "LULD_PRICE_COLLAR_BREACH" in err

    # Manual halt
    cb.trigger_halt(current_time=10.0)
    assert cb.state == CircuitBreakerState.HALTED
    ok, err = cb.validate_order(valid_order, current_time=15.0)
    assert ok is False
    assert "TRADING_HALTED" in err


def test_fee_schedule_rebates():
    schedule = FeeSchedule()
    # Retail (0 volume): Maker 1 bps, Taker 5 bps
    m_bps, t_bps = schedule.get_tier_fees(participant_volume_30d=50_000.0)
    assert m_bps == 1.0
    assert t_bps == 5.0

    # Institutional VIP 2 (> 1M volume): Maker -0.5 bps (rebate!), Taker 2.0 bps
    m_bps, t_bps = schedule.get_tier_fees(participant_volume_30d=2_000_000.0)
    assert m_bps == -0.5
    assert t_bps == 2.0

    # Rebate calculation on $100,000 notional: -$5.00
    fee = schedule.calculate_trade_fees(
        notional_value=100_000.0, is_maker=True, participant_volume_30d=2_000_000.0
    )
    assert fee == -5.0


def test_itch_50_binary_parser():
    # Construct synthetic ITCH 'A' (Add Order) binary message
    # Format: len(H=36), msg_type('A'), stock_locate(H=1), tracking(H=1), ts(6s), ref_num(Q=9999), side(c=b'B'), shares(I=100), stock(8s=b'AAPL    '), price(I=1500000 = $150.00)
    msg_type = b"A"
    locate = 1
    tracking = 1
    ts_bytes = (1000000).to_bytes(6, byteorder="big")
    ref_num = 9999
    side = b"B"
    shares = 100
    stock = b"AAPL    "
    raw_price = 1500000  # $150.00

    payload = struct.pack(
        ">cHH6sQcI8sI",
        msg_type,
        locate,
        tracking,
        ts_bytes,
        ref_num,
        side,
        shares,
        stock,
        raw_price,
    )
    stream = io.BytesIO(struct.pack(">H", len(payload)) + payload)

    parsed = list(ITCH50Parser.parse_stream(stream))
    assert len(parsed) == 1
    m = parsed[0]
    assert m.msg_type == "A"
    assert m.order_ref_num == 9999
    assert m.shares == 100
    assert m.price == 150.0
    assert m.stock == "AAPL"

    # Convert to ZERENE Order
    order = ITCH50Parser.to_zerene_order(m)
    assert order is not None
    assert order.price == 150.0
    assert order.quantity == 100.0


def test_adverse_selection_agent():
    venue = ExchangeVenue(symbols=["TEST-USD"])
    engine = venue.engines["TEST-USD"]

    # Seed passive asks
    for i in range(1, 4):
        engine.process_order(
            Order(
                f"A-{i}",
                "C",
                "TEST-USD",
                Side.SELL,
                OrderType.LIMIT,
                price=100.0 + i * 0.1,
                quantity=10.0,
                owner_id="LP",
            )
        )

    agent = AdverseSelectionAgent("TEST-USD", sensitivity_threshold_qty=5.0)

    # Big aggressive sweep trade triggers evaporation
    trade = Trade(
        trade_id="TRD-1",
        maker_order_id="A-1",
        taker_order_id="T-TAKER",
        symbol="TEST-USD",
        price=100.1,
        quantity=10.0,
        aggressor_side=Side.BUY,
        timestamp=0.0,
    )
    evap = agent.on_trade(trade, engine, current_time=1.0)

    assert evap is not None
    assert evap.withdrawn_volume > 0.0
    assert agent.is_retreating(current_time=1.5) is True


def test_vector_rl_env():
    vec_env = VectorRLTradingEnvironment(num_envs=2, max_steps=10)
    obs, infos = vec_env.reset()
    assert obs.shape == (2, 6)

    actions = np.array([1, 2])  # Env 0: Buy limit, Env 1: Sell limit
    next_obs, rewards, term, trunc, infos = vec_env.step(actions)
    assert next_obs.shape == (2, 6)
    assert rewards.shape == (2,)


def test_golden_vector_determinism():
    res1 = GoldenVectorHarness.execute_standard_vector(num_orders=100)
    res2 = GoldenVectorHarness.execute_standard_vector(num_orders=100)
    assert res1["sha256_digest"] == res2["sha256_digest"]
    assert len(res1["sha256_digest"]) == 64


def test_benchmark_html_generator():
    dummy_results = {
        "system_metadata": {"platform": "TestOS", "python_version": "3.14"},
        "workload_metadata": {"total_operations": 500, "seed": 42},
        "execution_metrics": {
            "orders_per_second": 50000,
            "total_trades_generated": 100,
        },
        "latencies_ns": {
            "p50_ns": 12000,
            "p90_ns": 20000,
            "p99_ns": 35000,
            "p99_9_ns": 60000,
        },
    }
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
        path = tf.name
    BenchmarkReportGenerator.generate_html_report(dummy_results, path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "ZERENE ⚡ Benchmark Report" in content
    assert "50,000" in content

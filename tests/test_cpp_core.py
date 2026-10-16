"""
Unit tests for the ultra-fast C++ Matching Engine Core and Accelerator.
Verifies pybind11 bindings, crossing engine, order lifecycle, and high-throughput benchmarks.
"""

from zerene.engine.c_accelerator import NativeMatchingAccelerator
from zerene.benchmarks.cpp_runner import CppBenchmarkRunner


def test_native_accelerator_availability():
    """Verify that native C++ core extension is successfully imported."""
    assert NativeMatchingAccelerator.is_available() is True
    mod = NativeMatchingAccelerator.get_core()
    assert mod is not None
    assert hasattr(mod, "MatchingEngineCore")
    assert hasattr(mod, "Side")
    assert hasattr(mod, "OrderType")
    assert hasattr(mod, "run_cpp_benchmark")


def test_cpp_matching_core_order_lifecycle():
    """Verify limit order placement, crossing, modification, and cancellation in C++ core."""
    mod = NativeMatchingAccelerator.get_core()
    engine = mod.MatchingEngineCore("BTC-USD", 50_000_0000)  # anchor at $50,000

    # 1. Place resting limit buy orders: $49,990 (499900000 ticks) and $49,980
    engine.process_order_fast(
        101, mod.Side.BUY, mod.OrderType.LIMIT, 499900000, 2.5, 1.0
    )
    engine.process_order_fast(
        102, mod.Side.BUY, mod.OrderType.LIMIT, 499800000, 1.0, 1.1
    )

    assert engine.best_bid_ticks() == 499900000

    # 2. Place resting limit sell order: $50,010 (500100000 ticks)
    engine.process_order_fast(
        201, mod.Side.SELL, mod.OrderType.LIMIT, 500100000, 3.0, 1.2
    )
    assert engine.best_ask_ticks() == 500100000

    # 3. Market order crossing: aggressive buy sweeps resting sell
    trades_gen = engine.process_order_fast(
        301, mod.Side.BUY, mod.OrderType.MARKET, 0, 1.5, 2.0
    )
    assert trades_gen == 1
    assert engine.trade_count() == 1

    # Resting sell order #201 had 3.0, matched 1.5 -> 1.5 remaining at 500100000
    assert engine.best_ask_ticks() == 500100000

    # 4. Modify resting buy order price: change #101 to $49,995 (499950000 ticks)
    ok_mod = engine.modify_order_fast(101, 2.5, 499950000)
    assert ok_mod is True
    assert engine.best_bid_ticks() == 499950000

    # 5. Cancel resting order
    ok_cancel = engine.cancel_order_fast(101)
    assert ok_cancel is True
    assert engine.best_bid_ticks() == 499800000


def test_cpp_benchmark_runner_execution():
    """Verify CppBenchmarkRunner runs deterministically and achieves multi-million ops/sec."""
    runner = CppBenchmarkRunner(symbol="BENCH-USD", seed=42)
    results = runner.run(num_orders=100_000, verbose=False, seed=42)

    assert results["workload_metadata"]["total_operations"] == 100_000
    assert (
        results["execution_metrics"]["orders_per_second"] > 1_000_000
    )  # > 1M ops/sec even on small batch
    assert results["execution_metrics"]["total_trades_generated"] > 0
    assert "latencies_ns" in results
    assert "p50_ns" in results["latencies_ns"]

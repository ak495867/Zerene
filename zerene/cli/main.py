"""
ZERENE Command Line Interface.
Provides entry points for simulation (`zerene sim`), benchmarking (`zerene benchmark`), and inspection (`zerene inspect`).
"""

import sys
import argparse
from typing import List, Optional
from zerene.examples.run_simulation import run_basic_simulation
from zerene.benchmarks.runner import BenchmarkRunner
from zerene.exchange.venue import ExchangeVenue


def main(args: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zerene",
        description="ZERENE: Institutional-Grade Market Microstructure Research Platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: sim
    sim_parser = subparsers.add_parser("sim", help="Run synthetic market simulation")
    sim_parser.add_argument("--symbols", type=str, default="BTC-USD,ETH-USD", help="Comma-separated list of symbols")
    sim_parser.add_argument("--steps", type=int, default=1000, help="Number of simulation steps to run")

    # Command: benchmark
    bench_parser = subparsers.add_parser("benchmark", help="Run high-throughput matching engine benchmark")
    bench_parser.add_argument("--orders", type=int, default=50000, help="Number of operations to process")
    bench_parser.add_argument("--symbol", type=str, default="BENCH-USD", help="Target symbol")
    bench_parser.add_argument("--workload", type=str, default="realistic", choices=["realistic", "insert_only"], help="Workload regime: realistic (mix of inserts, cancels, modifies, crossings) or insert_only")
    bench_parser.add_argument("--shards", type=int, default=1, help="Number of parallel matching engines to spawn (sharded architecture)")

    # Command: inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect live or seeded limit order book structure")
    inspect_parser.add_argument("--symbol", type=str, default="BTC-USD", help="Symbol to inspect")

    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return 0

    if parsed.command == "sim":
        symbols = [s.strip() for s in parsed.symbols.split(",") if s.strip()]
        print(f"\n[+] Launching ZERENE Market Simulation for {symbols} over {parsed.steps} steps...\n")
        summary = run_basic_simulation(steps=parsed.steps, symbols=symbols)
        print(summary)

    elif parsed.command == "benchmark":
        if getattr(parsed, 'shards', 1) > 1:
            print(f"\n[+] Running ZERENE Sharded Institutional Benchmark across {parsed.orders:,} operations ({parsed.shards} shards, {parsed.workload} workload)...\n")
            from zerene.benchmarks.sharded_runner import ShardedBenchmarkRunner
            runner = ShardedBenchmarkRunner(base_symbol=parsed.symbol, num_shards=parsed.shards)
            results = runner.run(total_orders=parsed.orders, workload=parsed.workload)
        else:
            print(f"\n[+] Running ZERENE Institutional Benchmark across {parsed.orders:,} operations ({parsed.workload} workload on {parsed.symbol})...\n")
            runner = BenchmarkRunner(parsed.symbol)
            results = runner.run(num_orders=parsed.orders, workload=parsed.workload, verbose=True)
        
        sys_m = results["system_metadata"]
        w_m = results["workload_metadata"]
        exec_m = results["execution_metrics"]
        l_ns = results["latencies_ns"]

        print("\n======================================================================")
        print("                 ZERENE INSTITUTIONAL BENCHMARK REPORT                ")
        print("======================================================================")
        print("[System Environment]")
        print(f"  Platform                 : {sys_m['platform']}")
        print(f"  Python Version           : {sys_m['python_version']}")
        print(f"  CPU Processor            : {sys_m['cpu_processor']}")
        print(f"  Execution Mode           : {sys_m['execution_mode']}")
        print(f"  Garbage Collector        : {'Enabled' if sys_m['gc_enabled'] else 'Disabled'}")
        print("\n[Workload Configuration]")
        print(f"  Target Symbol            : {w_m['symbol']}")
        print(f"  Workload Mode            : {w_m['workload_mode'].upper()}")
        print(f"  Total Operations         : {w_m['total_operations']:,}")
        if getattr(parsed, 'shards', 1) > 1:
            print(f"  Active Shards            : {w_m['shards']}")
        print(f"  Operation Mix            : Limit: {w_m['limit_inserts_pct']}% | Market: {w_m['market_inserts_pct']}% | Cancel: {w_m['cancels_pct']}% | Modify: {w_m['modifies_pct']}%")
        print(f"  Latency Sample Size      : {w_m['latency_sample_size']:,} (reservoir sampled)")
        print("\n[Throughput & Execution Metrics]")
        print(f"  Elapsed Time             : {exec_m['elapsed_seconds']} s")
        print(f"  Operations / Second (orders_per_second): {exec_m['orders_per_second']:,.2f} ops/sec")
        print(f"  Total Trades Generated   : {exec_m['total_trades_generated']:,}")
        print(f"  Average Matches / Order  : {exec_m['avg_matches_per_order']}")
        print(f"  Successful Cancels       : {exec_m['successful_cancels']:,}")
        print(f"  Successful Modifies      : {exec_m['successful_modifies']:,}")
        print(f"  Final Orderbook Depth    : {exec_m['final_orderbook_depth_levels']} active price levels")
        print("\n[Latency Percentiles]")
        print(f"  P50 Median Latency       : {l_ns['p50_ns']:>8.1f} ns ({l_ns['p50_ns']/1000:>6.2f} µs)")
        print(f"  P90 Latency              : {l_ns['p90_ns']:>8.1f} ns ({l_ns['p90_ns']/1000:>6.2f} µs)")
        print(f"  P99 Latency              : {l_ns['p99_ns']:>8.1f} ns ({l_ns['p99_ns']/1000:>6.2f} µs)")
        print(f"  P99.9 Latency            : {l_ns['p99_9_ns']:>8.1f} ns ({l_ns['p99_9_ns']/1000:>6.2f} µs)")
        print(f"  Max Worst-Case Latency   : {l_ns['max_ns']:>8.1f} ns ({l_ns['max_ns']/1000:>6.2f} µs)")
        print("======================================================================")

    elif parsed.command == "inspect":
        exchange = ExchangeVenue("ZERENE-INSPECT", symbols=[parsed.symbol])
        from zerene.models import Order, Side, OrderType
        from zerene.pools import GLOBAL_ORDER_POOL
        # Seed book
        engine = exchange.engines[parsed.symbol]
        for i in range(1, 6):
            engine.process_order(GLOBAL_ORDER_POOL.acquire(
                order_id=f"B-{i}", client_order_id=f"CB-{i}", symbol=parsed.symbol, side=Side.BUY,
                order_type=OrderType.LIMIT, price=round(100.0 - i * 0.1, 2), quantity=10.0, owner_id="LP"
            ))
            engine.process_order(GLOBAL_ORDER_POOL.acquire(
                order_id=f"A-{i}", client_order_id=f"CA-{i}", symbol=parsed.symbol, side=Side.SELL,
                order_type=OrderType.LIMIT, price=round(100.0 + i * 0.1, 2), quantity=10.0, owner_id="LP"
            ))
        snap = exchange.get_order_book_snapshot(parsed.symbol, 0.0, levels=10)
        print("==================================================")
        print(f"     LIMIT ORDER BOOK INSPECTION: {parsed.symbol}")
        print("==================================================")
        print(f"Mid Price: {snap.mid_price} | Spread: {snap.spread} | Imbalance: {snap.imbalance:.2f}")
        print("\n--- ASKS (Lowest to Highest) ---")
        for p, v in reversed(snap.asks):
            print(f"  ${p:>8.2f}  |  {v:>8.2f} qty")
        print("--------------------------------")
        for p, v in snap.bids:
            print(f"  ${p:>8.2f}  |  {v:>8.2f} qty")
        print("--- BIDS (Highest to Lowest) ---")
        print("==================================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())

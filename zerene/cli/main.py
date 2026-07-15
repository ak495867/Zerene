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
    bench_parser.add_argument("--orders", type=int, default=50000, help="Number of orders to process")
    bench_parser.add_argument("--symbol", type=str, default="BENCH-USD", help="Target symbol")

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
        print(f"\n[+] Running ZERENE Matching Engine Benchmark across {parsed.orders:,} orders on {parsed.symbol}...\n")
        runner = BenchmarkRunner(parsed.symbol)
        results = runner.run(num_orders=parsed.orders)
        print("==================================================")
        print("        ZERENE BENCHMARK RESULTS                  ")
        print("==================================================")
        for k, v in results.items():
            print(f"  {k:<25}: {v}")
        print("==================================================")

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

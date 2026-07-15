"""
High-throughput benchmark engine measuring matching speed, latency percentiles, and system/workload characteristics.

Architecture: Fully streaming execution — no pre-generation phase.
Orders are generated and executed inline to avoid O(N) memory for instruction lists.
Latency samples use reservoir sampling (capped at 1M samples) for bounded memory at any scale.
"""

import time
import random
import platform
import sys
import gc
from typing import Dict, Any, List
from zerene.models import Order, Side, OrderType
from zerene.engine.matching_engine import MatchingEngine
from zerene.pools import GLOBAL_ORDER_POOL

# Maximum latency samples to collect (reservoir sampling beyond this)
_MAX_LATENCY_SAMPLES = 1_000_000
# Maximum tracked resting IDs for cancel/modify targeting
_MAX_RESTING_TRACKER = 50_000
# First progress report (early feedback so it doesn't look stuck)
_FIRST_PROGRESS = 50_000
# Subsequent progress report interval
_PROGRESS_INTERVAL = 250_000


class BenchmarkRunner:
    """
    Executes institutional throughput and latency performance benchmarks
    on ZERENE's deterministic matching engine.
    Supports realistic exchange workloads including insertions, partial fills, cancellations, and modifications.

    Streaming architecture: generates and executes each operation inline (no pre-allocation of
    instruction lists), so memory usage stays bounded regardless of total operation count.
    """
    def __init__(self, symbol: str = "BENCH-USD"):
        self.symbol = symbol

    def run(self, num_orders: int = 100_000, workload: str = "realistic", verbose: bool = True) -> Dict[str, Any]:
        engine = MatchingEngine(self.symbol)

        # Pre-seed resting order book across 250 price levels on each side
        for idx in range(1, 251):
            engine.process_order(GLOBAL_ORDER_POOL.acquire(
                order_id=f"PRE-B-{idx}",
                client_order_id="CPRE",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=round(100.0 - (idx * 0.05), 2),
                quantity=1000.0,
                timestamp=0.0,
                owner_id="BENCH_LP",
            ))
            engine.process_order(GLOBAL_ORDER_POOL.acquire(
                order_id=f"PRE-A-{idx}",
                client_order_id="CPRE",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=round(100.0 + (idx * 0.05), 2),
                quantity=1000.0,
                timestamp=0.0,
                owner_id="BENCH_LP",
            ))

        # Capped circular buffer for cancel/modify target tracking
        active_resting_ids: List[str] = [f"PRE-B-{idx}" for idx in range(1, 251)] + [f"PRE-A-{idx}" for idx in range(1, 251)]

        # Counters
        limit_count = 0
        market_count = 0
        cancel_count = 0
        modify_count = 0
        actual_cancels = 0
        actual_modifies = 0

        # Reservoir-sampled latency collection (bounded memory)
        latency_samples: List[float] = []
        max_latency_ns: float = 0.0

        # Streaming execution: generate + execute each operation inline
        if verbose and num_orders >= _FIRST_PROGRESS:
            print(f"  [bench] Streaming {num_orders:,} operations (generate + execute inline)...")

        start_t = time.perf_counter()

        for i in range(num_orders):
            side = Side.BUY if i % 2 == 0 else Side.SELL

            # Determine operation type
            if workload == "realistic":
                r = random.random()
                if r < 0.45:
                    op_type = 0  # LIMIT
                elif r < 0.70:
                    op_type = 1  # MARKET
                elif r < 0.90:
                    op_type = 2  # CANCEL
                else:
                    op_type = 3  # MODIFY
            else:
                op_type = 1 if (i % 5 == 0) else 0

            # Generate and execute inline
            t0 = time.perf_counter_ns()

            if op_type == 1:
                market_count += 1
                o = GLOBAL_ORDER_POOL.acquire(
                    order_id=f"TEST-M-{i}",
                    client_order_id="C-BENCH",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    price=0.0,
                    quantity=round(random.uniform(1.0, 25.0), 2),
                    timestamp=float(i),
                    owner_id="BENCH_TAKER",
                )
                engine.process_order(o)
            elif op_type == 2 and active_resting_ids:
                cancel_count += 1
                target_id = random.choice(active_resting_ids)
                if engine.cancel_order(target_id):
                    actual_cancels += 1
            elif op_type == 3 and active_resting_ids:
                modify_count += 1
                target_id = random.choice(active_resting_ids)
                new_qty = round(random.uniform(10.0, 500.0), 2)
                new_price = round(100.0 + random.uniform(-1.0, 1.0), 2)
                if engine.modify_order(target_id, new_qty, new_price):
                    actual_modifies += 1
            else:
                limit_count += 1
                price_offset = random.uniform(-0.5, 0.5) if workload == "realistic" else random.uniform(-2.0, 2.0)
                price = round(100.0 + price_offset, 2)
                o = GLOBAL_ORDER_POOL.acquire(
                    order_id=f"TEST-L-{i}",
                    client_order_id="C-BENCH",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    quantity=round(random.uniform(5.0, 50.0), 2),
                    timestamp=float(i),
                    owner_id="BENCH_TAKER",
                )
                engine.process_order(o)
                # Cap the resting tracker to avoid unbounded list growth
                if len(active_resting_ids) < _MAX_RESTING_TRACKER:
                    active_resting_ids.append(o.order_id)
                else:
                    # Replace a random existing entry (reservoir-style)
                    active_resting_ids[random.randint(0, _MAX_RESTING_TRACKER - 1)] = o.order_id

            t1 = time.perf_counter_ns()
            lat = float(t1 - t0)

            # Track max
            if lat > max_latency_ns:
                max_latency_ns = lat

            # Reservoir sampling for latency percentiles (bounded at _MAX_LATENCY_SAMPLES)
            sample_count = len(latency_samples)
            if sample_count < _MAX_LATENCY_SAMPLES:
                latency_samples.append(lat)
            else:
                # Reservoir replacement with decreasing probability
                j = random.randint(0, i)
                if j < _MAX_LATENCY_SAMPLES:
                    latency_samples[j] = lat

            # Progress reporting (early first report, then periodic)
            ops_done = i + 1
            if verbose and ops_done >= _FIRST_PROGRESS:
                if ops_done == _FIRST_PROGRESS or ops_done % _PROGRESS_INTERVAL == 0:
                    elapsed_so_far = time.perf_counter() - start_t
                    rate = ops_done / max(1e-9, elapsed_so_far)
                    pct = (ops_done / num_orders) * 100
                    print(f"  [bench] {ops_done:>13,} / {num_orders:,} ops ({pct:5.1f}%) | {rate:,.0f} ops/sec | trades: {engine._trade_counter:,}")

        end_t = time.perf_counter()
        elapsed = max(1e-9, end_t - start_t)
        total_ops = limit_count + market_count + cancel_count + modify_count
        ops_per_sec = total_ops / elapsed

        # Compute percentiles from reservoir sample
        latency_samples.sort()
        n = len(latency_samples)
        p50 = latency_samples[int(n * 0.50)] if n else 0.0
        p90 = latency_samples[int(n * 0.90)] if n else 0.0
        p99 = latency_samples[int(n * 0.99)] if n else 0.0
        p999 = latency_samples[int(n * 0.999)] if n else 0.0

        trades_gen = engine._trade_counter
        avg_matches = round(trades_gen / max(1, (limit_count + market_count)), 2)
        total_depth = len(engine.order_book.bids) + len(engine.order_book.asks)

        return {
            "system_metadata": {
                "platform": platform.platform(),
                "python_version": sys.version.split(" ")[0],
                "cpu_processor": platform.processor() or "Unknown Architecture",
                "execution_mode": "Single-Threaded CPython",
                "gc_enabled": gc.isenabled(),
            },
            "workload_metadata": {
                "symbol": self.symbol,
                "workload_mode": workload,
                "total_operations": total_ops,
                "limit_inserts_pct": round((limit_count / max(1, total_ops)) * 100, 1),
                "market_inserts_pct": round((market_count / max(1, total_ops)) * 100, 1),
                "cancels_pct": round((cancel_count / max(1, total_ops)) * 100, 1),
                "modifies_pct": round((modify_count / max(1, total_ops)) * 100, 1),
                "latency_sample_size": n,
            },
            "execution_metrics": {
                "elapsed_seconds": round(elapsed, 4),
                "orders_per_second": round(ops_per_sec, 2),
                "total_trades_generated": trades_gen,
                "avg_matches_per_order": avg_matches,
                "successful_cancels": actual_cancels,
                "successful_modifies": actual_modifies,
                "final_orderbook_depth_levels": total_depth,
            },
            "latencies_ns": {
                "p50_ns": round(p50, 1),
                "p90_ns": round(p90, 1),
                "p99_ns": round(p99, 1),
                "p99_9_ns": round(p999, 1),
                "max_ns": round(max_latency_ns, 1),
            },
        }

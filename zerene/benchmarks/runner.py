"""
High-throughput benchmark engine measuring matching speed and latency percentiles.
"""

import time
import random
import uuid
from typing import Dict, Any, List
from zerene.models import Order, Side, OrderType
from zerene.engine.matching_engine import MatchingEngine
from zerene.pools import GLOBAL_ORDER_POOL


class BenchmarkRunner:
    """
    Executes institutional throughput and latency performance benchmarks
    on ZERENE's deterministic matching engine.
    """
    def __init__(self, symbol: str = "BENCH-USD"):
        self.symbol = symbol

    def run(self, num_orders: int = 100_000) -> Dict[str, Any]:
        engine = MatchingEngine(self.symbol)

        # Pre-seed resting order book across 500 price levels
        for idx in range(1, 251):
            engine.process_order(GLOBAL_ORDER_POOL.acquire(
                order_id=f"PRE-B-{idx}",
                client_order_id="CPRE",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=100.0 - (idx * 0.05),
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
                price=100.0 + (idx * 0.05),
                quantity=1000.0,
                timestamp=0.0,
                owner_id="BENCH_LP",
            ))

        # Generate orders in memory to measure pure matching engine speed
        test_orders: List[Order] = []
        for i in range(num_orders):
            side = Side.BUY if i % 2 == 0 else Side.SELL
            is_market = (i % 5 == 0)
            if is_market:
                test_orders.append(GLOBAL_ORDER_POOL.acquire(
                    order_id=f"TEST-{i}",
                    client_order_id="C-BENCH",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    price=0.0,
                    quantity=random.uniform(0.1, 5.0),
                    timestamp=float(i),
                    owner_id="BENCH_TAKER",
                ))
            else:
                price = round(100.0 + random.uniform(-2.0, 2.0), 2)
                test_orders.append(GLOBAL_ORDER_POOL.acquire(
                    order_id=f"TEST-{i}",
                    client_order_id="C-BENCH",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    quantity=random.uniform(0.5, 10.0),
                    timestamp=float(i),
                    owner_id="BENCH_TAKER",
                ))

        # Execute matching benchmark
        start_t = time.perf_counter()
        latencies_ns: List[float] = []

        for o in test_orders:
            t0 = time.perf_counter_ns()
            engine.process_order(o)
            t1 = time.perf_counter_ns()
            latencies_ns.append(float(t1 - t0))

        end_t = time.perf_counter()
        elapsed = max(1e-9, end_t - start_t)
        ops_per_sec = num_orders / elapsed

        latencies_ns.sort()
        p50 = latencies_ns[int(num_orders * 0.50)]
        p90 = latencies_ns[int(num_orders * 0.90)]
        p99 = latencies_ns[int(num_orders * 0.99)]
        p999 = latencies_ns[int(num_orders * 0.999)]

        return {
            "symbol": self.symbol,
            "total_orders": num_orders,
            "elapsed_seconds": round(elapsed, 4),
            "orders_per_second": round(ops_per_sec, 2),
            "latency_ns_p50": round(p50, 1),
            "latency_ns_p90": round(p90, 1),
            "latency_ns_p99": round(p99, 1),
            "latency_ns_p99_9": round(p999, 1),
            "total_trades_generated": len(engine.trade_history),
        }

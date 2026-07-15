"""
Multiprocessing sharded benchmark to demonstrate linear scaling across multiple isolated symbols.
"""

import time
import multiprocessing as mp
from typing import Dict, Any, List
from zerene.benchmarks.runner import BenchmarkRunner

def _run_shard(shard_id: int, symbol: str, num_orders: int, workload: str) -> Dict[str, Any]:
    """
    Worker function to run a completely isolated matching engine in its own process.
    """
    runner = BenchmarkRunner(symbol)
    result = runner.run(num_orders=num_orders, workload=workload, verbose=False)
    print(f"  [shard-{shard_id}] Finished {num_orders:,} operations on {symbol}!")
    return result

class ShardedBenchmarkRunner:
    def __init__(self, base_symbol: str = "SHARD-USD", num_shards: int = 4):
        self.base_symbol = base_symbol
        self.num_shards = num_shards

    def run(self, total_orders: int = 100_000, workload: str = "realistic") -> Dict[str, Any]:
        orders_per_shard = total_orders // self.num_shards
        
        symbols = [f"{self.base_symbol}-{i}" for i in range(self.num_shards)]
        
        print(f"  [sharded] Booting {self.num_shards} independent processes (1 core per matching engine)...")
        start_t = time.perf_counter()
        
        with mp.Pool(processes=self.num_shards) as pool:
            results = []
            for i, symbol in enumerate(symbols):
                res = pool.apply_async(_run_shard, (i, symbol, orders_per_shard, workload))
                results.append(res)
            
            # Wait for all processes to finish and collect results
            completed_results = [res.get() for res in results]
            
        end_t = time.perf_counter()
        elapsed = max(1e-9, end_t - start_t)
        
        # Aggregate results
        total_ops = sum(r["workload_metadata"]["total_operations"] for r in completed_results)
        total_trades = sum(r["execution_metrics"]["total_trades_generated"] for r in completed_results)
        total_cancels = sum(r["execution_metrics"]["successful_cancels"] for r in completed_results)
        total_modifies = sum(r["execution_metrics"]["successful_modifies"] for r in completed_results)
        
        aggregate_ops_per_sec = total_ops / elapsed
        
        # Just grab metadata from the first shard
        sys_m = completed_results[0]["system_metadata"]
        sys_m["execution_mode"] = f"Multi-Process Sharded ({self.num_shards} cores)"
        
        # Combine latency percentiles (approximate by averaging them, or taking worst case)
        avg_p50 = sum(r["latencies_ns"]["p50_ns"] for r in completed_results) / self.num_shards
        avg_p90 = sum(r["latencies_ns"]["p90_ns"] for r in completed_results) / self.num_shards
        avg_p99 = sum(r["latencies_ns"]["p99_ns"] for r in completed_results) / self.num_shards
        avg_p99_9 = sum(r["latencies_ns"]["p99_9_ns"] for r in completed_results) / self.num_shards
        worst_max = max(r["latencies_ns"]["max_ns"] for r in completed_results)
        
        return {
            "system_metadata": sys_m,
            "workload_metadata": {
                "symbol": f"{self.base_symbol}-Multi",
                "workload_mode": workload,
                "total_operations": total_ops,
                "shards": self.num_shards,
                "limit_inserts_pct": completed_results[0]["workload_metadata"]["limit_inserts_pct"],
                "market_inserts_pct": completed_results[0]["workload_metadata"]["market_inserts_pct"],
                "cancels_pct": completed_results[0]["workload_metadata"]["cancels_pct"],
                "modifies_pct": completed_results[0]["workload_metadata"]["modifies_pct"],
                "latency_sample_size": sum(r["workload_metadata"]["latency_sample_size"] for r in completed_results)
            },
            "execution_metrics": {
                "elapsed_seconds": round(elapsed, 4),
                "orders_per_second": round(aggregate_ops_per_sec, 2),
                "total_trades_generated": total_trades,
                "avg_matches_per_order": round(total_trades / max(1, (total_ops * 0.7)), 2), # Approx
                "successful_cancels": total_cancels,
                "successful_modifies": total_modifies,
                "final_orderbook_depth_levels": sum(r["execution_metrics"]["final_orderbook_depth_levels"] for r in completed_results)
            },
            "latencies_ns": {
                "p50_ns": round(avg_p50, 1),
                "p90_ns": round(avg_p90, 1),
                "p99_ns": round(avg_p99, 1),
                "p99_9_ns": round(avg_p99_9, 1),
                "max_ns": round(worst_max, 1),
            },
        }

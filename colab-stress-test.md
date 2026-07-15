# Testing Zerene on COLAB VMs to compare throughput (idk why i did ts) 

## Objective: Compare ZERENE's throughput and latency on a shared cloud VM against local commodity hardware using an identical deterministic benchmark.

> [!TIP]
> Benchmark Reproducibility: All benchmark scripts are deterministic and publicly available. If you run ZERENE on your own hardware, feel free to open a PR or issue with your results.

```text
[+] Running ZERENE Sharded Institutional Benchmark across 5,000,000 operations (4 shards, realistic workload)...

  [sharded] Booting 4 independent processes (1 core per matching engine)...
  [shard-0] Finished 1,250,000 operations on BENCH-USD-0!
  [shard-3] Finished 1,250,000 operations on BENCH-USD-3!
  [shard-2] Finished 1,250,000 operations on BENCH-USD-2!
  [shard-1] Finished 1,250,000 operations on BENCH-USD-1!

======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT                
======================================================================
[System Environment]
  Platform                 : Linux-6.6.122+-x86_64-with-glibc2.35
  Python Version           : 3.12.13
  CPU Processor            : x86_64
  Execution Mode           : Multi-Process Sharded (4 cores)
  Garbage Collector        : Enabled

[Workload Configuration]
  Target Symbol            : BENCH-USD-Multi
  Workload Mode            : REALISTIC
  Total Operations         : 5,000,000
  Active Shards            : 4
  Operation Mix            : Limit: 45.0% | Market: 25.0% | Cancel: 20.0% | Modify: 10.0%
  Latency Sample Size      : 4,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 105.3022 s
  Operations / Second (orders_per_second): 47,482.37 ops/sec
  Total Trades Generated   : 3,363,633
  Average Matches / Order  : 0.96
  Successful Cancels       : 47,390
  Successful Modifies      : 500,060
  Final Orderbook Depth    : 571 active price levels

[Latency Percentiles]
  P50 Median Latency       :  24720.8 ns ( 24.72 µs)
  P90 Latency              :  51608.8 ns ( 51.61 µs)
  P99 Latency              : 2054940.2 ns (2054.94 µs)
  P99.9 Latency            : 6096207.5 ns (6096.21 µs)
  Max Worst-Case Latency   : 2206604707.0 ns (2206604.71 µs)
======================================================================
```
---
## What Changed Compared to Local Hardware?

For comparison, the exact same benchmark on my local Ryzen 7 7435HS laptop sustained 109,208 ops/sec, while the Colab VM sustained 47,482 ops/sec.

Platform	Throughput	P50	P99
Ryzen 7 7435HS (Windows, CPython 3.14.5)	109,208 ops/sec	21.98 µs	115.30 µs
Google Colab VM (Linux, CPython 3.12.13)	47,482 ops/sec	24.72 µs	2054.94 µs

The VM delivers roughly 43% of the throughput achieved on my local machine.

---

## 🤔 Why is the VM Slower?

This isn't necessarily a reflection of ZERENE itself.
Free Colab instances are optimized for accessibility rather than deterministic CPU performance. They typically run on shared virtualized hardware where multiple users compete for compute resources. That introduces factors such as:

### Shared CPU scheduling
### Lower sustained clock frequencies
### Virtualization overhead
### Background hypervisor activity
### Noisy-neighbor effects

Matching engines are almost entirely CPU-bound, so these factors have a much larger impact than they would for GPU-heavy machine learning workloads.

---

## Throughput vs Latency

Despite the lower throughput, the benchmark characteristics remained remarkably similar.

Average matches per operation: 0.96
Operation mix: unchanged
Final orderbook depth: comparable

This suggests the workload itself remained consistent across both environments.
The primary difference is tail latency.

Laptop P99      :   115 µs
Colab VM P99    : 2,055 µs

The large increase in P99 and P99.9 latency is consistent with runtime scheduling interruptions and virtualization overhead rather than changes in the matching algorithm itself.

---

Relative Performance
Metric	Difference
Throughput	2.30× faster locally
P50 Latency	11% lower locally
P99 Latency	~18× lower locally

---

# Reproducing This Benchmark
python -m zerene benchmark --orders 5000000 --workload realistic --shards 4

If you benchmark ZERENE on different hardware (desktop CPUs, EPYC, Xeon, Apple Silicon, cloud VMs, etc.), feel free to share your results. Cross-platform comparisons help characterize how the engine performs across a wide range of execution environments.
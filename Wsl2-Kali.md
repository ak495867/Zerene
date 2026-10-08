# Stress testing ZERENE, (On Kali Linux Wsl2): Ten Shards, Zero Mercy 🔥

Part 1 ran four shards on Windows and crossed 100k ops/sec. The obvious next question: what happens when you stop being polite and give every core a matching engine?

This round runs on **Kali Linux under WSL2** (Part 1 was native Windows 11) with **10 independent processes**, one matching engine per core, on three workload sizes: 1M, 5M and 10M operations. Same `realistic` workload as before, so the only things that changed are the shard count, the OS layer and the Python patch version.

A note on honesty before the numbers: the shards trade separate symbols (`BENCH-USD-0` to `BENCH-USD-9`) and never interact. The headline figure is **aggregate throughput across 10 independent engines**, not the speed of one engine. Divide by 10 for the per-engine picture. We show both.

---

## Test at 1,000,000 orders (The "Warmup Stretch")
*One million operations, 100,000 per shard. A quarter of the earlier wall-clock time.*

```text
[+] Running ZERENE Sharded Institutional Benchmark across 1,000,000 operations (10 shards, realistic workload)...

  [sharded] Booting 10 independent processes (1 core per matching engine)...
  [shard-0] Finished 100,000 operations on BENCH-USD-0!
  [shard-2] Finished 100,000 operations on BENCH-USD-2!
  [shard-3] Finished 100,000 operations on BENCH-USD-3!
  [shard-9] Finished 100,000 operations on BENCH-USD-9!
  [shard-4] Finished 100,000 operations on BENCH-USD-4!
  [shard-7] Finished 100,000 operations on BENCH-USD-7!
  [shard-1] Finished 100,000 operations on BENCH-USD-1!
  [shard-8] Finished 100,000 operations on BENCH-USD-8!
  [shard-5] Finished 100,000 operations on BENCH-USD-5!
  [shard-6] Finished 100,000 operations on BENCH-USD-6!

======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT
======================================================================
[System Environment]
  Platform                 : Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.42
  Python Version           : 3.14.7
  CPU Processor            : Unknown Architecture
  Execution Mode           : Multi-Process Sharded (10 cores)
  Garbage Collector        : Enabled

[Workload Configuration]
  Target Symbol            : BENCH-USD-Multi
  Workload Mode            : REALISTIC
  Total Operations         : 1,000,000
  Active Shards            : 10
  Operation Mix            : Limit: 45.2% | Market: 24.9% | Cancel: 20.1% | Modify: 9.8%
  Latency Sample Size      : 1,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 2.8483 s
  Operations / Second (orders_per_second): 351,090.44 ops/sec
  Total Trades Generated   : 672,155
  Average Matches / Order  : 0.96
  Successful Cancels       : 12,941
  Successful Modifies      : 99,993
  Final Orderbook Depth    : 1003 active price levels

[Latency Percentiles]
  P50 Median Latency       :  14539.6 ns ( 14.54 µs)
  P90 Latency              :  36664.7 ns ( 36.66 µs)
  P99 Latency              :  76659.9 ns ( 76.66 µs)
  P99.9 Latency            : 208561.7 ns (208.56 µs)
  Max Worst-Case Latency   : 18335776.0 ns (18335.78 µs)
======================================================================
```

**The Verdict:** `351,090 ops/sec` aggregate, roughly `35k ops/sec` per engine. One million operations done in under three seconds, with a median of `14.54 µs` and a P99.9 of only `208.56 µs`. The worst case was `18.3 ms`, a blip.

---

## Test at 5,000,000 orders (The "Liquidate The Intern" Run, Again)
*Five million operations, 500,000 per shard, 3.36 million trades.*

```text
[+] Running ZERENE Sharded Institutional Benchmark across 5,000,000 operations (10 shards, realistic workload)...

  [sharded] Booting 10 independent processes (1 core per matching engine)...
  [shard-2] Finished 500,000 operations on BENCH-USD-2!
  [shard-8] Finished 500,000 operations on BENCH-USD-8!
  [shard-5] Finished 500,000 operations on BENCH-USD-5!
  [shard-0] Finished 500,000 operations on BENCH-USD-0!
  [shard-1] Finished 500,000 operations on BENCH-USD-1!
  [shard-4] Finished 500,000 operations on BENCH-USD-4!
  [shard-9] Finished 500,000 operations on BENCH-USD-9!
  [shard-3] Finished 500,000 operations on BENCH-USD-3!
  [shard-7] Finished 500,000 operations on BENCH-USD-7!
  [shard-6] Finished 500,000 operations on BENCH-USD-6!

======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT
======================================================================
[System Environment]
  Platform                 : Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.42
  Python Version           : 3.14.7
  CPU Processor            : Unknown Architecture
  Execution Mode           : Multi-Process Sharded (10 cores)
  Garbage Collector        : Enabled

[Workload Configuration]
  Target Symbol            : BENCH-USD-Multi
  Workload Mode            : REALISTIC
  Total Operations         : 5,000,000
  Active Shards            : 10
  Operation Mix            : Limit: 44.9% | Market: 25.0% | Cancel: 20.0% | Modify: 10.0%
  Latency Sample Size      : 5,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 13.2285 s
  Operations / Second (orders_per_second): 377,973.21 ops/sec
  Total Trades Generated   : 3,364,368
  Average Matches / Order  : 0.96
  Successful Cancels       : 48,545
  Successful Modifies      : 498,371
  Final Orderbook Depth    : 1372 active price levels

[Latency Percentiles]
  P50 Median Latency       :  16095.5 ns ( 16.10 µs)
  P90 Latency              :  38072.6 ns ( 38.07 µs)
  P99 Latency              :  86079.8 ns ( 86.08 µs)
  P99.9 Latency            : 1145575.1 ns (1145.58 µs)
  Max Worst-Case Latency   : 377321592.0 ns (377321.59 µs)
======================================================================
```

**The Verdict:** `377,973 ops/sec`, the best run of the three, at about `37.8k ops/sec` per engine. The median held at `16.10 µs` and the P99 at `86.08 µs`. This is also where the tail starts to show: P99.9 jumps to `1.15 ms` and the worst case to `377 ms`.

---

## Test at 10,000,000 orders (The "Ten Million Reasons To Buy A Server" Run)
*Ten million operations, one million per shard, 6.7 million trades. Roughly 28 seconds of sustained load on every core at once.*

```text
[+] Running ZERENE Sharded Institutional Benchmark across 10,000,000 operations (10 shards, realistic workload)...

  [sharded] Booting 10 independent processes (1 core per matching engine)...
  [shard-7] Finished 1,000,000 operations on BENCH-USD-7!
  [shard-2] Finished 1,000,000 operations on BENCH-USD-2!
  [shard-1] Finished 1,000,000 operations on BENCH-USD-1!
  [shard-5] Finished 1,000,000 operations on BENCH-USD-5!
  [shard-3] Finished 1,000,000 operations on BENCH-USD-3!
  [shard-6] Finished 1,000,000 operations on BENCH-USD-6!
  [shard-4] Finished 1,000,000 operations on BENCH-USD-4!
  [shard-0] Finished 1,000,000 operations on BENCH-USD-0!
  [shard-8] Finished 1,000,000 operations on BENCH-USD-8!
  [shard-9] Finished 1,000,000 operations on BENCH-USD-9!

======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT
======================================================================
[System Environment]
  Platform                 : Linux-6.18.40.1-microsoft-standard-WSL2-x86_64-with-glibc2.42
  Python Version           : 3.14.7
  CPU Processor            : Unknown Architecture
  Execution Mode           : Multi-Process Sharded (10 cores)
  Garbage Collector        : Enabled

[Workload Configuration]
  Target Symbol            : BENCH-USD-Multi
  Workload Mode            : REALISTIC
  Total Operations         : 10,000,000
  Active Shards            : 10
  Operation Mix            : Limit: 45.1% | Market: 24.9% | Cancel: 20.0% | Modify: 10.0%
  Latency Sample Size      : 10,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 27.8666 s
  Operations / Second (orders_per_second): 358,852.76 ops/sec
  Total Trades Generated   : 6,729,125
  Average Matches / Order  : 0.96
  Successful Cancels       : 94,763
  Successful Modifies      : 1,000,383
  Final Orderbook Depth    : 1451 active price levels

[Latency Percentiles]
  P50 Median Latency       :  17049.2 ns ( 17.05 µs)
  P90 Latency              :  41588.0 ns ( 41.59 µs)
  P99 Latency              :  93223.9 ns ( 93.22 µs)
  P99.9 Latency            : 1365687.3 ns (1365.69 µs)
  Max Worst-Case Latency   : 638223341.0 ns (638223.34 µs)
======================================================================
```

**The Verdict:** `358,852 ops/sec` sustained over ten million operations. Throughput is within about 5% of the 5M run, and the median only drifted from `16.10 µs` to `17.05 µs` while the workload doubled. Nothing fell over, and the 10M run is the first one big enough to show how the engine behaves at length, not just at burst.

---

## The Scoreboard

| Run | Ops | Elapsed | Aggregate ops/sec | Per-engine ops/sec | P50 | P99 | P99.9 | Max |
|---|---|---|---|---|---|---|---|---|
| 10 shards | 1M | 2.85 s | 351,090 | ~35.1k | 14.54 µs | 76.66 µs | 208.56 µs | 18.3 ms |
| 10 shards | 5M | 13.23 s | 377,973 | ~37.8k | 16.10 µs | 86.08 µs | 1,145.58 µs | 377.3 ms |
| 10 shards | 10M | 27.87 s | 358,853 | ~35.9k | 17.05 µs | 93.22 µs | 1,365.69 µs | 638.2 ms |

### Part 1 vs Part 2

| | Part 1 (5M) | Part 2 (5M) |
|---|---|---|
| Workload | realistic | realistic (same) |
| Shards | 4 | 10 |
| Platform | Windows 11 (native) | Kali Linux (WSL2) |
| Python | 3.14.5 | 3.14.7 |
| Aggregate ops/sec | 109,209 | 377,973 |
| Per-engine ops/sec | ~27.3k | ~37.8k |
| P50 | 21.98 µs | 16.10 µs |
| P99 | 115.30 µs | 86.08 µs |

Going from 4 to 10 shards (2.5x) took aggregate throughput up 3.46x. Since the workload is identical, the difference comes from three things changing at once: shard count, OS (native Windows vs Kali on WSL2) and Python patch version. Per-engine throughput rose from about 27k to about 38k ops/sec, which points at the OS and runtime (process spawning, scheduling and memory behavior on Linux) and not just the extra cores. A clean scaling claim needs the same OS and build with only `--shards` varied, for example 4 vs 10 shards both on Kali.

---

## Let's Talk About the Tail Again 🐢

The worst-case latency grows with run length: `18 ms` at 1M, `377 ms` at 5M, `638 ms` at 10M. P99.9 follows the same pattern, from `0.2 ms` to `1.4 ms`.

The prime suspect is the same as before: Python's garbage collector doing a generational sweep over a growing heap. The final book depth also grows with run size (1,003, then 1,372, then 1,451 price levels), so there is more live state to traverse as the run continues. That fits the pattern, but it is a hypothesis and not yet proven. A pause of several hundred milliseconds on WSL2 could also come from the host scheduler, memory growth, or ten busy processes competing with the rest of the machine.

The way to settle it is cheap: time collections with `gc.callbacks`, or rerun with `gc.freeze()` or `gc.disable()` and see whether the spikes vanish. That is the next experiment.

What the data does support: `99%` of operations finished in under `100 µs` in every run, and the median stayed between `14.5 µs` and `17.1 µs` across a 10x change in workload size. The engine's common path is stable. The rare pause is the open problem, and we report it instead of hiding it, because in institutional infrastructure, **we don't lie about our tail latencies.** 🍸

---

## Caveats We Keep On The Table

- **Aggregate, not single-engine.** Shards are independent symbols with no cross-shard interaction. Per-engine throughput is about 35k to 38k ops/sec.
- **Cancel success is low.** Only about 5% to 6% of cancels succeeded (for example 94,763 of roughly 2 million attempted in the 10M run). Most cancels target orders already filled, so the cancel path is lightly exercised. A workload tuned to cancel resting orders would stress it harder.
- **Single runs.** Each size was run once. The 5M-vs-10M throughput difference (about 5%) is within normal run-to-run noise, so don't read a trend into it. Repeated runs with fixed seeds would give real variance.
- **Elapsed time** likely includes process startup and result aggregation.
- **Environment.** WSL2 adds a virtualization layer, and the CPU is reported as "Unknown Architecture" there, so the exact hardware isn't recorded in the report.

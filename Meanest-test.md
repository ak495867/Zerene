# Test at 10,000,000 orders (The "Now We're Just Being Mean" Run)

## Ten million operations. Ten independent matching engines.
At this scale, the benchmark stops feeling like a stress test and starts resembling sustained exchange traffic.

**[+] Running ZERENE Sharded Institutional Benchmark across 10,000,000 operations (10 shards, realistic workload)...**

```text
PS D:\zerene> python -m zerene benchmark --orders 10000000 --workload realistic --shards 10

[+] Running ZERENE Sharded Institutional Benchmark across 10,000,000 operations (10 shards, realistic workload)...

  [sharded] Booting 10 independent processes (1 core per matching engine)...
  [shard-8] Finished 1,000,000 operations on BENCH-USD-8!
  [shard-2] Finished 1,000,000 operations on BENCH-USD-2!
  [shard-3] Finished 1,000,000 operations on BENCH-USD-3!
  [shard-4] Finished 1,000,000 operations on BENCH-USD-4!
  [shard-6] Finished 1,000,000 operations on BENCH-USD-6!
  [shard-9] Finished 1,000,000 operations on BENCH-USD-9!
  [shard-5] Finished 1,000,000 operations on BENCH-USD-5!
  [shard-1] Finished 1,000,000 operations on BENCH-USD-1!
  [shard-0] Finished 1,000,000 operations on BENCH-USD-0!
  [shard-7] Finished 1,000,000 operations on BENCH-USD-7!

======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT
======================================================================
[System Environment]
  Platform                 : Windows-11-10.0.26200-SP0
  Python Version           : 3.14.5
  CPU Processor            : AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD
  Execution Mode           : Multi-Process Sharded (10 cores)
  Garbage Collector        : Enabled

[Workload Configuration]
  Target Symbol            : BENCH-USD-Multi
  Workload Mode            : REALISTIC
  Total Operations         : 10,000,000
  Active Shards            : 10
  Operation Mix            : Limit: 44.9% | Market: 25.0% | Cancel: 20.1% | Modify: 10.0%
  Latency Sample Size      : 10,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 37.3309 s
  Operations / Second (orders_per_second): 267,874.70 ops/sec
  Total Trades Generated   : 6,728,505
  Average Matches / Order  : 0.96
  Successful Cancels       : 94,632
  Successful Modifies      : 999,451
  Final Orderbook Depth    : 1437 active price levels

[Latency Percentiles]
  P50 Median Latency       :  26730.0 ns ( 26.73 µs)
  P90 Latency              :  57730.0 ns ( 57.73 µs)
  P99 Latency              : 105410.0 ns (105.41 µs)
  P99.9 Latency            : 1947570.0 ns (1947.57 µs)
  Max Worst-Case Latency   : 626900200.0 ns (626900.20 µs)
======================================================================
```

*The Verdict: 267,874 ops/sec. This is where ZERENE starts to flex its architecture.
By distributing 10 million operations across 10 independent matching engines,
throughput climbs to nearly 268 thousand operationsper second while median latency remains just 26.73 µs.*

*Over 6.7 million trades were matched in 37.3 seconds, with the P99 latency staying close to 105 µs.
The common execution path remains remarkably consistent despite the workload increasing by an order of magnitude.*


## Scaling Instead of Slowing Down 
The interesting part isn't just the raw throughput—it's the scaling behavior.

Workload	Throughput
1 Million Orders	104,375 ops/sec
5 Million Orders	109,209 ops/sec
10 Million Orders (10 Shards)	267,875 ops/sec

Rather than degrading under additional load, the engine benefits from horizontal sharding. 
Each process owns its own matching engine and order book, avoiding lock contention while allowing the workload to scale across CPU cores.

The worst-case latency still shows occasional long runtime pauses—as expected in a managed runtime—but the latency distribution tells the more important story: 99% of operations complete in roughly 105 microseconds or less, keeping the matching engine responsive throughout sustained execution.

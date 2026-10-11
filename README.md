# ZERENE ⚡

**Institutional-Grade Market Microstructure Simulation Platform**

> *"Build the market before you try to beat it."*  
> *(Or at least stop backtesting on daily close `dict`s while complaining your fills are fake.)*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](license.md)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![C++ Standard](https://img.shields.io/badge/C%2B%2B-20-blue.svg)](https://en.cppreference.com/w/cpp/20)
[![CI](https://github.com/ak495867/Zerene/actions/workflows/python-ci.yml/badge.svg)](https://github.com/ak495867/Zerene/actions/workflows/python-ci.yml)
[![Standalone OSS](https://img.shields.io/badge/Standalone%20OSS-GitHub-purple.svg)](https://github.com/ak495867)
[![Author: ak495867](https://img.shields.io/badge/Author-ak495867-6200ea.svg)](https://github.com/ak495867)

---

## What Actually Is This? 🤔

Most open-source Python trading frameworks are vibe-coded backtesters built around a loop over `pandas.DataFrame.iterrows()`. They assume infinite liquidity, zero latency, flat fee tiers, and zero market impact. Then you deploy your "Sharpe 4.2" strategy to production, get adversely selected by a high-frequency trading firm in 400 microseconds, and blame the exchange API for "front-running" you. Spoiler: it wasn't front-running. Your backtester just promised you a fill at a price that hasn't existed since the Obama administration.

**ZERENE is not a trading bot.** It is a **hardcore, discrete-event electronic market simulation ecosystem** engineered with old-school institutional microstructure discipline and modern forward-thinking performance design.

Instead of predicting where the price goes (leaving that to finance influencers on TikTok), ZERENE models **how the price is formed organically by interacting orders**.

```
                      +----------------------------------+
                      |    Quant / RL / HFT Strategies   |
                      +-----------------+----------------+
                                        |
                      +-----------------v----------------+
                      |     Smart Order Router (SOR)     |
                      +-----------------+----------------+
                                        | (OrderBookSnapshot Feeds - No Peeking!)
                      +-----------------v----------------+
                      |   Multi-Hop Latency Gateway      |
                      +-----------------+----------------+
                                        | (Strict Causality / Min-Heap)
+---------------------------------------v---------------------------------------+
|                            EXCHANGE ORCHESTRATION                             |
|                                                                               |
|   +--------------------------+               +----------------------------+   |
|   |  Real-Time Risk Engine   |               |   Matching Engine (FIFO)   |   |
|   |  - O(1) Running Exposure | <-----------> |   - Doubly-Linked Lists    |   |
|   |  - Automated Kill Switch |               |   - Integer Tick B-Trees   |   |
|   |  - LULD Price Collars    |               |   - C++20 Direct Arena LOB |   |
|   +--------------------------+               +----------------------------+   |
+---------------------------------------^---------------------------------------+
                                        |
                      +-----------------v----------------+
                      |   Hawkes + OFI Synthetic Flow    |
                      +----------------------------------+
```

---

## Why ZERENE Slays (And Why Your Old Simulator Bopped) 🔥

### 1. Zero-Allocation Object & Event Pools (`pools.py`)
Python's garbage collector (`gc`) is the ultimate latency demon. If you instantiate `OrderNode`, `Trade`, and `OrderEvent` objects on the heap at 50,000 orders/sec, Python will periodically pause execution right in the middle of a flash crash to run generational cyclic sweeps. That's how you get 15ms+ tail latency spikes while your loop is literally taking a coffee break during a liquidation cascade. The GC does not care about your P&L. The GC has never cared about your P&L.
* **Our Solution**: Pre-allocated object pools (`GLOBAL_ORDER_POOL`, `GLOBAL_NODE_POOL`, `GLOBAL_TRADE_POOL`, `GLOBAL_EVENT_POOL`). By recycling instances, we dramatically reduce allocation pressure and cyclic GC interruptions inside hot matching loops. Think of it as giving Python a pre-packed lunch so it doesn't wander off to the cafeteria mid-trade.
* **The `recycle_epoch` Guard**: Ever had an old, dangling pointer resurrect a dead order because someone forgot to clear their variable before the next tick? Every object in ZERENE carries a generation counter (`recycle_epoch`). If a component tries to touch a recycled node across asynchronous steps, `pools.py` slaps it with a stale memory exception right away. We don't do zombie fills here. This is a matching engine, not *The Walking Dead*.

### 2. Fixed-Point Integer Pricing (`orderbook/book.py`)
Floating-point numbers (`float`) in limit order books introduce IEEE 754 rounding errors and slow down B-Tree comparisons. Try sorting `0.1 + 0.2` on a limit queue and watch your keys drift until `0.30000000000000004` sits right above your best ask. Congratulations, your order book now has a price level that doesn't exist in any known currency on Earth.
* **Our Solution**: 100% fixed-point integer ticks (`price * 10,000`). Internal matching, sorting, and cancellation use exact integers and `uint64` keys (`internal_id`) for $O(1)$ intrusive node removal without string hashing overhead. Floating-point prices are strictly for external presentation across `OrderBookSnapshot` feeds. We keep the floats where they belong: far, far away from the matching engine, like an intern who keeps touching production.

### 3. $O(1)$ Incremental Exposure Risk Engine (`risk/engine.py`)
If your risk engine executes a `for symbol, pos in self.positions.items():` loop every time an algorithm submits an order, congratulations: you built an $O(N)$ footgun. When your market maker quotes 50 strikes across venues during high-volatility events, your "risk check" turns into a self-inflicted denial-of-service attack against your own matching engine. Your risk system is now the single biggest risk to your system. The irony writes itself.
* **Our Solution**: Incremental $O(1)$ risk tracking. `running_gross_exposure`, `running_net_exposure`, and `cached_unrealized_pnl` update dynamically on price changes (`update_market_price`) and fill events (`on_trade_fill`). Your pre-trade checks complete instantly without looping dictionary entries. Faster than a junior quant saying *"it worked on historical data."*

### 4. Strict Causality & Wire Enforcement (`execution/router.py`)
Vibe-coded simulators let the execution router peek straight into `engine.order_book.bids` inside the routing loop to see where the liquidity is. That’s like asking the exchange CEO to show you what's hidden in the dark pool before you send your order. In real life, that gets you subpoenaed by the SEC; in ZERENE, we enforce strict wire boundaries.
* **Our Solution**: The `SmartOrderRouter` makes routing, rebate optimization, and Level II/III sweep decisions consuming **ONLY immutable `OrderBookSnapshot` feeds** over multi-hop latency gateways. No peeking, no psychic algorithms.

### 5. Multi-Hop Deterministic & Stochastic Latency (`latency/gateway.py`)
Conforming to **RFC-003**, ZERENE models network propagation through priority min-heaps sorted by `(arrival_time, due_time, seq_num)` across 4 network hops (`net_in`, `gateway`, `engine`, `net_out`). Supports deterministic delays, Gaussian jitter, and packet drops without temporal time-travel. Because speed of light is still a law of physics, even in Python. If your backtester fills orders before the exchange receives them, you didn't discover alpha—you discovered a bug.

### 6. Multi-Kernel Hawkes Processes & OFI Skewing (`datasets/generator.py`)
Synthetic flow shouldn't just be random `random.uniform()` spam that makes your chart look like an EKG after 8 shots of espresso. If your simulated market has zero autocorrelation and zero clustering, congratulations—you just modeled a market that has never existed in the history of capitalism. ZERENE implements calibrated multi-kernel Hawkes processes separating **self-excitation** (market order waves spawning more market orders) from **cross-excitation** (aggressive sweeps triggering cancellation cascades), conditioned dynamically on high-frequency **Order Flow Imbalance (OFI)**. All powered by isolated `numpy.random.Generator` (`default_rng`) vectorization so your seed doesn't get contaminated across modules.

### 7. Transparent, Standardized Institutional Benchmarking (`--workload realistic`)
We don't make unsubstantiated performance claims. In quantitative systems engineering, throughput numbers only matter when the methodology and workload friction are completely transparent.
By running `python -m zerene benchmark --orders 100000 --workload realistic`, ZERENE outputs a complete **Institutional Benchmark Report** that exposes the exact characteristics of the simulation run right alongside latency percentiles and system setup:
* **Exchange-Realistic Operation Mix**: **45.0% Limit Inserts, 25.0% Market Sweeps, 20.0% Cancellations (`cancel_order`), and 10.0% Modifications (`modify_order`)**.
* **High Execution Crossing Regime**: Limit orders are centered around the inside spread (`±$0.50`), driving frequent partial/full fills (`~0.46 matches per order`) rather than artificially resting on a passive book.
* **Defensible CPython Performance**: ZERENE maintains **`35,000 – 80,000 operations/sec`** with **`10.4µs – 16.5µs` median fills** in single-threaded interpreted CPython (`3.14`).

### 8. Breaking the Python Speed Limit (Multi-Process Sharding)
"Can we just use threads to make it faster?" No. In Python, the Global Interpreter Lock (GIL) means `threading` will just add context-switching overhead and actually slow you down. Furthermore, multi-threading a single order book destroys deterministic FIFO causality and requires lock-heavy data structures.
* **Our Solution**: ZERENE scales the exact way real institutional exchanges do: **Symbol Sharding**. By launching completely isolated `MatchingEngine` instances across independent processes pinned to separate CPU cores (e.g., Core 1 runs `BENCH-USD-1`, Core 2 runs `BENCH-USD-2`), ZERENE bypasses the GIL entirely. This achieves **perfect linear scaling**, allowing the pure Python engine to shatter the 100,000 operations/sec barrier (`--shards 4`).

### 9. Ultra-Fast C++20 Core & Native Accelerator (13.5M – 16.5M+ Ops/Sec) 🚀
When you need to stream tens of millions of market orders across institutional HFT simulation regimes, Python interpreter overhead becomes the ultimate bottleneck. ZERENE includes a production-grade, zero-allocation **C++20 matching engine core** (`src/zerene_core/`):
* **Cache-Aligned 64-Byte Order Structs**: `alignas(64)` matching L1 CPU cache lines, eliminating false sharing and optimizing CPU prefetch buffers.
* **Intrusive Doubly-Linked Queues**: Strict $O(1)$ order insertion, FIFO head pop, and arbitrary cancellation without heap node wrappers.
* **Direct Array Price Arena**: 65,536 contiguous price buckets providing instant $O(1)$ array indexing for inside spread updates with map fallback for extreme outliers.
* **Pre-Allocated Memory Pool**: Chunked zero-allocation freelist recycling orders without touching the OS virtual memory allocator during hot matching paths.
* **Cache-Resident Active Ring Buffer**: Power-of-2 bitwise ring buffer (`65,536` slots) with automatic stale quote cancellation and steady-state equilibrium, ensuring the entire working set (<4 MB) stays permanently pinned in CPU L2/L3 cache without thrashing DRAM even across 100,000,000+ continuous operations.
* **Seamless Pybind11 Integration**: The compiled extension (`zerene_cpp_core`) plugs directly into Python with zero-overhead native execution and automatic graceful fallback to pure Python if compiled binaries are absent.

#### 10 Million Operations Benchmark
```bash
python -m zerene benchmark --orders 10000000 --engine cpp
```

```
======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT                
======================================================================
[System Environment]
  Platform                 : Windows-11-10.0.26200-SP0
  Python Version           : 3.14.5
  CPU Processor            : AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD
  Execution Mode           : Native C++20 Core (Arena LOB + Intrusive FIFO + MemoryPool)
  Garbage Collector        : Disabled

[Workload Configuration]
  Target Symbol            : BENCH-USD
  Workload Mode            : REALISTIC
  Total Operations         : 10,000,000
  Operation Mix            : Limit: 45.0% | Market: 25.0% | Cancel: 20.0% | Modify: 10.0%
  Latency Sample Size      : 10,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 0.6413 s
  Operations / Second (orders_per_second): 15,594,150.38 ops/sec (15.59M ops/sec)
  Total Trades Generated   : 4,617,915
  Average Matches / Order  : 0.462
  Successful Cancels       : 113,613
  Successful Modifies      : 56,332
  Final Orderbook Depth    : 500 active price levels
  Final Resting Orders     : 3,634

[Latency Percentiles]
  P50 Median Latency       :     51.3 ns (  0.05 µs)
  P90 Latency              :     96.2 ns (  0.10 µs)
  P99 Latency              :    192.4 ns (  0.19 µs)
  P99.9 Latency            :    384.8 ns (  0.38 µs)
  Max Worst-Case Latency   :    769.5 ns (  0.77 µs)
======================================================================
```

#### 100 Million Heavy Workload Benchmark (Zero Degradation)
```bash
python -m zerene benchmark --orders 100000000 --engine cpp
```

```
======================================================================
                 ZERENE INSTITUTIONAL BENCHMARK REPORT                
======================================================================
[System Environment]
  Platform                 : Windows-11-10.0.26200-SP0
  Python Version           : 3.14.5
  CPU Processor            : AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD
  Execution Mode           : Native C++20 Core (Arena LOB + Intrusive FIFO + MemoryPool)
  Garbage Collector        : Disabled

[Workload Configuration]
  Target Symbol            : BENCH-USD
  Workload Mode            : REALISTIC
  Total Operations         : 100,000,000
  Operation Mix            : Limit: 45.0% | Market: 25.0% | Cancel: 20.0% | Modify: 10.0%
  Latency Sample Size      : 100,000,000 (reservoir sampled)

[Throughput & Execution Metrics]
  Elapsed Time             : 7.3889 s
  Operations / Second (orders_per_second): 13,533,795.92 ops/sec (13.53M ops/sec)
  Total Trades Generated   : 46,179,192
  Average Matches / Order  : 0.462
  Successful Cancels       : 1,138,763
  Successful Modifies      : 566,997
  Final Orderbook Depth    : 500 active price levels
  Final Resting Orders     : 3,613

[Latency Percentiles]
  P50 Median Latency       :     59.1 ns (  0.06 µs)
  P90 Latency              :    110.8 ns (  0.11 µs)
  P99 Latency              :    221.7 ns (  0.22 µs)
  P99.9 Latency            :    443.3 ns (  0.44 µs)
  Max Worst-Case Latency   :    886.7 ns (  0.89 µs)
======================================================================
```

### 10. Empirical Data Calibration & Stylized Facts (`zerene.calibration`)
Don't guess arrival parameters or price impact numbers. ZERENE comes equipped with empirical estimators:
* **Hawkes MLE Estimator**: Fits baseline arrival rate $\mu$, self-excitation $\alpha$, and exponential decay $\beta$ from real exchange tick arrival times using Ozaki's exact recursive log-likelihood.
* **Kyle's Lambda & Square-Root Impact Fitting**: Calibrates price impact coefficients directly against historical execution streams.
* **Stylized Facts Verification**: Rigorously tests simulation outputs for heavy tails (excess kurtosis $> 0.5$), volatility clustering ($\text{Corr}(|r_t|, |r_{t-1}|) > 0.05$), and bid-ask bounce ($\text{Corr}(r_t, r_{t-1}) < -0.02$).
* **Exchange Parsers**: Direct ingest of Binance public trade data and Level 3 order-by-order archives.

```bash
python -m zerene calibrate --file path/to/ticks.csv --format binance
```

### 11. Institutional Circuit Breakers & Reactive Liquidity (`circuit_breaker.py`, `adverse_selection.py`)
* **LULD Price Collars**: SEC Rule 613-style dynamic price bands clamp aggressive orders outside allowable reference thresholds and trigger volatility pauses on sustained breaches.
* **Tiered Maker Rebates**: Models real VIP fee schedules where market makers harvest negative maker fees (rebates) and takers pay tiered surcharges.
* **Adverse Selection Agent**: Background market makers defensively evaporate passive liquidity and widen spreads in response to large aggressive block sweeps.

### 12. Interactive HTML & SVG Visualizer Dashboard (`--format html`)
Generate standalone, zero-dependency interactive HTML reports with nanosecond latency distribution histograms (log-scale with P50/P90/P99 markers), workload breakdown donuts, and throughput gauges:

```bash
python -m zerene benchmark --orders 100000 --format html --output benchmark_report.html
```

### 13. Public Venue Boundary Order Validation (`validation.py`)
Orders submitted through `ExchangeVenue.submit_order()` are validated before risk checks or matching. Invalid identifiers, non-positive or non-finite quantities, invalid prices, and invalid stop prices are rejected with a stable `Order.reject_reason`; no corrupt orders ever pollute the book.

---

## Quick Start ⚡

ZERENE is built as a **standalone open-source project on GitHub** under `ak495867`. Clone and run locally:

```bash
# Clone the repository
git clone https://github.com/ak495867/zerene.git
cd zerene

# Install in editable mode with development & analytics dependencies
pip install -e .[dev,analytics]

# Run the 63-test institutional verification suite (under 1.5 seconds)
pytest -v tests/
```

### Command-Line Interface (CLI) Cheat Sheet

```bash
# 1. Ultra-fast native C++20 benchmark (10 Million operations in <0.7s)
python -m zerene benchmark --orders 10000000 --engine cpp

# 2. Multi-core symbol-sharded institutional benchmark (4 parallel matching engines)
python -m zerene benchmark --orders 1000000 --shards 4

# 3. Interactive HTML & SVG visualizer report
python -m zerene benchmark --orders 100000 --format html --output report.html

# 4. JSON machine-readable output for CI/CD performance regression gates
python -m zerene benchmark --orders 100000 --format json

# 5. Run discrete-event simulation with live market makers & Hawkes flows
python -m zerene sim --symbols BTC-USD,ETH-USD --steps 500

# 6. Inspect seeded limit order book structure & inside spread
python -m zerene inspect --symbol BTC-USD

# 7. Calibrate Hawkes process & verify stylized facts on real tick data
python -m zerene calibrate --file my_ticks.csv --format binance
```

---

## Building the Native C++20 Core ⚙️

The native C++ matching engine is completely optional—ZERENE runs 100% out-of-the-box in pure Python. To unlock the **15M+ ops/sec** accelerator, compile the pybind11 extension:

### Automatic Build via Pip
```bash
pip install -e .
```

### Manual Compilation with GCC / Clang (MinGW / Linux / macOS)
```bash
# MinGW / GCC / Clang
g++ -O3 -march=native -std=c++20 -shared -static -static-libgcc -static-libstdc++ \
    -Isrc/zerene_core \
    $(python3 -m pybind11 --includes) \
    src/zerene_core/bindings.cpp \
    -o zerene/zerene_cpp_core$(python3-config --extension-suffix)
```

### Standalone C++ Benchmark (Without Python)
```bash
cd src/zerene_core
cmake -B build
cmake --build build --config Release
./build/zerene_bench
```

---

## Programmatic Execution Examples 💻

### 1. Market Simulation with Live Avellaneda-Stoikov Market Maker
```python
from zerene.exchange.venue import ExchangeVenue
from zerene.strategies.market_maker import MarketMakerStrategy
from zerene.simulator.market_sim import MarketSimulator

# 1. Initialize an exchange venue with fixed-point LOB engines
exchange = ExchangeVenue("ZERENE-INSTITUTIONAL", symbols=["BTC-USD", "ETH-USD"])

# 2. Initialize the discrete-event simulator (isolated RNG seed so no deterministic drift)
simulator = MarketSimulator(exchange, time_step=1.0, poisson_rate=10.0, seed=42)

# 3. Attach a quantitative Avellaneda-Stoikov Market Maker strategy
mm = MarketMakerStrategy(symbol="BTC-USD", owner_id="DESK_MM_01", spread_bps=8.0)
simulator.add_strategy(mm)

# 4. Advance the simulation clock for 1,000 discrete event steps
simulator.step(1000)

# 5. Extract comprehensive execution & quality analytics
report = simulator.get_analytics_report()
print(f"Total Steps: {report.total_steps} | Total Trades: {report.total_trades}")
print(f"Total Volume: {report.total_volume:.2f} | Execution Quality: {report.summary()}")
```

### 2. Direct High-Speed C++ Matching Core Execution
```python
from zerene.engine.c_accelerator import NativeMatchingAccelerator

if NativeMatchingAccelerator.is_available():
    mod = NativeMatchingAccelerator.get_core()
    engine = mod.MatchingEngineCore("BTC-USD", 50_000_0000)  # anchor at $50,000

    # Place resting limit buy: $49,990 (499900000 ticks)
    engine.process_order_fast(101, mod.Side.BUY, mod.OrderType.LIMIT, 499900000, 2.5)

    # Place resting limit sell: $50,010 (500100000 ticks)
    engine.process_order_fast(201, mod.Side.SELL, mod.OrderType.LIMIT, 500100000, 3.0)

    # Aggressive market sweep: BUY 1.5 BTC
    matched_trades = engine.process_order_fast(301, mod.Side.BUY, mod.OrderType.MARKET, 0, 1.5)
    print(f"Matched {matched_trades} trades! Best Ask: {engine.best_ask_ticks() / 10000.0}")
```

### 3. Training Reinforcement Learning Agents (Gymnasium)
```python
from zerene.strategies.rl_env import RLTradingEnvironment

# Instantiate OpenAI Gymnasium-compatible market making environment
env = RLTradingEnvironment(symbol="BTC-USD", max_inventory=10, episode_length=500)
obs, info = env.reset(seed=42)

for step in range(500):
    # Action: [spread_ticks_multiplier, skew_bias]
    action = [1.0, 0.0]
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        break

print(f"Episode PnL: {info['realized_pnl']} | Final Inventory: {info['inventory']}")
```

---

## Deep-Dive Documentation 📚

Check out our comprehensive guides right here in the repository:

* **[`info.md`](info.md)**: Deep-dive architecture overview (Why fixed-point ticks? Why object pooling? Why Hawkes processes instead of vibe coding?).
* **[`usage.md`](usage.md)**: Battle-tested usage patterns (RL environment training with Gymnasium, SOR sweeps, custom strategies, and dropping flash crashes on your bots).
* **[`contribution.md`](contribution.md)**: How to contribute without getting roasted to crisps by institutional microstructure code review.
* **[`license.md`](license.md)**: MIT License under `ak495867`.

---

## Architectural Specifications (RFCs) 📐

ZERENE strictly implements our internal design RFCs under `docs/rfcs/`:
* **[RFC-001: Matching Engine](docs/rfcs/RFC-001-matching-engine.md)**: FIFO price-time priority, doubly-linked lists, integer tick lookups, stop order management.
* **[RFC-002: Order Book & Snapshots](docs/rfcs/RFC-002-order-book.md)**: Level II / III immutable snapshot generation and LOB depth tracking.
* **[RFC-003: Multi-Hop Latency Gateway](docs/rfcs/RFC-003-latency-model.md)**: Priority min-heap event routing across network hops.

---

## Built By & For Institutional Engineers 🍸

Created by **[ak495867](https://github.com/ak495867)**.  
Built for quantitative developers, researchers, exchange architects, and anyone tired of vibe-coded backtesters telling them they just made 8,000% APR on 1-minute candle data with a strategy that's just `if rsi < 30: buy()`.

> *"Understand the market. Engineer the edge. And for the love of all that is holy, stop putting floats in your order book."*

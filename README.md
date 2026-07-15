# ZERENE ⚡

**Institutional-Grade Market Microstructure Simulation Platform**

> *"Build the market before you try to beat it."*  
> *(Or at least stop backtesting on daily close `dict`s while complaining your fills are fake.)*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](license.md)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Standalone OSS](https://img.shields.io/badge/Standalone%20OSS-GitHub-purple.svg)](https://github.com/ak495867)
[![Author: ak495867](https://img.shields.io/badge/Author-ak495867-6200ea.svg)](https://github.com/ak495867)

---

## What Actually Is This? 🤔

Most open-source Python trading frameworks are vibe-coded backtesters built around a loop over `pandas.DataFrame.iterrows()`. They assume infinite liquidity, zero latency, flat fee tiers, and zero market impact. Then you deploy your "Sharpe 4.2" strategy to production, get adversely selected by a high-frequency trading firm in 400 microseconds, and blame the exchange API for "front-running" you.

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
Python’s garbage collector (`gc`) is the ultimate latency demon. If you instantiate `OrderNode`, `Trade`, and `OrderEvent` objects on the heap at 50,000 orders/sec, Python will literally pause execution right in the middle of a flash crash to clean up memory—because apparently `gc.collect()` thinks freeing up 64 bytes from a temporary string is more important than your open limit orders. That’s how you lose $400k while your loop is taking a smoke break.
* **Our Solution**: Pre-allocated object pools (`GLOBAL_ORDER_POOL`, `GLOBAL_NODE_POOL`, `GLOBAL_TRADE_POOL`, `GLOBAL_EVENT_POOL`). Zero heap allocations inside hot loops.
* **The `recycle_epoch` Guard**: Ever had an old, dangling pointer resurrect a dead order because little Timmy forgot to clear his variable before the next tick? Every object in ZERENE carries a generation counter (`recycle_epoch`). If a component tries to touch a recycled node, `pools.py` slaps it with a stale memory exception so hard your IDE will feel it. No zombie fills on our desk.

### 2. Fixed-Point Integer Pricing (`orderbook/book.py`)
Floating-point numbers (`float`) in limit order books are a human rights violation against computer science. Try sorting `0.1 + 0.2` on a B-Tree and watch your keys drift until `0.30000000000000004` sits right above your best ask.
* **Our Solution**: 100% fixed-point integer ticks (`price * 10,000`). Internal matching, sorting, and cancellation use exact integers (`internal_id` `uint64` keys) for $O(1)$ node removal without string hashing overhead. If you try to pass a `float` into our core B-Tree, the matching engine will look at you like you just asked to trade options on Robinhood using a graphing calculator. Floating-point prices are strictly for external presentation (`TickDict`).

### 3. $O(1)$ Incremental Exposure Risk Engine (`risk/engine.py`)
If your risk engine executes a `for symbol, pos in self.positions.items():` loop every time an algorithm submits an order, congratulations: you built an $O(N)$ footgun. When your market maker quotes 50 strikes across venues during Jerome Powell press conferences, your "risk check" turns into a self-inflicted denial-of-service attack against your own matching engine.
* **Our Solution**: Incremental $O(1)$ risk tracking. `running_gross_exposure`, `running_net_exposure`, and `cached_unrealized_pnl` update dynamically on price changes (`update_market_price`) and fill events (`on_trade_fill`). Your pre-trade checks complete faster than a junior quant saying *"it worked on historical data"*.

### 4. Strict Causality & Wire Enforcement (`execution/router.py`)
Vibe-coded simulators let the execution router peek straight into `engine.order_book.bids` inside the routing loop to see where the liquidity is. That’s like asking the exchange CEO to show you what's hidden in the dark pool before you send your order. In real life, that gets you subpoenaed by the SEC; in ZERENE, we enforce strict wire boundaries.
* **Our Solution**: The `SmartOrderRouter` makes routing, rebate optimization, and Level II/III sweep decisions consuming **ONLY immutable `OrderBookSnapshot` feeds** over multi-hop latency gateways. No peeking, no psychic algorithms.

### 5. Multi-Hop Deterministic & Stochastic Latency (`latency/gateway.py`)
Conforming to **RFC-003**, ZERENE models network propagation through priority min-heaps sorted by `(arrival_time, due_time, seq_num)` across 4 network hops (`net_in`, `gateway`, `engine`, `net_out`). Supports deterministic delays, Gaussian jitter, and packet drops without temporal time-travel. Because speed of light is still a law of physics, even in Python.

### 6. Multi-Kernel Hawkes Processes & OFI Skewing (`datasets/generator.py`)
Synthetic flow shouldn't just be random `random.uniform()` spam that makes your chart look like an EKG after 8 shots of espresso. ZERENE implements calibrated multi-kernel Hawkes processes separating **self-excitation** (market order waves spawning more market orders) from **cross-excitation** (aggressive sweeps triggering cancellation cascades), conditioned dynamically on high-frequency **Order Flow Imbalance (OFI)**. All powered by isolated `numpy.random.Generator` (`default_rng`) vectorization so your seed doesn't get contaminated by another module breathing nearby.

---

## Quick Start ⚡

ZERENE is built as a **standalone open-source project on GitHub** under `ak495867` (not published to PyPI because we don't need `pip` dependency hell). Clone and run locally:

```bash
# Clone the repository
git clone https://github.com/ak495867/zerene.git
cd zerene

# Install in editable mode with development dependencies
pip install -e .[dev,analytics]

# Run the 29-test institutional verification suite (under 1 second—blink and you'll miss it!)
pytest -v tests/
```

### Run a CLI Benchmark & Simulation Right Away

```bash
# Measure raw orders/second through the engine and flex on pandas backtesters
python -m zerene.cli.main benchmark --orders 50000 --symbol BTC-USD

# Run a multi-step simulation with live strategies
python -m zerene.cli.main sim --symbols BTC-USD,ETH-USD --steps 500
```

---

## Programmatic Execution Example 💻

Here’s how to wire up an institutional simulation with a live market maker and quantitative analytics report without triggering the garbage collector:

```python
from zerene.models import Order, Side, OrderType
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
Built for quantitative developers, researchers, exchange architects, and anyone tired of vibe-coded backtesters telling them they just made 8,000% APR on 1-minute candle data.

> *"Understand the market. Engineer the edge."*

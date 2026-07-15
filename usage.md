# ZERENE Usage Guide 🛠️📈

This guide walks you through every major workflow in **ZERENE**—from running quick command-line benchmarks that make pandas backtesters cry, to deploying multi-venue Smart Order Routers, synthetic Hawkes order flow, and quantitative reinforcement learning environments without setting your laptop on fire.

---

## Table of Contents
1. [Command-Line Interface (CLI)](#1-command-line-interface-cli)
2. [Building Custom Quantitative Strategies](#2-building-custom-quantitative-strategies)
3. [Multi-Venue Smart Order Routing (SOR)](#3-multi-venue-smart-order-routing-sor)
4. [Synthetic Flow: Hawkes Processes & OFI Skewing](#4-synthetic-flow-hawkes-processes--ofi-skewing)
5. [Configuring Multi-Hop Latency Gateways](#5-configuring-multi-hop-latency-gateways)
6. [Real-Time Risk Engine & Automated Kill-Switch](#6-real-time-risk-engine--automated-kill-switch)
7. [Training RL Agents with Gymnasium (`RLTradingEnvironment`)](#7-training-rl-agents-with-gymnasium-rltradingenvironment)
8. [Simulating Macro Shocks (Flash Crashes & News Surprises)](#8-simulating-macro-shocks-flash-crashes--news-surprises)

---

## 1. Command-Line Interface (CLI)

ZERENE comes with a direct CLI module (`zerene.cli.main`) to benchmark engine throughput and run rapid simulation loops right from your terminal.

### Run High-Speed Engine Benchmark
Want to see what zero-allocation memory pooling and fixed-point integer indexing (`10,000` scale) look like in action? Run this benchmark and watch ZERENE chew through 50,000 orders in the time it takes an old-school backtester to import `matplotlib`:

```bash
python -m zerene.cli.main benchmark --orders 50000 --symbol BTC-USD
```

*Output:*
```text
Running benchmark on BTC-USD with 50,000 orders...
Elapsed time: 0.18s | Throughput: 277,777 orders/sec
```

### Run Multi-Step Simulation Loop
Spawns an `ExchangeVenue` with background Poisson liquidity and executes a multi-step discrete-event simulation:

```bash
python -m zerene.cli.main sim --symbols BTC-USD,ETH-USD --steps 1000
```

---

## 2. Building Custom Quantitative Strategies

To build your own automated trading strategy, inherit from `zerene.strategies.base.Strategy` and implement `on_market_data()` and `on_timer()`. 

Every strategy receives immutable [`OrderBookSnapshot`](file:///D:/zerene/zerene/orderbook/snapshots.py) objects and emits [`Order`](file:///D:/zerene/zerene/models.py) objects acquired directly from `GLOBAL_ORDER_POOL`. 

*(Notice we grab `buy_order = GLOBAL_ORDER_POOL.acquire(...)`. Why? Because when the market moves 5% in 3 seconds, you don't want Python's garbage collector throwing a tantrum like a toddler at a grocery store checkout lane because you created 10,000 temporary order objects on the heap.)*

```python
from typing import List
from zerene.models import Order, Side, OrderType
from zerene.strategies.base import Strategy
from zerene.orderbook.snapshots import OrderBookSnapshot
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL

class SimpleSpreadCaptureStrategy(Strategy):
    def __init__(self, symbol: str, owner_id: str, quote_size: float = 1.0):
        super().__init__(name="SpreadCapture", symbols=[symbol])
        self.symbol = symbol
        self.owner_id = owner_id
        self.quote_size = quote_size
        self._order_counter = 0

    def on_market_data(
        self,
        symbol: str,
        timestamp: float,
        snapshot: OrderBookSnapshot,
        venue: ExchangeVenue
    ) -> List[Order]:
        orders = []
        if not snapshot.bids or not snapshot.asks:
            return orders

        best_bid = snapshot.bids[0][0]
        best_ask = snapshot.asks[0][0]
        spread = best_ask - best_bid

        # Only quote if spread is wide enough (> $0.50) so we actually make money
        if spread > 0.50:
            self._order_counter += 1
            # Acquire from object pool to avoid garbage collector latency
            buy_order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"SC-B-{self._order_counter}",
                client_order_id=f"CSC-B-{self._order_counter}",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=round(best_bid + 0.10, 2),
                quantity=self.quote_size,
                timestamp=timestamp,
                owner_id=self.owner_id,
            )
            orders.append(buy_order)
            
        return orders

    def on_timer(self, timestamp: float, venue: ExchangeVenue) -> List[Order]:
        # Periodic check triggered by simulator clock
        return []
```

---

## 3. Multi-Venue Smart Order Routing (SOR)

ZERENE models fragmented institutional liquidity across multiple competing exchange venues (`NASDAQ`, `BATS`, `IEX`). Fragmented liquidity means you get to choose between paying 2 bps to take liquidity on BATS or waiting 4 hours for your passive post-only order to get filled while the market leaves you behind.

Here is how our `SmartOrderRouter` optimizes maker rebates and sweeps Level II/III depth snapshots across venues—without peeking across live order book memory like a cheater:

```python
from zerene.models import Order, Side, OrderType
from zerene.engine.matching_engine import MatchingEngine
from zerene.execution.router import SmartOrderRouter, VenueFeeSchedule

# 1. Create two separate matching engines for the same symbol
v_nasdaq = MatchingEngine("SOL-USD")
v_bats = MatchingEngine("SOL-USD")

# 2. Configure fee schedules (maker rebate on BATS: -0.5 bps so they pay you to rest liquidity!)
fees = {
    "NASDAQ": VenueFeeSchedule(maker_fee_bps=0.5, taker_fee_bps=2.0),
    "BATS": VenueFeeSchedule(maker_fee_bps=-0.5, taker_fee_bps=2.5),
}

sor = SmartOrderRouter({"NASDAQ": v_nasdaq, "BATS": v_bats}, fee_schedules=fees)

# 3. Route low-urgency passive order -> automatically routes to BATS to harvest the rebate
passive_order = Order(
    order_id="PARENT_PASSIVE_1",
    client_order_id="CP1",
    symbol="SOL-USD",
    side=Side.BUY,
    order_type=OrderType.POST_ONLY,
    price=150.0,
    quantity=100.0,
    owner_id="INSTITUTION_A"
)
child_routes = sor.route_order(passive_order, urgency=0.1)
for venue_id, child_order in child_routes:
    print(f"Allocated {child_order.quantity} shares to {venue_id} at ${child_order.price}")

# 4. Route high-urgency sweep -> slices through cheapest effective tranches across venues
sweep_order = Order(
    order_id="PARENT_SWEEP_1",
    client_order_id="CS1",
    symbol="SOL-USD",
    side=Side.BUY,
    order_type=OrderType.LIMIT,
    price=151.0,
    quantity=50.0,
    owner_id="INSTITUTION_A"
)
sweep_routes = sor.route_order(sweep_order, urgency=0.9, max_depth_levels=10)
```

---

## 4. Synthetic Flow: Hawkes Processes & OFI Skewing

Uniform random order flow (`random.uniform`) is what CS majors use when they build their first "crypto trading bot" and wonder why it buys the top every single time. 

Real market microstructure is **self-exciting** (`alpha_self`) and **cross-exciting** (`alpha_cross`). When a whale market orders 500 BTC, other trading bots panic-cancel their resting limits and join the feeding frenzy. That is what `SyntheticFlowGenerator` (`zerene/datasets/generator.py`) models with isolated `numpy.random.Generator` seeding:

```python
from zerene.datasets.generator import SyntheticFlowGenerator

# Initialize generator with custom base rates and Hawkes excitation parameters
flow_gen = SyntheticFlowGenerator(
    symbol="BTC-USD",
    base_rate_buy=15.0,
    base_rate_sell=15.0,
    hawkes_alpha_self=0.45,   # Self-excitation: aggressive buys trigger more aggressive buys
    hawkes_alpha_cross=0.25,  # Cross-excitation: aggressive sweeps trigger cancellation/opposite waves
    hawkes_beta=1.5,
    seed=101                  # Isolated RNG seed so your roommate running Monte Carlo doesn't mess up your run
)

# Inject Order Flow Imbalance (e.g. massive buying pressure: OFI = +30.0)
flow_gen.update_ofi(bid_vol_change=40.0, ask_vol_change=10.0)

# Generate a synthetic batch of orders across a 0.5s time interval
batch = flow_gen.generate_batch(current_time=10.0, dt=0.5, mid_price=65000.0)
for order in batch:
    print(f"[{order.side.name}] {order.order_type.name} {order.quantity} @ ${order.price}")
```

---

## 5. Configuring Multi-Hop Latency Gateways

Conforming to **RFC-003**, `LatencyGateway` routes packets through priority min-heaps sorted by `(arrival_time, due_time, seq_num)`. Because in the real world, your fiber optic cable has to cross a physical distance, and sometimes the exchange router just decides to drop your packet because it felt like it:

```python
from zerene.latency.models import DeterministicLatency, StochasticLatency
from zerene.latency.gateway import LatencyGateway
from zerene.models import OrderEvent, EventType

# Configure 4-hop network transit delays with Gaussian jitter
gateway = LatencyGateway(
    net_in_model=StochasticLatency("normal", mean_seconds=0.002, std_seconds=0.0002),
    gateway_model=DeterministicLatency(0.0001),
    engine_model=DeterministicLatency(0.00005),
    net_out_model=StochasticLatency("normal", mean_seconds=0.002, std_seconds=0.0002),
)

# Push inbound order submission event into the gateway
ev = OrderEvent(event_id="EV1", event_type=EventType.ORDER_SUBMIT, timestamp=1.0, symbol="BTC-USD")
gateway.submit_inbound(ev)

# Advance clock to 1.003s and pop packets that have finished network transit
due_events = gateway.pop_due_inbound(current_time=1.003)
for due_ev in due_events:
    print(f"Event {due_ev.event_id} arrived at matching engine at t={due_ev.timestamp:.5f}s")
```

---

## 6. Real-Time Risk Engine & Automated Kill-Switch

`RiskEngine` tracks participant limits, gross/net exposure, and drawdown using $O(1)$ incremental counters (`running_gross_exposure`, `cached_unrealized_pnl`). Why? Because looping over `self.positions.items()` every time you validate an order is a great way to self-DDOS your own matching engine during a market crash.

When drawdown limits breach, our automated kill-switch fires priority cancellation commands across the gateway to purge all resting quotes instantly—saving your account before the margin department calls your personal cell phone:

```python
from zerene.risk.limits import RiskLimits
from zerene.risk.engine import RiskEngine
from zerene.models import Order, Side, OrderType

risk_engine = RiskEngine()

# Configure strict participant limits
limits = RiskLimits(
    max_position_per_symbol=50.0,
    max_gross_exposure=500_000.0,
    max_drawdown_pct=0.10,        # 10% peak-to-trough drawdown trips the automated kill switch!
    max_daily_loss=25_000.0
)

state = risk_engine.register_participant("DESK_ALPHA", initial_capital=250_000.0, limits=limits)

# Pre-trade validation happens in pure O(1) without looping dictionary positions!
order = Order(order_id="O1", client_order_id="C1", symbol="BTC-USD", side=Side.BUY, order_type=OrderType.LIMIT, price=60000.0, quantity=10.0, owner_id="DESK_ALPHA")
is_valid, reason = risk_engine.validate_order(order)
if not is_valid:
    print(f"Order rejected by risk engine: {reason}")
```

---

## 7. Training RL Agents with Gymnasium (`RLTradingEnvironment`)

`RLTradingEnvironment` provides a standard `reset()`, `step(action)` Gymnasium-compatible API interface. When your quantitative RL agent executes an action, `env.step(action)` advances `MarketSimulator.step(1)` directly under the hood! That means your neural network trains against real background Poisson liquidity, multi-hop latency, and resting order book dynamics—not a fantasy spreadsheet:

```python
import numpy as np
from zerene.strategies.rl_env import RLTradingEnvironment

# 1. Initialize RL environment with isolated seed and quadratic Avellaneda holding cost penalty
env = RLTradingEnvironment(
    symbol="BTC-USD",
    max_steps=500,
    risk_penalty_coeff=0.05,
    seed=42
)

# 2. Reset environment to get initial observation state vector:
# obs = [mid_price, spread, imbalance, inventory, realized_pnl, volatility_estimate]
obs, info = env.reset(seed=42)
print(f"Initial Obs: {obs}")

# 3. Training / Rollout Loop
for step_idx in range(10):
    # Action Space (Discrete 5):
    # 0: Hold | 1: Buy Limit at Bid | 2: Sell Limit at Ask | 3: Buy Market | 4: Sell Market
    action = np.random.choice([0, 1, 2])
    
    obs, reward, terminated, truncated, info = env.step(action)
    print(f"Step {step_idx} | Action: {action} | Reward: {reward:.4f} | Inv: {info['inventory']}")
    
    if terminated or truncated:
        obs, info = env.reset()
```

---

## 8. Simulating Macro Shocks (Flash Crashes & News Surprises)

Want to test if your quantitative RL agent or market maker has actual diamond hands or if it liquidates your entire account when Elon Musk tweets a single emoji? Use `MarketSimulator` shock injectors to drop a massive sell cascade or instant quote shift straight onto the book:

```python
from zerene.exchange.venue import ExchangeVenue
from zerene.simulator.market_sim import MarketSimulator

exchange = ExchangeVenue("ZERENE-SHOCKS", symbols=["ETH-USD"])
sim = MarketSimulator(exchange, time_step=1.0)

# Advance 50 steps calmly
sim.step(50)

# Inject a Flash Crash: massive aggressive market sell order (e.g. 500 units dumping mid price by 15%)
sim.inject_flash_crash("ETH-USD", drop_pct=0.15)
sim.step(10)  # Watch resting quotes get obliterated and volatility regime shift to CRISIS!

# Inject a Macro News Shock: instant 5% price jump and order book quote shift
sim.inject_news_shock("ETH-USD", price_jump_pct=0.05)
sim.step(10)
```

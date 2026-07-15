# Contributing to ZERENE 🤝🏛️

So you want to contribute to **ZERENE**? First of all, we're genuinely stoked. Welcome aboard. Second of all, we need to have *the talk*.

We maintain an unflinching, battle-tested standard of institutional market microstructure discipline here. We blend old-school engineering rigor with modern, high-speed execution design. If your pull request introduces a slow Python garbage collection spike, peeks across wire boundaries, or breaks fixed-point integer precision, your PR will not just get rejected—it will be printed out and framed on our Wall of Shame right between "the intern who called `gc.collect()` inside the matching loop" and "the guy who used `time.sleep()` as a rate limiter."

Read these rules carefully before submitting your PR. We don't bite. But our code review does.

---

## The 6 Golden Rules of ZERENE Engineering 🏆

### 1. Zero-Allocation Pooling ONLY (`pools.py`)
**Do not instantiate new `OrderNode`, `Order`, `Trade`, or `OrderEvent` objects inside high-frequency execution loops.**
If we see `order = Order(...)` or `node = OrderNode(...)` instantiated right inside a hot matching engine loop in your Pull Request, we will close your PR faster than a risk desk liquidating an over-leveraged intern who just YOLO'd the entire book into illiquid options expiring tomorrow. Python heap allocations inside matching loops trigger `gc.collect()` pauses that destroy throughput. The garbage collector doesn't know what a limit order is, and frankly, it doesn't care. It will pause your engine mid-fill to free 64 bytes of a temporary string. It has no respect for your P&L.
* **DO**: Always acquire objects from `GLOBAL_ORDER_POOL.acquire(...)`, `GLOBAL_NODE_POOL.acquire(...)`, `GLOBAL_TRADE_POOL.acquire(...)`, or `GLOBAL_EVENT_POOL.acquire(...)`.
* **DO**: Release recycled objects back to their respective pools (`release()`) when their lifecycle terminates so the pool stays full.

### 2. Respect the `recycle_epoch` Guard
Every pool-managed object carries a `uint32` `recycle_epoch` tracking how many times it has been recycled.
* Never hold onto raw memory references of `OrderNode` or `Order` across asynchronous steps if they could have been cancelled/recycled.
* If you try to mutate a node after it's been returned to the pool, our generation guard will throw a stale reference exception right in your face. Don't try to resurrect the dead; this is a quantitative exchange simulator, not *Pet Sematary*. Sometimes dead orders should stay dead. That's literally what cancellation means.
* If you must verify node validity, check `if node.pool_id == expected_id and node.recycle_epoch == expected_epoch`.

### 3. Fixed-Point Integer Pricing (`10,000` Scale)
**Never use floating-point numbers (`float`) as keys in `SortedList` or B-Trees inside `orderbook/book.py` or `level.py`.**
If you try to shove a `float` into `level.py` or use `price == 100.0` inside internal order book indexing, our CI won't just fail—it will silently judge you the way your computer science professor judged you when you said `0.1 + 0.2 == 0.3` evaluates to `True`. (It doesn't. It never has. It never will. This is the hill we die on.)
* All internal order book prices are exact integers (`int(round(price * 10000))`).
* All node deletions use exact `internal_id` (`uint64`) mapping for $O(1)$ lookup without string hashing overhead.
* Convert from float at the venue entry boundary and back to float strictly for external reporting (`TickDict` / `OrderBookSnapshot`).

### 4. Strict Causality Across Wire Boundaries
**Never let an execution algorithm, Smart Order Router (SOR), or trading strategy peek directly into live `engine.order_book` internal structures.**
If your execution algorithm accesses `venue.engine.order_book._bids` directly because *"it makes the code simpler"*, please step away from the keyboard, brew yourself a cup of tea, and reflect on your choices. Peeking into live exchange order books before routing is illegal across every major financial jurisdiction, and it is illegal in this repository. We can't send you to jail, but we can send you to the shadow realm of rejected PRs, which is arguably worse for your GitHub contribution graph.
* All external decisions **MUST** consume immutable `OrderBookSnapshot` structures (`snap.bids`, `snap.asks`).
* If you need depth or Level II/III order book visibility in a strategy or router, pull it across the wire using `OrderBookSnapshot.from_book()` or request it via `ExchangeVenue.get_order_book_snapshot()`. You consume data over the wire or you stay blind.

### 5. Isolated `numpy.random.Generator` State
**Never call global `import random` (`random.random()`, `random.uniform()`) or `np.random.seed()` across components.**
If you call `import random` or `np.random.seed(42)` globally inside a strategy or simulator component, you just poisoned every other agent's Monte Carlo rollout and ruined benchmark reproducibility across the entire platform. Global RNG state is the secondhand smoke of quantitative computing. You might not notice the damage immediately, but six months later someone's RL agent is converging to a policy that only works on Tuesdays and nobody can figure out why. We will find out, and your code will be exiled to the `.trash/` directory where global state belongs.
* Every stochastic generator (`SyntheticFlowGenerator`, `MarketSimulator`, `RLTradingEnvironment`) must maintain its own isolated instance: `self.rng = np.random.default_rng(seed)`.
* This ensures 100% deterministic reproducibility across unit tests and RL training rollouts without cross-component seed contamination.

### 6. $O(1)$ Pre-Trade Risk Checks
**Never introduce an $O(N)$ dictionary loop (`for symbol, pos in self.positions.items():`) inside `RiskEngine.validate_order()`.**
When a quantitative market maker quotes 50 options across 5 venues, executing an $O(N)$ dictionary loop during pre-trade check means your risk validation takes longer than the actual trade matching. That is a self-inflicted denial-of-service attack against your own venue. You are the threat your own risk system was supposed to protect against. Think about that.
* All pre-trade exposure checks must execute in $O(1)$ time by reading `running_gross_exposure`, `running_net_exposure`, or `cached_unrealized_pnl` from `ParticipantRiskState`.
* If you modify position maps directly in tests or scripts, rely on the `PositionDict` dirty-flag mechanics (`_dirty = True`) to trigger `_sync_exposures()` before validation.

---

## Testing & Verification Checklist 🧪

Before submitting any Pull Request, you must verify that the entire institutional test suite passes with zero regressions:

```bash
# Run full verbose test suite
pytest -v tests/
```

Make sure your additions:
1. Come with dedicated unit tests under `tests/`.
2. Execute in under 2 seconds total across the entire suite (`pytest` currently runs 29 tests in ~0.9s—if your PR slows that down to 15 seconds, we will ask you what crypto mining script you hid in `conftest.py`, and also why your test fixtures are importing `tensorflow` for a matching engine).
3. Keep clean formatting and clear docstrings explaining institutional trade-offs.

---

## Pull Request Submission

Submit your PR directly to **[ak495867/zerene](https://github.com/ak495867/zerene)** with a clear breakdown:
* **Diagnosis/Context**: Why is this change needed? ("I felt like it" is not a valid reason. "The matching engine was producing fills at prices that violate thermodynamics" is.)
* **Microstructure Impact**: How does it impact latency, memory hygiene, or causality?
* **Verification**: Attach the clean `pytest` output confirming all tests pass.
* **Vibe Check**: Does your code spark joy in a senior quant engineer, or does it spark a 45-minute Slack thread about why we can't have nice things?

Let's build the cleanest, fastest open-source quantitative research platform on GitHub together. One PR at a time. Zero floats at a time. 🚀

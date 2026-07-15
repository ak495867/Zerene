"""
Master Discrete-Event Market Simulator.
Conforms to ZERENE architecture.
Supports trading sessions, circuit breakers, volatility regimes, flash crashes, and random news shocks.
Uses isolated `numpy.random.Generator` and vectorized background flow generation.
"""

import heapq
import numpy as np
import uuid
from enum import Enum
from typing import List, Dict, Optional, Any
from zerene.models import Order, Side, OrderType, OrderEvent, EventType
from zerene.pools import GLOBAL_EVENT_POOL, GLOBAL_ORDER_POOL
from zerene.exchange.venue import ExchangeVenue
from zerene.strategies.base import Strategy
from zerene.simulator.events import SimulationEvent, SimEventType


class TradingSession(Enum):
    PRE_MARKET = "PRE_MARKET"
    CONTINUOUS = "CONTINUOUS"
    AUCTION = "AUCTION"
    POST_MARKET = "POST_MARKET"
    HALTED = "HALTED"


class VolatilityRegime(Enum):
    CALM = "CALM"  # Low volatility
    NORMAL = "NORMAL"  # Baseline volatility
    HIGH_VOL = "HIGH_VOL"  # High volatility / economic data release
    CRISIS = "CRISIS"  # Extreme market distress / liquidation cascades


class MarketSimulator:
    """
    Master Discrete-Event Simulation Loop.
    Advances simulation clock deterministically via min-heap event processing.
    Injects synthetic background order flow and structural market events using vectorized isolated RNG.
    """

    def __init__(
        self,
        exchange: ExchangeVenue,
        initial_time: float = 0.0,
        time_step: float = 1.0,  # Seconds per step/tick
        poisson_rate: float = 5.0,  # Mean background orders arriving per second
        seed: Optional[int] = None,
    ):
        self.exchange = exchange
        self.current_time = initial_time
        self.time_step = time_step
        self.poisson_rate = poisson_rate
        self.rng = np.random.default_rng(seed)
        self.event_queue: List[SimulationEvent] = []
        self.strategies: List[Strategy] = []
        self.session: TradingSession = TradingSession.CONTINUOUS
        self.regime: VolatilityRegime = VolatilityRegime.NORMAL
        self.circuit_breaker_active: bool = False
        self.circuit_breaker_until: float = 0.0
        self.circuit_breaker_threshold: float = 0.10  # 10% deviation triggers halt
        self.circuit_breaker_duration: float = 60.0  # Halt duration in seconds
        self._reference_prices: Dict[str, float] = {}
        self.step_count = 0
        self._sim_counter: int = 0

        # Inject initial baseline liquidity across all symbols
        for symbol in self.exchange.engines.keys():
            self._seed_initial_book(symbol)
            engine = self.exchange.engines[symbol]
            mid = engine.order_book.mid_price() or 100.0
            self._reference_prices[symbol] = mid

    def add_strategy(self, strategy: Strategy) -> None:
        self.strategies.append(strategy)

    def schedule_event(self, event: SimulationEvent) -> None:
        heapq.heappush(self.event_queue, event)

    def inject_flash_crash(self, symbol: str, drop_pct: float = 0.15) -> None:
        """Injects a massive aggressive market sell cascade to simulate a flash crash."""
        self.schedule_event(
            SimulationEvent(
                timestamp=self.current_time + 0.1,
                event_type=SimEventType.SHOCK_FLASH_CRASH,
                symbol=symbol,
                data={"drop_pct": drop_pct, "quantity": 500.0},
            )
        )

    def inject_news_shock(self, symbol: str, price_jump_pct: float = 0.05) -> None:
        """Injects a sudden macroeconomic news surprise."""
        self.schedule_event(
            SimulationEvent(
                timestamp=self.current_time + 0.1,
                event_type=SimEventType.SHOCK_NEWS,
                symbol=symbol,
                data={"jump_pct": price_jump_pct},
            )
        )

    def step(self, num_steps: int = 1) -> None:
        """Advances simulation clock by `num_steps` discrete intervals."""
        for _ in range(num_steps):
            self.step_count += 1
            self.current_time += self.time_step

            # Check circuit breaker expiration
            if (
                self.circuit_breaker_active
                and self.current_time >= self.circuit_breaker_until
            ):
                self.circuit_breaker_active = False
                self.session = TradingSession.CONTINUOUS

            if self.session == TradingSession.HALTED:
                continue

            # Process all scheduled events up to current_time
            while (
                self.event_queue and self.event_queue[0].timestamp <= self.current_time
            ):
                ev = heapq.heappop(self.event_queue)
                self._handle_event(ev)

            # Generate background Poisson liquidity and noise flow in vectorized batch
            for symbol in self.exchange.engines.keys():
                self._generate_background_flow(symbol)

            # Process due inbound events arriving from latency gateway
            due = self.exchange.latency_gateway.pop_due_inbound(self.current_time)
            for ev in due:
                if ev.order:
                    self.exchange.submit_order(ev.order)
                GLOBAL_EVENT_POOL.release(ev)

            # Notify strategies of periodic timer ticks and new snapshots
            for symbol in self.exchange.engines.keys():
                snapshot = self.exchange.get_order_book_snapshot(
                    symbol, self.current_time
                )
                if snapshot:
                    for strategy in self.strategies:
                        if symbol in strategy.symbols:
                            new_orders = strategy.on_market_data(
                                symbol, self.current_time, snapshot, self.exchange
                            )
                            for o in new_orders:
                                o.timestamp = self.current_time
                                ev = GLOBAL_EVENT_POOL.acquire(
                                    event_id=f"EV-{o.order_id}",
                                    event_type=EventType.ORDER_SUBMIT,
                                    timestamp=self.current_time,
                                    symbol=o.symbol,
                                )
                                ev.order = o
                                self.exchange.latency_gateway.submit_inbound(ev)

            for strategy in self.strategies:
                timer_orders = strategy.on_timer(self.current_time, self.exchange)
                for o in timer_orders:
                    o.timestamp = self.current_time
                    ev = GLOBAL_EVENT_POOL.acquire(
                        event_id=f"EV-{o.order_id}",
                        event_type=EventType.ORDER_SUBMIT,
                        timestamp=self.current_time,
                        symbol=o.symbol,
                    )
                    ev.order = o
                    self.exchange.latency_gateway.submit_inbound(ev)

            # Pop any orders that completed latency transit right within this step interval
            due_post = self.exchange.latency_gateway.pop_due_inbound(self.current_time)
            for ev in due_post:
                if ev.order:
                    self.exchange.submit_order(ev.order)
                GLOBAL_EVENT_POOL.release(ev)

            # Check for circuit breaker trigger condition (extreme price deviation from reference baseline)
            for symbol, engine in self.exchange.engines.items():
                if engine.last_trade_price:
                    ref_price = self._reference_prices.get(symbol)
                    if not ref_price or ref_price <= 0:
                        self._reference_prices[symbol] = engine.last_trade_price
                        continue
                    dev_pct = abs(engine.last_trade_price - ref_price) / ref_price
                    if dev_pct >= self.circuit_breaker_threshold:
                        self.circuit_breaker_active = True
                        self.circuit_breaker_until = (
                            self.current_time + self.circuit_breaker_duration
                        )
                        self.session = TradingSession.HALTED
                        break

    def get_analytics_report(self):
        """Generates performance report across all engines and strategies."""
        from zerene.analytics.report import AnalyticsReport

        return AnalyticsReport.from_simulation(self)

    def _handle_event(self, ev: SimulationEvent) -> None:
        if ev.event_type == SimEventType.SHOCK_FLASH_CRASH:
            # Execute large market sell orders
            qty = ev.data.get("quantity", 200.0)
            order = Order(
                order_id=f"CRASH-{uuid.uuid4().hex[:6].upper()}",
                client_order_id="C-CRASH",
                symbol=ev.symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=qty,
                timestamp=self.current_time,
                owner_id="FLASH_CRASH_SHOCK",
            )
            self.exchange.submit_order(order)
            self.regime = VolatilityRegime.CRISIS

        elif ev.event_type == SimEventType.SHOCK_NEWS:
            # Shift order book quotes aggressively
            jump = ev.data.get("jump_pct", 0.05)
            engine = self.exchange.engines.get(ev.symbol)
            if engine:
                mid = engine.order_book.mid_price() or 100.0
                new_mid = mid * (1.0 + jump)
                # Cancel existing best bids and asks and drop new shifted quotes
                for idx in range(1, 4):
                    self.exchange.submit_order(
                        Order(
                            order_id=f"NEWS-B-{idx}",
                            client_order_id="C-NEWS",
                            symbol=ev.symbol,
                            side=Side.BUY,
                            order_type=OrderType.LIMIT,
                            price=round(new_mid - idx * 0.1, 2),
                            quantity=10.0,
                            timestamp=self.current_time,
                            owner_id="NEWS_SHOCK",
                        )
                    )

        elif ev.event_type == SimEventType.SESSION_CHANGE:
            new_session = ev.data.get("session")
            if isinstance(new_session, TradingSession):
                self.session = new_session

    def _generate_background_flow(self, symbol: str) -> None:
        engine = self.exchange.engines[symbol]
        book = engine.order_book
        mid = book.mid_price() or 100.0

        # Adjust intensity by volatility regime
        mult = 1.0
        if self.regime == VolatilityRegime.HIGH_VOL:
            mult = 2.5
        elif self.regime == VolatilityRegime.CRISIS:
            mult = 5.0

        # Sample number of background orders from vectorized Poisson generator
        num_orders = int(self.rng.poisson(self.poisson_rate * mult * self.time_step))
        if num_orders <= 0:
            return

        # Vectorized sampling of attributes across all background orders
        sides_r = self.rng.random(num_orders)
        type_r = self.rng.random(num_orders)
        offsets = self.rng.exponential(scale=0.5, size=num_orders)
        quantities = self.rng.uniform(0.1, 5.0, size=num_orders)

        for idx in range(num_orders):
            side = Side.BUY if sides_r[idx] < 0.5 else Side.SELL
            is_market = type_r[idx] < 0.2  # 20% market orders, 80% limit

            self._sim_counter += 1
            if is_market:
                qty = round(float(quantities[idx]), 2)
                order = GLOBAL_ORDER_POOL.acquire(
                    order_id=f"SIM-M-{self._sim_counter}",
                    client_order_id="C-SIM",
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=qty,
                    timestamp=self.current_time,
                    owner_id="NOISE_TRADER",
                )
            else:
                offset = float(offsets[idx])
                price = round(mid - offset if side == Side.BUY else mid + offset, 2)
                if price <= 0:
                    continue
                qty = round(float(quantities[idx]), 2)
                order = GLOBAL_ORDER_POOL.acquire(
                    order_id=f"SIM-L-{self._sim_counter}",
                    client_order_id="C-SIM",
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    quantity=qty,
                    timestamp=self.current_time,
                    owner_id="NOISE_TRADER",
                )
            ev = GLOBAL_EVENT_POOL.acquire(
                event_id=f"EV-{order.order_id}",
                event_type=EventType.ORDER_SUBMIT,
                timestamp=self.current_time,
                symbol=symbol,
            )
            ev.order = order
            self.exchange.latency_gateway.submit_inbound(ev)

    def _seed_initial_book(self, symbol: str) -> None:
        engine = self.exchange.engines[symbol]
        base_price = 100.0 if "BTC" not in symbol else 60000.0
        for i in range(1, 11):
            engine.process_order(
                Order(
                    order_id=f"SEED-B-{i}",
                    client_order_id=f"CS-{i}",
                    symbol=symbol,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    price=round(base_price - (i * (base_price * 0.0005)), 2),
                    quantity=10.0,
                    timestamp=0.0,
                    owner_id="SEED_LP",
                )
            )
            engine.process_order(
                Order(
                    order_id=f"SEED-A-{i}",
                    client_order_id=f"CS-{i}",
                    symbol=symbol,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    price=round(base_price + (i * (base_price * 0.0005)), 2),
                    quantity=10.0,
                    timestamp=0.0,
                    owner_id="SEED_LP",
                )
            )


def np_poisson(lam: float) -> int:
    """Fast Poisson sampling compatibility wrapper."""
    return int(np.random.poisson(lam)) if lam > 0 else 0

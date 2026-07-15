"""
Reinforcement Learning Trading Environment.
Provides an OpenAI Gym / Gymnasium compatible API interface (reset, step, observation, reward)
for training quantitative RL agents directly on ZERENE's matching engine and discrete-event `MarketSimulator`.
Uses isolated `numpy.random.Generator` state.
"""

import numpy as np
import uuid
from typing import Dict, Any, Tuple, Optional
from zerene.models import Order, Side, OrderType
from zerene.exchange.venue import ExchangeVenue
from zerene.pools import GLOBAL_ORDER_POOL
from zerene.simulator.market_sim import MarketSimulator


class RLTradingEnvironment:
    """
    OpenAI Gym compatible environment for training Reinforcement Learning trading agents.
    Observation space: [mid_price, spread, imbalance, inventory, realized_pnl, volatility_estimate]
    Action space:
      - Discrete(5): [0: Hold, 1: Buy Limit at Bid, 2: Sell Limit at Ask, 3: Buy Market, 4: Sell Market]
      - Or continuous action vectors for quoting spreads and sizes.
    """

    def __init__(
        self,
        symbol: str = "BTC-USD",
        exchange: Optional[ExchangeVenue] = None,
        max_steps: int = 1000,
        initial_inventory: float = 0.0,
        risk_penalty_coeff: float = 0.05,
        seed: Optional[int] = None,
        simulator: Optional[MarketSimulator] = None,
    ):
        self.symbol = symbol
        self.exchange = exchange or ExchangeVenue("ZERENE-RL", symbols=[symbol])
        self.max_steps = max_steps
        self.current_step = 0
        self.inventory = initial_inventory
        self.risk_penalty_coeff = risk_penalty_coeff
        self.prev_pnl = 0.0
        self.owner_id = "RL_AGENT_01"
        self.rng = np.random.default_rng(seed)
        self.simulator = simulator or MarketSimulator(
            self.exchange, time_step=1.0, poisson_rate=3.0, seed=seed
        )

    def reset(self, seed: Optional[int] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Resets the environment and returns the initial observation state vector."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.current_step = 0
        self.inventory = 0.0
        self.prev_pnl = 0.0
        self.exchange = ExchangeVenue("ZERENE-RL", symbols=[self.symbol])
        self.simulator = MarketSimulator(
            self.exchange, time_step=1.0, poisson_rate=3.0, seed=seed
        )

        # Inject initial baseline book liquidity
        self._inject_baseline_liquidity()
        obs = self._get_observation()
        return obs, {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Executes discrete agent action, advances simulation step via MarketSimulator, and returns:
        (observation, reward, terminated, truncated, info)
        """
        self.current_step += 1
        terminated = False
        truncated = self.current_step >= self.max_steps

        # Execute action
        book = self.exchange.engines[self.symbol].order_book
        bb = book.best_bid() or 100.0
        ba = book.best_ask() or 100.1
        mid = (bb + ba) / 2.0

        if action == 1:  # Buy Limit at Bid
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"RL-{self.current_step}-B",
                client_order_id=f"CRL-{self.current_step}-B",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=bb,
                quantity=1.0,
                timestamp=float(self.current_step),
                owner_id=self.owner_id,
            )
            self.exchange.submit_order(order)
        elif action == 2:  # Sell Limit at Ask
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"RL-{self.current_step}-S",
                client_order_id=f"CRL-{self.current_step}-S",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=ba,
                quantity=1.0,
                timestamp=float(self.current_step),
                owner_id=self.owner_id,
            )
            self.exchange.submit_order(order)
        elif action == 3:  # Buy Market
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"RL-{self.current_step}-BM",
                client_order_id=f"CRL-{self.current_step}-BM",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                price=0.0,
                quantity=1.0,
                timestamp=float(self.current_step),
                owner_id=self.owner_id,
            )
            _, trades = self.exchange.submit_order(order)
            self.inventory += sum(t.quantity for t in trades)
        elif action == 4:  # Sell Market
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"RL-{self.current_step}-SM",
                client_order_id=f"CRL-{self.current_step}-SM",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                price=0.0,
                quantity=1.0,
                timestamp=float(self.current_step),
                owner_id=self.owner_id,
            )
            _, trades = self.exchange.submit_order(order)
            self.inventory -= sum(t.quantity for t in trades)

        # Advance discrete-event simulation loop (background Poisson flow, latency gateway, event execution)
        self.simulator.step(1)

        # Reconcile inventory from any resting orders that got filled during simulator step
        state = self.exchange.risk_engine.states.get(self.owner_id)
        if state:
            self.inventory = state.positions.get(self.symbol, 0.0)
            current_pnl = state.realized_pnl + state.unrealized_pnl({self.symbol: mid})
        else:
            current_pnl = 0.0

        # Calculate reward: PnL delta minus inventory risk penalty (Avellaneda quadratic holding cost)
        pnl_delta = current_pnl - self.prev_pnl
        reward = pnl_delta - (self.risk_penalty_coeff * (self.inventory**2))
        self.prev_pnl = current_pnl

        # Check risk kill switch for termination
        if state and state.kill_switch_active:
            terminated = True
            reward -= 50.0  # Heavy penalty for blowing up account limits

        obs = self._get_observation()
        info = {
            "inventory": self.inventory,
            "realized_pnl": state.realized_pnl if state else 0.0,
            "reward": reward,
            "step": self.current_step,
        }
        return obs, reward, terminated, truncated, info

    def _get_observation(self) -> np.ndarray:
        book = self.exchange.engines[self.symbol].order_book
        mid = book.mid_price() or 100.0
        spread = book.spread() or 0.1
        imbalance = book.imbalance(levels=5)
        state = self.exchange.risk_engine.states.get(self.owner_id)
        pnl = state.realized_pnl if state else 0.0

        return np.array(
            [mid, spread, imbalance, self.inventory, pnl, 0.02], dtype=np.float32
        )

    def _inject_baseline_liquidity(self) -> None:
        engine = self.exchange.engines[self.symbol]
        for idx in range(1, 6):
            engine.process_order(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=f"BASE-B-{idx}",
                    client_order_id=f"CB-{idx}",
                    symbol=self.symbol,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    price=100.0 - (idx * 0.1),
                    quantity=5.0,
                    timestamp=0.0,
                    owner_id="BASE_LP",
                )
            )
            engine.process_order(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=f"BASE-A-{idx}",
                    client_order_id=f"CA-{idx}",
                    symbol=self.symbol,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    price=100.0 + (idx * 0.1),
                    quantity=5.0,
                    timestamp=0.0,
                    owner_id="BASE_LP",
                )
            )

    def _inject_noise_flow(self) -> None:
        book = self.exchange.engines[self.symbol].order_book
        mid = book.mid_price() or 100.0
        side = Side.BUY if self.rng.random() < 0.5 else Side.SELL
        is_market = (
            self.rng.random() < 0.35
        )  # 35% chance of aggressive market order taking resting liquidity

        if is_market:
            self.exchange.submit_order(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=f"NOISE-M-{uuid.uuid4().hex[:6]}",
                    client_order_id=f"CN-M-{uuid.uuid4().hex[:6]}",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    price=0.0,
                    quantity=round(float(self.rng.uniform(0.5, 2.0)), 2),
                    timestamp=float(self.current_step),
                    owner_id="NOISE_TRADER",
                )
            )
        else:
            price = round(mid + float(self.rng.uniform(-0.3, 0.3)), 2)
            self.exchange.submit_order(
                GLOBAL_ORDER_POOL.acquire(
                    order_id=f"NOISE-L-{uuid.uuid4().hex[:6]}",
                    client_order_id=f"CN-L-{uuid.uuid4().hex[:6]}",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    quantity=round(float(self.rng.uniform(0.5, 3.0)), 2),
                    timestamp=float(self.current_step),
                    owner_id="NOISE_TRADER",
                )
            )

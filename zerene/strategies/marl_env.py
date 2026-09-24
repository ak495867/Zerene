"""
Multi-Agent Reinforcement Learning (MARL) Market Simulation Environment.
Enables competitive multi-agent RL training (Market Makers vs Execution Algos vs Arbitrageurs)
with observation state vectors, multi-agent action mapping, and inventory-penalized PnL rewards.
"""

import numpy as np
from typing import Dict, List, Tuple, Any, Optional
from zerene.models import Order, Side, OrderType, OrderStatus
from zerene.exchange.venue import ExchangeVenue
from zerene.simulator.market_sim import MarketSimulator
from zerene.pools import GLOBAL_ORDER_POOL


class MultiAgentRLMarketEnv:
    """
    Competitive Multi-Agent RL Market Environment for ZERENE.
    Supports multiple concurrent agents placing orders, quoting, or sweeping liquidity.
    """

    def __init__(
        self,
        agent_ids: List[str],
        symbol: str = "BTC-USD",
        depth_levels: int = 5,
        max_steps: int = 200,
        seed: Optional[int] = None,
    ):
        self.agent_ids = agent_ids
        self.symbol = symbol
        self.depth_levels = depth_levels
        self.max_steps = max_steps
        self.seed = seed
        self.rng = np.random.default_rng(seed)

        self.exchange = ExchangeVenue("MARL-VENUE", symbols=[symbol])
        self.simulator = MarketSimulator(
            self.exchange, time_step=1.0, poisson_rate=5.0, seed=seed
        )
        self.current_step = 0
        self.prev_pnl: Dict[str, float] = {aid: 0.0 for aid in agent_ids}
        self.positions: Dict[str, float] = {aid: 0.0 for aid in agent_ids}

    def reset(self) -> Dict[str, np.ndarray]:
        """Resets the environment and returns initial observations for all agents."""
        self.exchange = ExchangeVenue("MARL-VENUE", symbols=[self.symbol])
        self.simulator = MarketSimulator(
            self.exchange, time_step=1.0, poisson_rate=5.0, seed=self.seed
        )
        self.current_step = 0
        self.prev_pnl = {aid: 0.0 for aid in self.agent_ids}
        self.positions = {aid: 0.0 for aid in self.agent_ids}

        # Warm up book with background trades
        self.simulator.step(10)
        return {aid: self._get_observation(aid) for aid in self.agent_ids}

    def step(self, actions: Dict[str, int]) -> Tuple[
        Dict[str, np.ndarray],
        Dict[str, float],
        Dict[str, bool],
        Dict[str, bool],
        Dict[str, Any],
    ]:
        """
        Executes one step in the environment for all agents.
        Actions per agent:
          0: Hold (no-op)
          1: Limit Buy at Best Bid
          2: Limit Sell at Best Ask
          3: Market Buy 1.0 unit
          4: Market Sell 1.0 unit
          5: Cancel all quotes
        """
        self.current_step += 1

        # Process agent actions
        for aid, act in actions.items():
            self._apply_agent_action(aid, act)

        # Advance background market step
        self.simulator.step(1)

        # Update position and PnL metrics
        observations = {}
        rewards = {}
        terminateds = {}
        truncateds = {}

        is_done = self.current_step >= self.max_steps

        for aid in self.agent_ids:
            obs = self._get_observation(aid)
            observations[aid] = obs

            # Calculate PnL and inventory penalty
            engine = self.exchange.engines[self.symbol]
            mid = engine.order_book.mid_price() or 100.0

            pos = self.positions[aid]
            curr_pnl = self.prev_pnl[aid]
            unrealized = pos * mid
            total_equity = curr_pnl + unrealized

            # Reward delta PnL minus inventory variance penalty
            r = (total_equity - self.prev_pnl[aid]) - 0.01 * (pos**2)
            rewards[aid] = float(r)
            self.prev_pnl[aid] = total_equity

            terminateds[aid] = is_done
            truncateds[aid] = False

        info = {"step": self.current_step}
        return observations, rewards, terminateds, truncateds, info

    def _apply_agent_action(self, agent_id: str, action: int) -> None:
        engine = self.exchange.engines[self.symbol]
        bb = engine.order_book.best_bid() or 100.0
        ba = engine.order_book.best_ask() or 100.1

        if action == 1:  # Limit Buy
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"MARL-B-{agent_id}-{self.current_step}",
                client_order_id="C-MARL",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=round(bb, 2),
                quantity=1.0,
                timestamp=self.simulator.current_time,
                owner_id=agent_id,
            )
            self.exchange.submit_order(order)
        elif action == 2:  # Limit Sell
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"MARL-A-{agent_id}-{self.current_step}",
                client_order_id="C-MARL",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=round(ba, 2),
                quantity=1.0,
                timestamp=self.simulator.current_time,
                owner_id=agent_id,
            )
            self.exchange.submit_order(order)
        elif action == 3:  # Market Buy
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"MARL-MB-{agent_id}-{self.current_step}",
                client_order_id="C-MARL",
                symbol=self.symbol,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=1.0,
                timestamp=self.simulator.current_time,
                owner_id=agent_id,
            )
            _, trades = self.exchange.submit_order(order)
            for t in trades:
                self.positions[agent_id] += t.quantity
                self.prev_pnl[agent_id] -= t.quantity * t.price
        elif action == 4:  # Market Sell
            order = GLOBAL_ORDER_POOL.acquire(
                order_id=f"MARL-MS-{agent_id}-{self.current_step}",
                client_order_id="C-MARL",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=1.0,
                timestamp=self.simulator.current_time,
                owner_id=agent_id,
            )
            _, trades = self.exchange.submit_order(order)
            for t in trades:
                self.positions[agent_id] -= t.quantity
                self.prev_pnl[agent_id] += t.quantity * t.price
        elif action == 5:  # Cancel All
            self.exchange.cancel_all_for_participant(agent_id)

    def _get_observation(self, agent_id: str) -> np.ndarray:
        """Encodes L2 orderbook depth and agent state into flat feature vector."""
        engine = self.exchange.engines[self.symbol]
        bids_depth, asks_depth = engine.order_book.get_depth(self.depth_levels)
        mid = engine.order_book.mid_price() or 100.0
        spread = engine.order_book.spread() or 0.01

        obs = []
        # Normalized bid depths
        for i in range(self.depth_levels):
            if i < len(bids_depth):
                obs.append((bids_depth[i][0] - mid) / mid)
                obs.append(bids_depth[i][1])
            else:
                obs.append(0.0)
                obs.append(0.0)

        # Normalized ask depths
        for i in range(self.depth_levels):
            if i < len(asks_depth):
                obs.append((asks_depth[i][0] - mid) / mid)
                obs.append(asks_depth[i][1])
            else:
                obs.append(0.0)
                obs.append(0.0)

        # Agent state
        obs.append(self.positions.get(agent_id, 0.0))
        obs.append(spread / mid)

        return np.array(obs, dtype=np.float32)

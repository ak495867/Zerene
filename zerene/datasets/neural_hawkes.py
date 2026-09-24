"""
Neural Hawkes Process Order Flow Surrogate Generator for ZERENE.
Implements non-linear Hawkes intensity function:
lambda_k(t) = Softplus(mu_k + sum_j alpha_jk * exp(-beta_jk * (t - t_j)))
with isolated numpy random generator state and vectorized sampling.
"""

import numpy as np
from typing import List, Optional
from zerene.models import Order, Side, OrderType
from zerene.pools import GLOBAL_ORDER_POOL


def softplus(x: np.ndarray) -> np.ndarray:
    """Non-linear activation function guaranteeing strictly positive intensity."""
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0)


class NeuralHawkesGenerator:
    """
    Neural Hawkes Process Order Flow Generator.
    Models multi-dimensional non-linear order flow dynamics.
    """

    def __init__(
        self,
        symbol: str = "BTC-USD",
        num_event_types: int = 4,  # [Limit Buy, Limit Sell, Market Buy, Market Sell]
        mu: Optional[np.ndarray] = None,
        alpha: Optional[np.ndarray] = None,
        beta: Optional[np.ndarray] = None,
        seed: Optional[int] = None,
    ):
        self.symbol = symbol
        self.K = num_event_types
        self.rng = np.random.default_rng(seed)

        # Baseline intensities (mu)
        self.mu = mu if mu is not None else np.full(self.K, 2.0)
        # Excitation matrix (alpha K x K)
        self.alpha = alpha if alpha is not None else np.full((self.K, self.K), 0.3)
        # Decay rates matrix (beta K x K)
        self.beta = beta if beta is not None else np.full((self.K, self.K), 1.2)

        self.last_event_time = 0.0
        self.history_times: List[float] = []
        self.history_types: List[int] = []
        self._order_counter = 0

    def compute_intensities(self, current_time: float) -> np.ndarray:
        """Computes current intensity vector across all event types in O(history)."""
        intensities = self.mu.copy()
        for t_k, type_k in zip(self.history_times, self.history_types):
            dt = current_time - t_k
            if dt > 10.0:  # Truncate old history beyond decay horizon
                continue
            decay = np.exp(-self.beta[:, type_k] * dt)
            intensities += self.alpha[:, type_k] * decay

        return softplus(intensities)

    def generate_step(
        self, current_time: float, dt: float, mid_price: float = 100.0
    ) -> List[Order]:
        """Generates synthetic orders over interval `dt` via Neural Hawkes intensity sampling."""
        orders: List[Order] = []
        if dt <= 0:
            return orders

        intensities = self.compute_intensities(current_time)
        events_count = self.rng.poisson(intensities * dt)
        total_events = int(np.sum(events_count))

        if total_events <= 0:
            return orders

        # Generate orders based on sampled counts
        for k in range(self.K):
            c = events_count[k]
            for _ in range(c):
                self._order_counter += 1
                self.history_times.append(current_time)
                self.history_types.append(k)

                # Prune history buffer
                if len(self.history_times) > 200:
                    self.history_times.pop(0)
                    self.history_types.pop(0)

                # Map event type k: 0=Limit Buy, 1=Limit Sell, 2=Market Buy, 3=Market Sell
                side = Side.BUY if k in (0, 2) else Side.SELL
                is_market = k in (2, 3)

                if is_market:
                    orders.append(
                        GLOBAL_ORDER_POOL.acquire(
                            order_id=f"NH-M-{self._order_counter}",
                            client_order_id="C-NH",
                            symbol=self.symbol,
                            side=side,
                            order_type=OrderType.MARKET,
                            price=0.0,
                            quantity=round(float(self.rng.uniform(0.5, 3.0)), 2),
                            timestamp=current_time,
                            owner_id="NEURAL_HAWKES",
                        )
                    )
                else:
                    offset = float(self.rng.exponential(0.3))
                    p = (
                        round(mid_price - max(0.01, offset), 2)
                        if side == Side.BUY
                        else round(mid_price + max(0.01, offset), 2)
                    )
                    if p > 0:
                        orders.append(
                            GLOBAL_ORDER_POOL.acquire(
                                order_id=f"NH-L-{self._order_counter}",
                                client_order_id="C-NH",
                                symbol=self.symbol,
                                side=side,
                                order_type=OrderType.LIMIT,
                                price=p,
                                quantity=round(float(self.rng.uniform(0.5, 3.0)), 2),
                                timestamp=current_time,
                                owner_id="NEURAL_HAWKES",
                            )
                        )

        return orders

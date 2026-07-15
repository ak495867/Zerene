"""
Multi-Kernel Calibrated Hawkes Process & Order Flow Imbalance (OFI) conditioned synthetic order flow generator.
Separates self-excitation (market order -> more market orders) and cross-excitation (aggressive sweep -> cancellation waves).
Uses isolated `numpy.random.Generator` state and vectorized sampling for deterministic, high-speed execution.
"""

import math
import numpy as np
from typing import List, Optional
from zerene.models import Order, Side, OrderType
from zerene.pools import GLOBAL_ORDER_POOL


class SyntheticFlowGenerator:
    """
    Multi-Kernel Hawkes Process flow generator with Order Flow Imbalance (OFI) conditioning.
    Models both self-excitation (`alpha_self`) and cross-excitation (`alpha_cross`),
    as well as dynamic quote skewing based on high-frequency OFI signals.
    """
    def __init__(
        self,
        symbol: str = "BTC-USD",
        base_rate_buy: float = 8.0,
        base_rate_sell: float = 8.0,
        hawkes_alpha_self: float = 0.45,
        hawkes_alpha_cross: float = 0.25,
        hawkes_beta: float = 1.5,
        seed: Optional[int] = None,
    ):
        self.symbol = symbol
        self.mu_buy = base_rate_buy
        self.mu_sell = base_rate_sell
        self.alpha_self = hawkes_alpha_self
        self.alpha_cross = hawkes_alpha_cross
        self.beta = hawkes_beta
        self.rng = np.random.default_rng(seed)

        # Dynamic intensity states for buy and sell kernels
        self.intensity_buy = base_rate_buy
        self.intensity_sell = base_rate_sell
        self.last_event_time = 0.0

        # OFI conditioning state
        self.current_ofi = 0.0
        self._order_counter = 0

    def update_ofi(self, bid_vol_change: float, ask_vol_change: float) -> float:
        """
        Updates Order Flow Imbalance (OFI) signal:
        OFI = delta_bid_volume - delta_ask_volume
        Positive OFI indicates strong buying pressure; shifts buy intensity upward and skews pricing.
        """
        self.current_ofi = bid_vol_change - ask_vol_change
        return self.current_ofi

    def generate_batch(self, current_time: float, dt: float, mid_price: float = 100.0) -> List[Order]:
        """Generates a batch of synthetic orders across time interval `dt` governed by multi-kernel Hawkes + OFI."""
        orders: List[Order] = []
        if dt <= 0.0:
            return orders

        # Exponential decay of intensity since last event
        decay = math.exp(-self.beta * max(0.0, current_time - self.last_event_time))
        self.intensity_buy = self.mu_buy + (self.intensity_buy - self.mu_buy) * decay
        self.intensity_sell = self.mu_sell + (self.intensity_sell - self.mu_sell) * decay

        # Condition base intensity on OFI
        ofi_skew = max(-5.0, min(5.0, self.current_ofi * 0.1))
        eff_buy_rate = max(0.5, self.intensity_buy + ofi_skew)
        eff_sell_rate = max(0.5, self.intensity_sell - ofi_skew)

        # Vectorized Poisson sampling from isolated generator
        count_buy = int(self.rng.poisson(eff_buy_rate * dt))
        count_sell = int(self.rng.poisson(eff_sell_rate * dt))
        total_events = count_buy + count_sell

        if total_events <= 0:
            return orders

        # Pre-sample random variates in vectorized arrays for maximum speed
        market_rands = self.rng.random(total_events)
        offsets = self.rng.exponential(scale=0.5, size=total_events)
        quantities = self.rng.uniform(0.1, 5.0, size=total_events)

        for idx in range(total_events):
            is_buy = idx < count_buy
            side = Side.BUY if is_buy else Side.SELL

            # Apply self & cross excitation
            if is_buy:
                self.intensity_buy += self.alpha_self
                self.intensity_sell += self.alpha_cross
            else:
                self.intensity_sell += self.alpha_self
                self.intensity_buy += self.alpha_cross

            self.last_event_time = current_time

            # When OFI is strongly skewed toward one side, probability of aggressive market order increases
            market_prob = 0.15 + (0.10 if (is_buy and self.current_ofi > 0) or (not is_buy and self.current_ofi < 0) else 0.0)
            is_market = market_rands[idx] < market_prob

            if is_market:
                self._order_counter += 1
                orders.append(GLOBAL_ORDER_POOL.acquire(
                    order_id=f"SYN-M-{self._order_counter}",
                    client_order_id=f"C-SYN-{idx}",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    price=0.0,
                    quantity=round(float(quantities[idx]), 2),
                    timestamp=current_time,
                    owner_id="SYNTHETIC_FLOW",
                ))
            else:
                # Limit order placement relative to mid price skewed by OFI
                offset = float(offsets[idx])
                if is_buy:
                    # If OFI > 0, buy limits place closer to mid or inside spread
                    price = round(mid_price - max(0.01, offset - max(0.0, ofi_skew * 0.05)), 2)
                else:
                    price = round(mid_price + max(0.01, offset + min(0.0, ofi_skew * 0.05)), 2)

                if price <= 0:
                    continue

                self._order_counter += 1
                orders.append(GLOBAL_ORDER_POOL.acquire(
                    order_id=f"SYN-L-{self._order_counter}",
                    client_order_id=f"C-SYN-{idx}",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=price,
                    quantity=round(float(quantities[idx]), 2),
                    timestamp=current_time,
                    owner_id="SYNTHETIC_FLOW",
                ))

        return orders

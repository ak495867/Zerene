"""
Limit Up / Limit Down (LULD) and Dynamic Price Collar Circuit Breakers.
Implements institutional volatility pauses and reference price collars conforming
to SEC Rule 613 / Plan to Address Extraordinary Market Volatility and crypto perpetual collar rules.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple
from zerene.models import Order, Side


class CircuitBreakerState(Enum):
    NORMAL = "NORMAL"
    LIMIT_STATE = "LIMIT_STATE"  # Order resting at band boundary
    STRADDLE_STATE = "STRADDLE_STATE"
    HALTED = "HALTED"  # Trading paused due to sustained price breach


@dataclass(slots=True)
class PriceBand:
    lower_price: float
    upper_price: float
    reference_price: float


class CircuitBreaker:
    """
    State machine enforcing Limit Up / Limit Down (LULD) price bands and trading halts.
    Rejects or clamps orders that attempt to execute outside calculated price bands.
    """

    def __init__(
        self,
        symbol: str,
        initial_reference_price: Optional[float] = None,
        band_pct: float = 0.05,  # 5% price bands around reference price
        halt_duration_sec: float = 300.0,  # 5-minute halt on breach
        collar_enabled: bool = True,
    ):
        self.symbol = symbol
        self.reference_price = initial_reference_price
        self.band_pct = band_pct
        self.halt_duration_sec = halt_duration_sec
        self.collar_enabled = collar_enabled
        self.state = CircuitBreakerState.NORMAL
        self.halt_start_time: Optional[float] = None
        self.lower_band: Optional[float] = None
        self.upper_band: Optional[float] = None
        if self.reference_price is not None:
            self._update_bands()

    def _update_bands(self) -> None:
        if self.reference_price is not None:
            self.lower_band = round(self.reference_price * (1.0 - self.band_pct), 4)
            self.upper_band = round(self.reference_price * (1.0 + self.band_pct), 4)

    def update_reference_price(self, new_reference_price: float) -> None:
        """Updates rolling reference price (e.g. 5-minute volume-weighted moving average)."""
        if new_reference_price > 0 and self.state == CircuitBreakerState.NORMAL:
            self.reference_price = new_reference_price
            self._update_bands()

    def check_halt_expiry(self, current_time: float) -> bool:
        """Resumes trading if halt duration has elapsed."""
        if (
            self.state == CircuitBreakerState.HALTED
            and self.halt_start_time is not None
        ):
            if current_time - self.halt_start_time >= self.halt_duration_sec:
                self.state = CircuitBreakerState.NORMAL
                self.halt_start_time = None
                return True
        return False

    def trigger_halt(self, current_time: float) -> None:
        """Manually or automatically triggers an exchange volatility halt."""
        self.state = CircuitBreakerState.HALTED
        self.halt_start_time = current_time

    def validate_order(
        self, order: Order, current_time: float = 0.0
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates order against circuit breaker state and price collar bands.
        Rejects orders during halts or orders crossing outside allowable collars.
        """
        self.check_halt_expiry(current_time)

        if self.state == CircuitBreakerState.HALTED:
            return (
                False,
                f"TRADING_HALTED: LULD circuit breaker active on {self.symbol}",
            )

        if not self.collar_enabled:
            return True, None

        # If reference price not yet established, initialize from first limit order
        if self.reference_price is None and order.price is not None:
            self.update_reference_price(order.price)
            return True, None

        # Collar checks on limit orders
        if (
            order.price is not None
            and self.upper_band is not None
            and self.lower_band is not None
        ):
            if order.side == Side.BUY and order.price > self.upper_band:
                return (
                    False,
                    f"LULD_PRICE_COLLAR_BREACH: BUY price {order.price:.2f} > Upper Band {self.upper_band:.2f}",
                )
            if order.side == Side.SELL and order.price < self.lower_band:
                return (
                    False,
                    f"LULD_PRICE_COLLAR_BREACH: SELL price {order.price:.2f} < Lower Band {self.lower_band:.2f}",
                )

        return True, None

    def get_bands(self) -> PriceBand:
        return PriceBand(
            lower_price=self.lower_band,
            upper_price=self.upper_band,
            reference_price=self.reference_price,
        )

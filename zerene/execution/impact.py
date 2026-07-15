"""
Market impact models (Almgren-Chriss, Kyle's Lambda, Square Root Impact).
"""

import math
from abc import ABC, abstractmethod


class MarketImpactModel(ABC):
    """Abstract base class for calculating price impact of execution tranches."""

    @abstractmethod
    def calculate_temporary_impact(self, quantity: float, volume_rate: float) -> float:
        """Returns price slippage/impact per unit traded for temporary order imbalance."""
        pass

    @abstractmethod
    def calculate_permanent_impact(
        self, quantity: float, total_daily_volume: float
    ) -> float:
        """Returns permanent baseline shift in mid price due to trade execution."""
        pass


class AlmgrenChrissImpact(MarketImpactModel):
    """
    Almgren-Chriss market impact model.
    Temporary impact proportional to execution speed (rate v).
    Permanent impact proportional to total quantity traded (q).
    """

    def __init__(self, eta: float = 0.01, gamma: float = 0.001):
        self.eta = eta  # Temporary impact coefficient
        self.gamma = gamma  # Permanent impact coefficient

    def calculate_temporary_impact(self, quantity: float, volume_rate: float) -> float:
        return self.eta * volume_rate

    def calculate_permanent_impact(
        self, quantity: float, total_daily_volume: float = 1e6
    ) -> float:
        return self.gamma * quantity


class KylesLambdaImpact(MarketImpactModel):
    """
    Kyle's Lambda impact model.
    Slippage linearly related to order imbalance and lambda parameter.
    """

    def __init__(self, kyle_lambda: float = 0.0005):
        self.kyle_lambda = kyle_lambda

    def calculate_temporary_impact(self, quantity: float, volume_rate: float) -> float:
        return self.kyle_lambda * abs(quantity)

    def calculate_permanent_impact(
        self, quantity: float, total_daily_volume: float = 1e6
    ) -> float:
        return 0.5 * self.kyle_lambda * abs(quantity)


class SquareRootImpact(MarketImpactModel):
    """
    Square-root price impact law (frequently observed across equity and crypto markets).
    Slippage proportional to sigma * sqrt(Q / V).
    """

    def __init__(self, daily_volatility: float = 0.02, scaling_factor: float = 0.5):
        self.sigma = daily_volatility
        self.Y = scaling_factor

    def calculate_temporary_impact(self, quantity: float, volume_rate: float) -> float:
        if volume_rate <= 1e-9:
            return 0.0
        return self.Y * self.sigma * math.sqrt(abs(quantity) / max(1.0, volume_rate))

    def calculate_permanent_impact(
        self, quantity: float, total_daily_volume: float = 1e6
    ) -> float:
        if total_daily_volume <= 1e-9:
            return 0.0
        return 0.3 * self.Y * self.sigma * math.sqrt(abs(quantity) / total_daily_volume)

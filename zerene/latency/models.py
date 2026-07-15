"""
Deterministic and Stochastic Latency models conforming to RFC-003.
"""

import random
import math
from abc import ABC, abstractmethod
from typing import Optional


class LatencyModel(ABC):
    """Abstract base class for multi-hop latency distribution models."""
    @abstractmethod
    def sample(self) -> float:
        """Returns sampled latency in seconds."""
        pass

    @abstractmethod
    def should_drop(self) -> bool:
        """Returns True if the packet/message is lost due to network degradation."""
        pass


class DeterministicLatency(LatencyModel):
    """
    Fixed deterministic latency profile across all hops.
    """
    def __init__(self, delay_seconds: float = 0.001, packet_drop_rate: float = 0.0):
        self.delay = max(0.0, delay_seconds)
        self.drop_rate = max(0.0, min(1.0, packet_drop_rate))

    def sample(self) -> float:
        return self.delay

    def should_drop(self) -> bool:
        if self.drop_rate <= 0.0:
            return False
        return random.random() < self.drop_rate


class StochasticLatency(LatencyModel):
    """
    Stochastic institutional latency profile (Normal, Exponential, Lognormal, Pareto).
    """
    def __init__(
        self,
        distribution: str = "normal",
        mean_seconds: float = 0.002,
        std_seconds: float = 0.0005,
        min_seconds: float = 0.0001,
        packet_drop_rate: float = 0.0,
    ):
        self.distribution = distribution.lower()
        self.mean = mean_seconds
        self.std = std_seconds
        self.min_latency = min_seconds
        self.drop_rate = max(0.0, min(1.0, packet_drop_rate))

    def sample(self) -> float:
        if self.distribution == "normal":
            val = random.gauss(self.mean, self.std)
        elif self.distribution == "exponential":
            val = self.min_latency + random.expovariate(1.0 / max(1e-9, self.mean - self.min_latency))
        elif self.distribution == "lognormal":
            # Convert mean and std to lognormal mu and sigma
            variance = self.std ** 2
            mean = max(1e-9, self.mean)
            sigma2 = math.log(1.0 + (variance / (mean ** 2)))
            mu = math.log(mean) - 0.5 * sigma2
            val = random.lognormvariate(mu, math.sqrt(sigma2))
        elif self.distribution == "pareto":
            alpha = 2.5
            # paretovariate(2.5) has mean 2.5 / 1.5 = 1.6667 (excess over 1 is 0.6667)
            excess = random.paretovariate(alpha) - 1.0
            scale = (max(1e-9, self.mean - self.min_latency)) / 0.6666666666666666
            val = self.min_latency + (excess * scale)
        else:
            val = self.mean

        return max(self.min_latency, val)

    def should_drop(self) -> bool:
        if self.drop_rate <= 0.0:
            return False
        return random.random() < self.drop_rate

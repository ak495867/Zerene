"""
Latency subpackage conforming to RFC-003.
"""
from .models import LatencyModel, DeterministicLatency, StochasticLatency
from .gateway import LatencyGateway

__all__ = ["LatencyModel", "DeterministicLatency", "StochasticLatency", "LatencyGateway"]

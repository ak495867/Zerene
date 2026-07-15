"""
Discrete event structures for the Master Simulation Loop.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from zerene.models import Order


class SimEventType(Enum):
    TIMER_TICK = auto()
    ORDER_ARRIVAL = auto()
    ORDER_CANCEL = auto()
    SHOCK_NEWS = auto()
    SHOCK_FLASH_CRASH = auto()
    SESSION_CHANGE = auto()
    REGIME_CHANGE = auto()


@dataclass(slots=True)
class SimulationEvent:
    timestamp: float
    event_type: SimEventType
    symbol: str = ""
    order: Optional[Order] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: "SimulationEvent") -> bool:
        return self.timestamp < other.timestamp

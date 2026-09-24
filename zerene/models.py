"""
Core data models, enums, and event structures for ZERENE.
Optimized with __slots__ and strict type definitions for institutional-grade performance.
"""

import math
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self == Side.BUY else Side.BUY


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "POST_ONLY"
    REDUCE_ONLY = "REDUCE_ONLY"
    ICEBERG = "ICEBERG"
    HIDDEN = "HIDDEN"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    REPLACE = "REPLACE"
    MIDPOINT_PEG = "MIDPOINT_PEG"
    PRIMARY_PEG = "PRIMARY_PEG"
    MARKET_PEG = "MARKET_PEG"


class OrderStatus(Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    TRIGGERED = "TRIGGERED"
    REPLACED = "REPLACED"


class TimeInForce(Enum):
    GTC = "GTC"  # Good-Til-Canceled
    IOC = "IOC"  # Immediate-or-Cancel
    FOK = "FOK"  # Fill-or-Kill
    GTD = "GTD"  # Good-Til-Date


_INTERNAL_ID_COUNTER: int = 0


def get_next_internal_id() -> int:
    """Generates monotonically increasing sequence integer IDs for fast O(1) integer hashing in hot paths."""
    global _INTERNAL_ID_COUNTER
    _INTERNAL_ID_COUNTER += 1
    return _INTERNAL_ID_COUNTER


class STPMode(Enum):
    NONE = "NONE"
    CANCEL_NEWEST = "CANCEL_NEWEST"
    CANCEL_OLDEST = "CANCEL_OLDEST"
    DECREMENT_AND_CANCEL = "DECREMENT_AND_CANCEL"


@dataclass(slots=True)
class Order:
    """
    Core Order object representing a single participant request in ZERENE.
    Strictly tracks visible vs hidden tranches for institutional execution quality.
    """

    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    filled_quantity: float = 0.0
    display_quantity: Optional[float] = None  # Visible tranche for Iceberg
    hidden_quantity: float = 0.0  # Remaining hidden tranche for Iceberg/Hidden
    iceberg_slice: float = (
        0.0  # Recorded initial visible tranche size for precise replenishment
    )
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    stp_mode: STPMode = STPMode.NONE
    timestamp: float = 0.0  # Arrival or replenishment timestamp (nanoseconds/seconds)
    owner_id: str = "DEFAULT"
    status: OrderStatus = OrderStatus.NEW
    reject_reason: Optional[str] = None
    internal_id: int = 0
    recycle_epoch: int = 0
    _in_pool: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.internal_id == 0:
            self.internal_id = get_next_internal_id()
        # Initialize display and hidden quantities if not explicitly set
        if self.order_type == OrderType.ICEBERG:
            if self.display_quantity is None or self.display_quantity <= 0:
                self.display_quantity = self.quantity
            self.hidden_quantity = max(0.0, self.quantity - self.display_quantity)
            self.display_quantity = min(self.quantity, self.display_quantity)
            self.iceberg_slice = self.display_quantity
        elif self.order_type == OrderType.HIDDEN:
            self.display_quantity = 0.0
            self.hidden_quantity = self.quantity
            self.iceberg_slice = 0.0
        else:
            if self.display_quantity is None:
                self.display_quantity = self.quantity
            self.hidden_quantity = 0.0
            self.iceberg_slice = self.display_quantity

    def validate(self) -> Optional[str]:
        """Return a stable rejection reason for invalid external order input."""
        if not self.order_id or not self.client_order_id or not self.symbol:
            return "MISSING_ORDER_IDENTIFIERS"
        if not isinstance(self.side, Side) or not isinstance(
            self.order_type, OrderType
        ):
            return "INVALID_ORDER_ENUM"
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            return "INVALID_QUANTITY"
        if (
            not math.isfinite(self.filled_quantity)
            or not 0 <= self.filled_quantity <= self.quantity
        ):
            return "INVALID_FILLED_QUANTITY"
        if self.price is not None and (not math.isfinite(self.price) or self.price < 0):
            return "INVALID_PRICE"
        if self.stop_price is not None and (
            not math.isfinite(self.stop_price) or self.stop_price <= 0
        ):
            return "INVALID_STOP_PRICE"
        return None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)


@dataclass(slots=True)
class Trade:
    """
    Represents an executed match between two orders.
    """

    trade_id: str
    maker_order_id: str
    taker_order_id: str
    symbol: str
    price: float
    quantity: float
    aggressor_side: Side
    timestamp: float
    maker_owner_id: str = ""
    taker_owner_id: str = ""
    internal_id: int = 0
    recycle_epoch: int = 0
    _in_pool: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.internal_id == 0:
            self.internal_id = get_next_internal_id()


class EventType(Enum):
    ORDER_SUBMIT = auto()
    ORDER_CANCEL = auto()
    ORDER_REPLACE = auto()
    ORDER_FILL = auto()
    ORDER_REJECT = auto()
    MARKET_DATA_UPDATE = auto()
    STOP_TRIGGERED = auto()


@dataclass(slots=True)
class OrderEvent:
    """
    Event envelope traversing the multi-hop latency pipeline.
    """

    event_id: str
    event_type: EventType
    timestamp: float  # Actual event occurrence / arrival time
    symbol: str
    order: Optional[Order] = None
    trade: Optional[Trade] = None
    message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    sequence_number: int = 0
    recycle_epoch: int = 0
    _in_pool: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.sequence_number == 0:
            self.sequence_number = get_next_internal_id()

    def __lt__(self, other: "OrderEvent") -> bool:
        if self.timestamp == other.timestamp:
            return self.sequence_number < other.sequence_number
        return self.timestamp < other.timestamp

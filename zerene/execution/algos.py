"""
Institutional execution algorithms (TWAP, VWAP, POV, Implementation Shortfall).
Supports urgency-based passive limit order pegging and zero-allocation object pooling (`GLOBAL_ORDER_POOL`).
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from zerene.models import Order, Side, OrderType, TimeInForce
from zerene.pools import GLOBAL_ORDER_POOL


class ExecutionAlgorithm(ABC):
    """Abstract base class for execution schedules."""
    def __init__(
        self,
        symbol: str,
        side: Side,
        total_quantity: float,
        start_time: float,
        end_time: float,
        owner_id: str = "EX_ALGO",
        use_passive_pegging: bool = False,
        urgency_threshold: float = 0.3,
    ):
        self.symbol = symbol
        self.side = side
        self.total_quantity = total_quantity
        self.executed_quantity = 0.0
        self.start_time = start_time
        self.end_time = end_time
        self.owner_id = owner_id
        self.use_passive_pegging = use_passive_pegging
        self.urgency_threshold = urgency_threshold
        self._child_counter: int = 0

    @property
    def is_finished(self) -> bool:
        return self.executed_quantity >= self.total_quantity - 1e-9

    def _acquire_slice_order(self, prefix: str, qty: float, current_time: float, market_data: Dict[str, Any], urgency: float) -> Order:
        self._child_counter += 1
        order_id = f"{prefix}-{self.owner_id}-{self._child_counter}"
        client_id = f"C-{prefix}-{self._child_counter}"

        # Determine order type and price based on passive pegging and urgency
        order_type = OrderType.MARKET
        price: Optional[float] = None

        if self.use_passive_pegging and urgency < self.urgency_threshold:
            best_bid = market_data.get("best_bid")
            best_ask = market_data.get("best_ask")
            mid = market_data.get("mid_price")
            if self.side == Side.BUY and best_bid is not None:
                order_type = OrderType.LIMIT
                price = best_bid if best_ask is None or best_ask - best_bid > 0.02 else round(best_bid + 0.01, 2)
            elif self.side == Side.SELL and best_ask is not None:
                order_type = OrderType.LIMIT
                price = best_ask if best_bid is None or best_ask - best_bid > 0.02 else round(best_ask - 0.01, 2)
            elif mid is not None:
                order_type = OrderType.LIMIT
                price = round(mid, 2)

        return GLOBAL_ORDER_POOL.acquire(
            order_id=order_id,
            client_order_id=client_id,
            symbol=self.symbol,
            side=self.side,
            order_type=order_type,
            quantity=qty,
            price=price,
            timestamp=current_time,
            owner_id=self.owner_id,
        )

    @abstractmethod
    def get_next_slice(self, current_time: float, market_data: Dict[str, Any]) -> Optional[Order]:
        """Returns the next child order slice to submit given current time and market data."""
        pass


class TWAPExecution(ExecutionAlgorithm):
    """Time-Weighted Average Price execution schedule dividing parent order across time intervals."""
    def __init__(
        self,
        symbol: str,
        side: Side,
        total_quantity: float,
        start_time: float,
        end_time: float,
        slices: int = 10,
        owner_id: str = "TWAP",
        use_passive_pegging: bool = False,
        urgency_threshold: float = 0.3,
    ):
        super().__init__(symbol, side, total_quantity, start_time, end_time, owner_id, use_passive_pegging, urgency_threshold)
        self.slices = max(1, slices)
        self.interval = (end_time - start_time) / self.slices
        self.slice_size = total_quantity / self.slices
        self.next_trigger_time = start_time

    def get_next_slice(self, current_time: float, market_data: Dict[str, Any]) -> Optional[Order]:
        if self.is_finished or current_time < self.next_trigger_time:
            return None

        qty = min(self.slice_size, self.total_quantity - self.executed_quantity)
        if qty <= 1e-9:
            return None

        self.executed_quantity += qty
        self.next_trigger_time += self.interval

        # Urgency rises as we get closer to deadline with remaining quantity
        time_left = max(1e-9, self.end_time - current_time)
        total_time = max(1e-9, self.end_time - self.start_time)
        urgency = min(1.0, (1.0 - (time_left / total_time)) * ((self.total_quantity - self.executed_quantity) / self.total_quantity))

        return self._acquire_slice_order("TWAP", qty, current_time, market_data, urgency)


class VWAPExecution(ExecutionAlgorithm):
    """Volume-Weighted Average Price execution schedule weighted by historical volume profile."""
    def __init__(
        self,
        symbol: str,
        side: Side,
        total_quantity: float,
        start_time: float,
        end_time: float,
        volume_weights: List[float],
        owner_id: str = "VWAP",
        use_passive_pegging: bool = False,
        urgency_threshold: float = 0.3,
    ):
        super().__init__(symbol, side, total_quantity, start_time, end_time, owner_id, use_passive_pegging, urgency_threshold)
        self.weights = volume_weights if volume_weights else [1.0]
        total_w = sum(self.weights)
        self.weights = [w / max(1e-9, total_w) for w in self.weights]
        self.slices = len(self.weights)
        self.interval = (end_time - start_time) / max(1, self.slices)
        self.current_slice_idx = 0
        self.next_trigger_time = start_time

    def get_next_slice(self, current_time: float, market_data: Dict[str, Any]) -> Optional[Order]:
        if self.is_finished or self.current_slice_idx >= self.slices or current_time < self.next_trigger_time:
            return None

        weight = self.weights[self.current_slice_idx]
        qty = min(self.total_quantity * weight, self.total_quantity - self.executed_quantity)
        self.current_slice_idx += 1
        self.next_trigger_time += self.interval

        if qty <= 1e-9:
            return None

        self.executed_quantity += qty
        urgency = self.current_slice_idx / max(1, self.slices)
        return self._acquire_slice_order("VWAP", qty, current_time, market_data, urgency)


class POVExecution(ExecutionAlgorithm):
    """Percentage of Volume (POV) execution targeting a participation rate of market volume."""
    def __init__(
        self,
        symbol: str,
        side: Side,
        total_quantity: float,
        target_participation_rate: float = 0.1,
        max_slice: float = 100.0,
        owner_id: str = "POV",
        use_passive_pegging: bool = False,
        urgency_threshold: float = 0.3,
    ):
        super().__init__(symbol, side, total_quantity, 0.0, float("inf"), owner_id, use_passive_pegging, urgency_threshold)
        self.participation_rate = max(0.01, min(0.5, target_participation_rate))
        self.max_slice = max_slice

    def get_next_slice(self, current_time: float, market_data: Dict[str, Any]) -> Optional[Order]:
        if self.is_finished:
            return None

        recent_market_vol = market_data.get("recent_traded_volume", 0.0)
        if recent_market_vol <= 1e-9:
            return None

        target_qty = min(self.max_slice, recent_market_vol * self.participation_rate)
        qty = min(target_qty, self.total_quantity - self.executed_quantity)
        if qty <= 1e-9:
            return None

        self.executed_quantity += qty
        return self._acquire_slice_order("POV", qty, current_time, market_data, urgency=0.1)


class ImplementationShortfallExecution(ExecutionAlgorithm):
    """Implementation Shortfall (IS) / Almgren-Chriss schedule balancing execution urgency and variance risk."""
    def __init__(
        self,
        symbol: str,
        side: Side,
        total_quantity: float,
        start_time: float,
        end_time: float,
        urgency_kappa: float = 0.5,
        slices: int = 10,
        owner_id: str = "IS",
        use_passive_pegging: bool = False,
        urgency_threshold: float = 0.3,
    ):
        super().__init__(symbol, side, total_quantity, start_time, end_time, owner_id, use_passive_pegging, urgency_threshold)
        self.kappa = max(0.01, urgency_kappa)
        self.slices = max(1, slices)
        self.interval = (end_time - start_time) / self.slices
        self.current_slice_idx = 0
        self.next_trigger_time = start_time

        import math
        T = self.slices
        weights = []
        for j in range(T):
            w = (math.sinh(self.kappa * (T - j)) - math.sinh(self.kappa * (T - j - 1))) / math.sinh(self.kappa * T)
            weights.append(max(0.0, w))
        tot = sum(weights)
        self.weights = [w / max(1e-9, tot) for w in weights]

    def get_next_slice(self, current_time: float, market_data: Dict[str, Any]) -> Optional[Order]:
        if self.is_finished or self.current_slice_idx >= self.slices or current_time < self.next_trigger_time:
            return None

        weight = self.weights[self.current_slice_idx]
        qty = min(self.total_quantity * weight, self.total_quantity - self.executed_quantity)
        self.current_slice_idx += 1
        self.next_trigger_time += self.interval

        if qty <= 1e-9:
            return None

        self.executed_quantity += qty
        urgency = self.current_slice_idx / max(1, self.slices)
        return self._acquire_slice_order("IS", qty, current_time, market_data, urgency)

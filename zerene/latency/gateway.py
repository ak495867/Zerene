"""
Multi-Hop Latency Gateway routing events through priority queues.
Conforms to RFC-003.
"""

import heapq
from typing import List, Optional, Callable, Dict, Any, Tuple
from zerene.models import OrderEvent, EventType
from zerene.latency.models import LatencyModel, DeterministicLatency


class LatencyGateway:
    """
    Routes events between clients and matching engines across configured latency hops.
    Uses priority min-heap sorted by arrival_time (`due_time`, `seq_num`) to preserve strict temporal causality and deterministic tie-breaking.
    """
    def __init__(
        self,
        net_in_model: Optional[LatencyModel] = None,
        gateway_model: Optional[LatencyModel] = None,
        engine_model: Optional[LatencyModel] = None,
        net_out_model: Optional[LatencyModel] = None,
    ):
        self.net_in = net_in_model or DeterministicLatency(0.001)
        self.gateway = gateway_model or DeterministicLatency(0.0002)
        self.engine = engine_model or DeterministicLatency(0.0001)
        self.net_out = net_out_model or DeterministicLatency(0.001)

        self.inbound_queue: List[Tuple[float, int, OrderEvent]] = []   # Events destined for Matching Engine
        self.outbound_queue: List[Tuple[float, int, OrderEvent]] = []  # Events destined for Clients
        self._seq_counter: int = 0

    def submit_inbound(self, event: OrderEvent) -> bool:
        """
        Processes inbound order submission/cancellation from client to matching engine.
        Returns False if packet was dropped.
        """
        if self.net_in.should_drop() or self.gateway.should_drop():
            return False

        delay = self.net_in.sample() + self.gateway.sample() + self.engine.sample()
        event.timestamp += delay
        self._seq_counter += 1
        heapq.heappush(self.inbound_queue, (event.timestamp, self._seq_counter, event))
        return True

    def submit_outbound(self, event: OrderEvent) -> bool:
        """
        Processes outbound confirmation or fill report from engine to client.
        Returns False if packet was dropped.
        """
        if self.net_out.should_drop():
            return False

        delay = self.net_out.sample()
        event.timestamp += delay
        self._seq_counter += 1
        heapq.heappush(self.outbound_queue, (event.timestamp, self._seq_counter, event))
        return True

    def pop_due_inbound(self, current_time: float) -> List[OrderEvent]:
        """Pops and returns all inbound events arriving at or before `current_time`."""
        due: List[OrderEvent] = []
        while self.inbound_queue and self.inbound_queue[0][0] <= current_time:
            _, _, ev = heapq.heappop(self.inbound_queue)
            due.append(ev)
        return due

    def pop_due_outbound(self, current_time: float) -> List[OrderEvent]:
        """Pops and returns all outbound events arriving at or before `current_time`."""
        due: List[OrderEvent] = []
        while self.outbound_queue and self.outbound_queue[0][0] <= current_time:
            _, _, ev = heapq.heappop(self.outbound_queue)
            due.append(ev)
        return due

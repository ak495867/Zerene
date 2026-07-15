"""
Tests for multi-hop deterministic and stochastic latency models and priority queues.
"""

import pytest
from zerene.latency.models import DeterministicLatency, StochasticLatency
from zerene.latency.gateway import LatencyGateway
from zerene.models import OrderEvent, EventType


def test_deterministic_and_stochastic_latency():
    det = DeterministicLatency(0.005)
    assert det.sample() == 0.005
    assert det.should_drop() is False

    stoch = StochasticLatency(distribution="normal", mean_seconds=0.003, std_seconds=0.0001)
    sample = stoch.sample()
    assert sample >= stoch.min_latency


def test_latency_gateway_priority_queue():
    gw = LatencyGateway(
        net_in_model=DeterministicLatency(0.001),
        gateway_model=DeterministicLatency(0.001),
        engine_model=DeterministicLatency(0.001),
    )

    ev1 = OrderEvent(event_id="EV1", event_type=EventType.ORDER_SUBMIT, timestamp=1.0, symbol="BTC-USD")
    ev2 = OrderEvent(event_id="EV2", event_type=EventType.ORDER_SUBMIT, timestamp=0.5, symbol="BTC-USD")

    gw.submit_inbound(ev1)
    gw.submit_inbound(ev2)

    # Total delay = 0.003s per event. EV2 arrives at 0.503, EV1 arrives at 1.003.
    due = gw.pop_due_inbound(0.60)
    assert len(due) == 1
    assert due[0].event_id == "EV2"

    due2 = gw.pop_due_inbound(1.10)
    assert len(due2) == 1
    assert due2[0].event_id == "EV1"

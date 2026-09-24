"""
SIP Market Data Feed & Latency Arbitrage Simulator for ZERENE.
Simulates Securities Information Processor (SIP) consolidated feed latency vs Direct Exchange Feeds (ITCH/OUCH).
Enables backtesting High-Frequency Latency Arbitrage & quote pick-off strategies.
"""

import heapq
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from zerene.orderbook.snapshots import OrderBookSnapshot


@dataclass(slots=True)
class SIPFeedPacket:
    """Consolidated market data packet traversing the SIP network pipeline."""

    send_time: float
    receive_time: float
    venue_id: str
    symbol: str
    snapshot: OrderBookSnapshot
    seq_num: int


class SIPFeedSimulator:
    """
    Simulates Consolidated SIP Feed delay vs Direct Feed latency across fragmented venues.
    """

    def __init__(
        self,
        direct_feed_latency_sec: float = 0.0002,  # 200 microseconds direct feed
        sip_consolidation_latency_sec: float = 0.0020,  # 2.0 milliseconds SIP feed
    ):
        self.direct_latency = direct_feed_latency_sec
        self.sip_latency = sip_consolidation_latency_sec
        self.sip_queue: List[Tuple[float, int, SIPFeedPacket]] = []
        self._seq_counter = 0

    def publish_snapshot(
        self, venue_id: str, symbol: str, snapshot: OrderBookSnapshot, current_time: float
    ) -> None:
        """Publishes an L2 snapshot to the SIP consolidation pipeline."""
        self._seq_counter += 1
        receive_time = current_time + self.sip_latency
        pkt = SIPFeedPacket(
            send_time=current_time,
            receive_time=receive_time,
            venue_id=venue_id,
            symbol=symbol,
            snapshot=snapshot,
            seq_num=self._seq_counter,
        )
        heapq.heappush(self.sip_queue, (receive_time, self._seq_counter, pkt))

    def get_due_sip_updates(self, current_time: float) -> List[SIPFeedPacket]:
        """Pops all consolidated SIP feed updates arriving at or before `current_time`."""
        due: List[SIPFeedPacket] = []
        while self.sip_queue and self.sip_queue[0][0] <= current_time:
            _, _, pkt = heapq.heappop(self.sip_queue)
            due.append(pkt)
        return due

    def calculate_latency_arbitrage_opportunity(
        self,
        direct_snapshots: Dict[str, OrderBookSnapshot],
        sip_snapshots: Dict[str, OrderBookSnapshot],
    ) -> List[Dict[str, Any]]:
        """
        Identifies stale quotes on slower venues where SIP feed has not yet updated
        relative to fast direct feed changes.
        """
        opportunities = []
        for vid, direct_snap in direct_snapshots.items():
            sip_snap = sip_snapshots.get(vid)
            if not sip_snap:
                continue

            # Compare direct best bid/ask vs stale SIP best bid/ask
            d_bid = direct_snap.bids[0][0] if direct_snap.bids else None
            s_bid = sip_snap.bids[0][0] if sip_snap.bids else None

            d_ask = direct_snap.asks[0][0] if direct_snap.asks else None
            s_ask = sip_snap.asks[0][0] if sip_snap.asks else None

            if d_bid is not None and s_bid is not None and d_bid > s_bid:
                opportunities.append({
                    "venue_id": vid,
                    "side": "BUY",
                    "stale_price": s_bid,
                    "fresh_price": d_bid,
                    "arb_profit_bps": ((d_bid - s_bid) / s_bid) * 10000.0,
                })

            if d_ask is not None and s_ask is not None and d_ask < s_ask:
                opportunities.append({
                    "venue_id": vid,
                    "side": "SELL",
                    "stale_price": s_ask,
                    "fresh_price": d_ask,
                    "arb_profit_bps": ((s_ask - d_ask) / s_ask) * 10000.0,
                })

        return opportunities

"""
Level II and Level III snapshot containers.
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
from zerene.orderbook.book import OrderBook


@dataclass
class OrderBookSnapshot:
    """
    Immutable representation of the book state at a given timestamp.
    """

    symbol: str
    timestamp: float
    bids: List[Tuple[float, float]]  # (price, visible_volume)
    asks: List[Tuple[float, float]]
    mid_price: Optional[float]
    spread: Optional[float]
    imbalance: float

    @classmethod
    def from_book(
        cls, book: OrderBook, timestamp: float, levels: int = 10
    ) -> "OrderBookSnapshot":
        bids_depth, asks_depth = book.get_depth(levels=levels)
        return cls(
            symbol=book.symbol,
            timestamp=timestamp,
            bids=bids_depth,
            asks=asks_depth,
            mid_price=book.mid_price(),
            spread=book.spread(),
            imbalance=book.imbalance(levels=levels),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bids": self.bids,
            "asks": self.asks,
            "mid_price": self.mid_price,
            "spread": self.spread,
            "imbalance": self.imbalance,
        }

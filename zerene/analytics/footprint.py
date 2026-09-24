"""
Institutional Footprint Chart & Volume Profile Analytics for ZERENE.
Tracks Bid/Ask volume delta per price level, Point of Control (POC),
Value Area High/Low (VAH/VAL), and Cumulative Volume Delta (CVD).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from zerene.models import Trade, Side


@dataclass
class FootprintBar:
    """Footprint bar aggregating volume traded per price level split by aggressor side."""

    bar_id: int
    start_time: float
    end_time: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    price_level_volumes: Dict[float, Dict[str, float]] = field(
        default_factory=dict
    )  # price -> {"buy_vol": float, "sell_vol": float}
    total_buy_volume: float = 0.0
    total_sell_volume: float = 0.0
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None

    def add_trade(self, price: float, quantity: float, aggressor_side: Side) -> None:
        p = round(price, 4)
        if p not in self.price_level_volumes:
            self.price_level_volumes[p] = {"buy_vol": 0.0, "sell_vol": 0.0}

        if aggressor_side == Side.BUY:
            self.price_level_volumes[p]["buy_vol"] += quantity
            self.total_buy_volume += quantity
        else:
            self.price_level_volumes[p]["sell_vol"] += quantity
            self.total_sell_volume += quantity

        self.high_price = max(self.high_price, price)
        self.low_price = min(self.low_price, price)
        self.close_price = price

    def finalize(self) -> None:
        """Calculates Point of Control (POC) and Value Area High/Low (VAH/VAL)."""
        if not self.price_level_volumes:
            return

        # POC: price with max total volume
        poc = max(
            self.price_level_volumes.keys(),
            key=lambda p: self.price_level_volumes[p]["buy_vol"]
            + self.price_level_volumes[p]["sell_vol"],
        )
        self.poc_price = poc

        # Value Area (70% of total volume centered around POC)
        total_vol = self.total_buy_volume + self.total_sell_volume
        target_vol = total_vol * 0.70

        sorted_prices = sorted(self.price_level_volumes.keys())
        poc_idx = sorted_prices.index(poc)

        accumulated = (
            self.price_level_volumes[poc]["buy_vol"]
            + self.price_level_volumes[poc]["sell_vol"]
        )
        low_idx = poc_idx
        high_idx = poc_idx

        while accumulated < target_vol and (
            low_idx > 0 or high_idx < len(sorted_prices) - 1
        ):
            next_low_vol = 0.0
            if low_idx > 0:
                p_low = sorted_prices[low_idx - 1]
                next_low_vol = (
                    self.price_level_volumes[p_low]["buy_vol"]
                    + self.price_level_volumes[p_low]["sell_vol"]
                )

            next_high_vol = 0.0
            if high_idx < len(sorted_prices) - 1:
                p_high = sorted_prices[high_idx + 1]
                next_high_vol = (
                    self.price_level_volumes[p_high]["buy_vol"]
                    + self.price_level_volumes[p_high]["sell_vol"]
                )

            if next_high_vol >= next_low_vol and high_idx < len(sorted_prices) - 1:
                high_idx += 1
                accumulated += next_high_vol
            elif low_idx > 0:
                low_idx -= 1
                accumulated += next_low_vol
            else:
                break

        self.val_price = sorted_prices[low_idx]
        self.vah_price = sorted_prices[high_idx]


class FootprintTracker:
    """
    Real-time Footprint & Cumulative Volume Delta (CVD) analytics tracker.
    """

    def __init__(self, bar_duration_sec: float = 60.0):
        self.bar_duration = bar_duration_sec
        self.bars: List[FootprintBar] = []
        self.current_bar: Optional[FootprintBar] = None
        self.cvd: float = 0.0  # Cumulative Volume Delta (Buy Vol - Sell Vol)

    def on_trade(self, trade: Trade) -> None:
        """Ingests a trade print and updates active footprint bar and CVD."""
        delta = trade.quantity if trade.aggressor_side == Side.BUY else -trade.quantity
        self.cvd += delta

        if not self.current_bar or trade.timestamp >= self.current_bar.end_time:
            if self.current_bar:
                self.current_bar.finalize()
                self.bars.append(self.current_bar)

            bar_id = len(self.bars) + 1
            start_t = trade.timestamp
            end_t = start_t + self.bar_duration
            self.current_bar = FootprintBar(
                bar_id=bar_id,
                start_time=start_t,
                end_time=end_t,
                open_price=trade.price,
                high_price=trade.price,
                low_price=trade.price,
                close_price=trade.price,
            )

        self.current_bar.add_trade(trade.price, trade.quantity, trade.aggressor_side)

    def get_summary(self) -> Dict[str, Any]:
        """Returns current CVD and latest footprint bar stats."""
        curr = self.current_bar
        if curr:
            curr.finalize()
        return {
            "cvd": self.cvd,
            "total_bars": len(self.bars) + (1 if curr else 0),
            "latest_poc": curr.poc_price if curr else None,
            "latest_vah": curr.vah_price if curr else None,
            "latest_val": curr.val_price if curr else None,
        }

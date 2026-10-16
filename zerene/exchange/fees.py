"""
Tiered Maker-Taker Fee and Rebate Models.
Implements institutional volume-tiered fee curves (e.g. VIP 0 to VIP 9) with negative maker rebates
and taker surcharges based on 30-day rolling turnover or simulated execution tranches.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass(slots=True)
class FeeTier:
    min_volume_30d: float  # Minimum 30d USD volume to unlock tier
    maker_fee_bps: float  # Maker fee (negative = rebate to liquidity provider)
    taker_fee_bps: float  # Taker fee (positive = charge to liquidity taker)


@dataclass
class FeeSchedule:
    """
    Tiered fee schedule model conforming to Tier 1 equity and crypto derivatives venues.
    """

    venue_name: str = "DEFAULT"
    tiers: List[FeeTier] = field(
        default_factory=lambda: [
            FeeTier(
                min_volume_30d=0.0, maker_fee_bps=1.0, taker_fee_bps=5.0
            ),  # Retail / VIP 0
            FeeTier(
                min_volume_30d=100_000.0, maker_fee_bps=0.0, taker_fee_bps=3.5
            ),  # VIP 1
            FeeTier(
                min_volume_30d=1_000_000.0, maker_fee_bps=-0.5, taker_fee_bps=2.0
            ),  # VIP 2 (Maker Rebate)
            FeeTier(
                min_volume_30d=10_000_000.0, maker_fee_bps=-1.0, taker_fee_bps=1.5
            ),  # VIP 3 (Institutional MM)
            FeeTier(
                min_volume_30d=50_000_000.0, maker_fee_bps=-1.5, taker_fee_bps=1.0
            ),  # VIP 4 (Lead Market Maker)
        ]
    )

    def get_tier_fees(self, participant_volume_30d: float) -> Tuple[float, float]:
        """Returns (maker_fee_bps, taker_fee_bps) for the corresponding participant tier."""
        selected_tier = self.tiers[0]
        for t in self.tiers:
            if participant_volume_30d >= t.min_volume_30d:
                selected_tier = t
        return selected_tier.maker_fee_bps, selected_tier.taker_fee_bps

    def calculate_trade_fees(
        self,
        notional_value: float,
        is_maker: bool,
        participant_volume_30d: float = 0.0,
    ) -> float:
        """
        Calculates fee in USD currency.
        Positive fee = cost paid to exchange.
        Negative fee = rebate paid to participant.
        """
        maker_bps, taker_bps = self.get_tier_fees(participant_volume_30d)
        effective_bps = maker_bps if is_maker else taker_bps
        return round(notional_value * (effective_bps / 10_000.0), 6)

"""
Risk limit configuration container.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class RiskLimits:
    """
    Configurable risk limits for a market participant.
    Breaching these thresholds triggers the automated kill switch.
    """
    max_gross_exposure: float = 1_000_000.0
    max_net_exposure: float = 500_000.0
    max_position_per_symbol: float = 10_000.0
    max_daily_loss: float = 50_000.0
    max_drawdown_pct: float = 0.15          # 15% maximum drawdown from peak capital
    max_leverage: float = 10.0
    var_95_limit: float = 25_000.0          # Value-at-Risk threshold
    cvar_95_limit: float = 35_000.0         # Expected Shortfall / CVaR threshold
    symbol_position_limits: Dict[str, float] = field(default_factory=dict)

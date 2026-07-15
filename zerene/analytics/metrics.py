"""
Trading performance and market microstructure metric calculations.
"""

import math
from typing import List, Dict, Any, Optional
from zerene.models import Trade, Side


def calculate_max_drawdown(equity_curve: List[float]) -> float:
    """Calculates maximum percentage drawdown from peak."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Calculates annualized Sharpe Ratio from periodic return series."""
    if len(returns) < 2:
        return 0.0
    import numpy as np
    arr = np.array(returns)
    mean = float(np.mean(arr)) - (risk_free_rate / periods_per_year)
    std = float(np.std(arr, ddof=1))
    if std <= 1e-9:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def calculate_sortino_ratio(returns: List[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Calculates annualized Sortino Ratio (downside risk adjusted)."""
    if len(returns) < 2:
        return 0.0
    import numpy as np
    arr = np.array(returns)
    mean = float(np.mean(arr)) - (risk_free_rate / periods_per_year)
    downside = arr[arr < 0]
    if len(downside) == 0:
        std_down = float(np.std(arr, ddof=1))
    else:
        std_down = float(np.std(downside, ddof=1))
    if std_down <= 1e-9:
        return 0.0
    return (mean / std_down) * math.sqrt(periods_per_year)


def calculate_calmar_ratio(cagr: float, max_drawdown: float) -> float:
    """Calculates Calmar Ratio (CAGR / Max Drawdown)."""
    if max_drawdown <= 1e-9:
        return float("inf") if cagr > 0 else 0.0
    return cagr / max_drawdown


def calculate_profit_factor(trade_pnls: List[float]) -> float:
    """Calculates Profit Factor (gross winning trade gains / gross losing trade losses)."""
    gross_gains = sum(p for p in trade_pnls if p > 0)
    gross_losses = sum(abs(p) for p in trade_pnls if p < 0)
    if gross_losses <= 1e-9:
        return float("inf") if gross_gains > 0 else 0.0
    return gross_gains / gross_losses


def calculate_effective_spread(trades: List[Trade], mid_prices: Dict[str, float]) -> float:
    """
    Calculates average effective spread across trades:
    Effective Spread = 2 * |Trade Price - Mid Price|
    """
    if not trades:
        return 0.0
    total = 0.0
    count = 0
    for t in trades:
        mid = mid_prices.get(t.trade_id)
        if mid is not None and mid > 0:
            total += 2.0 * abs(t.price - mid) / mid
            count += 1
    return total / max(1, count)


def calculate_adverse_selection(trades: List[Trade], future_mids: Dict[str, float]) -> float:
    """
    Calculates adverse selection / price impact at specific time horizon tau:
    Adverse Selection = Sign(Aggressor Side) * (Mid_future - Trade Price) / Trade Price
    """
    if not trades:
        return 0.0
    total = 0.0
    count = 0
    for t in trades:
        f_mid = future_mids.get(t.trade_id)
        if f_mid is not None and t.price > 0:
            sign = 1.0 if t.aggressor_side == Side.BUY else -1.0
            total += sign * (f_mid - t.price) / t.price
            count += 1
    return total / max(1, count)

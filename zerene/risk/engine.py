"""
Real-time risk tracking engine and kill switch.
"""

import math
from typing import Dict, List, Optional, Any, Tuple
from zerene.models import Order, Trade, Side, OrderStatus, OrderType
from zerene.risk.limits import RiskLimits

"""
Real-time risk tracking engine and kill switch.
"""

import math
from typing import Dict, List, Optional, Any, Tuple
from zerene.models import Order, Trade, Side, OrderStatus, OrderType


class PositionDict(dict):
    """
    Dictionary wrapper for positions and average prices that marks the state dirty when modified directly.
    """

    def __init__(self, state: "ParticipantRiskState"):
        super().__init__()
        self.state = state

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.state._dirty = True

    def __delitem__(self, key):
        super().__delitem__(key)
        self.state._dirty = True

    def pop(self, key, default=...):
        self.state._dirty = True
        if default is ...:
            return super().pop(key)
        return super().pop(key, default)

    def clear(self):
        super().clear()
        self.state._dirty = True


class ParticipantRiskState:
    """
    Tracks real-time portfolio state, equity, margin, and exposure for a single participant.
    Uses O(1) incremental running exposures and PnL caching (`_dirty` tracking) to eliminate dictionary iteration on high-throughput pre-trade checks while preserving 100% test compatibility.
    """

    def __init__(
        self,
        owner_id: str,
        initial_capital: float = 1_000_000.0,
        limits: Optional[RiskLimits] = None,
    ):
        self.owner_id = owner_id
        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.realized_pnl = 0.0
        self._dirty: bool = False
        self.positions: PositionDict = PositionDict(
            self
        )  # symbol -> net quantity (positive=long, negative=short)
        self.average_prices: PositionDict = PositionDict(
            self
        )  # symbol -> avg entry price
        self.running_gross_exposure: float = 0.0
        self.running_net_exposure: float = 0.0
        self.cached_unrealized_pnl: float = 0.0
        self.return_history: List[float] = []
        self.limits = limits or RiskLimits()
        self.kill_switch_active: bool = False
        self.kill_switch_reason: Optional[str] = None

    @property
    def equity(self) -> float:
        return self.initial_capital + self.realized_pnl

    def update_peak_equity(self, current_unrealized_pnl: float = 0.0) -> None:
        total = self.equity + current_unrealized_pnl
        if total > self.peak_equity:
            self.peak_equity = total

    def calculate_drawdown(self, current_unrealized_pnl: float = 0.0) -> float:
        total = self.equity + current_unrealized_pnl
        if self.peak_equity <= 1e-9:
            return 0.0
        return max(0.0, (self.peak_equity - total) / self.peak_equity)

    def _sync_exposures(self, market_prices: Dict[str, float]) -> None:
        gross = 0.0
        net = 0.0
        unreal = 0.0
        for sym, qty in self.positions.items():
            price = market_prices.get(sym, self.average_prices.get(sym, 0.0))
            avg_p = self.average_prices.get(sym, 0.0)
            gross += abs(qty) * price
            net += qty * price
            if abs(qty) > 1e-9 and avg_p > 0:
                unreal += qty * (price - avg_p)
        self.running_gross_exposure = gross
        self.running_net_exposure = net
        self.cached_unrealized_pnl = unreal
        self._dirty = False

    def gross_exposure(self, market_prices: Dict[str, float]) -> float:
        if not self.positions:
            return 0.0
        if self._dirty:
            self._sync_exposures(market_prices)
        return max(0.0, self.running_gross_exposure)

    def net_exposure(self, market_prices: Dict[str, float]) -> float:
        if not self.positions:
            return 0.0
        if self._dirty:
            self._sync_exposures(market_prices)
        return self.running_net_exposure

    def unrealized_pnl(self, market_prices: Dict[str, float]) -> float:
        if not self.positions:
            return 0.0
        if self._dirty:
            self._sync_exposures(market_prices)
        return self.cached_unrealized_pnl

    def calculate_var_cvar(self, confidence: float = 0.95) -> Tuple[float, float]:
        """Calculates historical Value-at-Risk (VaR) and Conditional VaR (CVaR)."""
        if len(self.return_history) < 10:
            return 0.0, 0.0

        sorted_returns = sorted(self.return_history)
        cutoff_idx = max(0, int((1.0 - confidence) * len(sorted_returns)))
        var_return = (
            abs(sorted_returns[cutoff_idx]) if sorted_returns[cutoff_idx] < 0 else 0.0
        )

        tail = [r for r in sorted_returns[: max(1, cutoff_idx)] if r < 0]
        cvar_return = abs(sum(tail) / max(1, len(tail))) if tail else var_return

        var_dollar = var_return * self.equity
        cvar_dollar = cvar_return * self.equity
        return var_dollar, cvar_dollar


class RiskEngine:
    """
    Master Risk Engine managing pre-trade order validation, real-time exposure tracking,
    and automatic kill-switch enforcement for all participants.
    """

    def __init__(self):
        self.states: Dict[str, ParticipantRiskState] = {}
        self.market_prices: Dict[str, float] = {}
        self.on_kill_switch_callback: Optional[Any] = None  # Callable[[str, str], None]

    def register_participant(
        self,
        owner_id: str,
        initial_capital: float = 1_000_000.0,
        limits: Optional[RiskLimits] = None,
    ) -> ParticipantRiskState:
        if owner_id not in self.states:
            self.states[owner_id] = ParticipantRiskState(
                owner_id, initial_capital, limits
            )
        return self.states[owner_id]

    def update_market_price(self, symbol: str, price: float) -> None:
        old_price = self.market_prices.get(symbol)
        self.market_prices[symbol] = price
        if old_price is None:
            old_price = price
        delta_p = price - old_price
        if abs(delta_p) > 1e-9:
            for state in self.states.values():
                if not state._dirty:
                    qty = state.positions.get(symbol, 0.0)
                    if abs(qty) > 1e-9:
                        state.running_gross_exposure += abs(qty) * delta_p
                        state.running_net_exposure += qty * delta_p
                        state.cached_unrealized_pnl += qty * delta_p

    def validate_order(self, order: Order) -> Tuple[bool, Optional[str]]:
        """
        Pre-trade risk check in strict O(1) without iterating positions dictionary when cached.
        Returns (is_valid, reject_reason). Also handles Reduce-Only validation and adjustments.
        """
        state = self.states.get(order.owner_id)
        if not state:
            return True, None

        if state.kill_switch_active:
            return False, f"KILL_SWITCH_ACTIVE: {state.kill_switch_reason}"

        price = order.price or self.market_prices.get(order.symbol, 0.0)
        if price <= 0:
            return (
                True,
                None,
            )  # Market order without reference price passes check until matched

        # Reduce-only check
        if order.order_type == OrderType.REDUCE_ONLY:
            current_pos = state.positions.get(order.symbol, 0.0)
            if (order.side == Side.BUY and current_pos >= 0) or (
                order.side == Side.SELL and current_pos <= 0
            ):
                return False, "REDUCE_ONLY_WOULD_INCREASE_POSITION"
            if order.quantity > abs(current_pos):
                order.quantity = abs(current_pos)
                if order.display_quantity is not None:
                    order.display_quantity = min(order.display_quantity, order.quantity)

        # Position limit check
        sym_limit = state.limits.symbol_position_limits.get(
            order.symbol, state.limits.max_position_per_symbol
        )
        current_pos = state.positions.get(order.symbol, 0.0)
        delta = order.quantity if order.side == Side.BUY else -order.quantity
        if abs(current_pos + delta) > sym_limit:
            return False, "POSITION_LIMIT_EXCEEDED"

        # Exposure limit checks
        est_gross = state.gross_exposure(self.market_prices) + order.quantity * price
        if est_gross > state.limits.max_gross_exposure:
            return False, "GROSS_EXPOSURE_LIMIT_EXCEEDED"

        # Check drawdown & loss limits
        unreal = state.unrealized_pnl(self.market_prices)
        state.update_peak_equity(unreal)
        dd = state.calculate_drawdown(unreal)
        if dd >= state.limits.max_drawdown_pct:
            state.kill_switch_active = True
            state.kill_switch_reason = f"MAX_DRAWDOWN_BREACH: {dd*100:.1f}% >= {state.limits.max_drawdown_pct*100:.1f}%"
            if self.on_kill_switch_callback:
                self.on_kill_switch_callback(order.owner_id, state.kill_switch_reason)
            return False, state.kill_switch_reason

        return True, None

    def on_trade_fill(self, trade: Trade) -> None:
        """Post-trade exposure and inventory reconciliation with O(1) incremental exposure maintenance."""
        self.update_market_price(trade.symbol, trade.price)
        for owner_id, side in [
            (
                trade.maker_owner_id,
                Side.SELL if trade.aggressor_side == Side.BUY else Side.BUY,
            ),
            (trade.taker_owner_id, trade.aggressor_side),
        ]:
            if not owner_id or owner_id not in self.states:
                continue

            state = self.states[owner_id]
            if state._dirty:
                state._sync_exposures(self.market_prices)

            current_qty = state.positions.get(trade.symbol, 0.0)
            avg_price = state.average_prices.get(trade.symbol, 0.0)

            # Deduct old position contribution from running exposure counters
            if abs(current_qty) > 1e-9:
                state.running_gross_exposure = max(
                    0.0, state.running_gross_exposure - abs(current_qty) * trade.price
                )
                state.running_net_exposure -= current_qty * trade.price
                if avg_price > 0:
                    state.cached_unrealized_pnl -= current_qty * (
                        trade.price - avg_price
                    )

            trade_delta = trade.quantity if side == Side.BUY else -trade.quantity
            new_qty = current_qty + trade_delta

            # Calculate realized PnL if reducing position
            if (current_qty > 0 and trade_delta < 0) or (
                current_qty < 0 and trade_delta > 0
            ):
                closed_qty = min(abs(current_qty), abs(trade_delta))
                if current_qty > 0:
                    pnl = closed_qty * (trade.price - avg_price)
                else:
                    pnl = closed_qty * (avg_price - trade.price)
                state.realized_pnl += pnl
                if state.equity > 0:
                    state.return_history.append(pnl / state.equity)

            # Update average price if increasing position or flipping
            if abs(new_qty) <= 1e-9:
                state.positions._dirty = False
                dict.__setitem__(state.positions, trade.symbol, 0.0)
                dict.__setitem__(state.average_prices, trade.symbol, 0.0)
            elif (current_qty >= 0 and trade_delta > 0) or (
                current_qty <= 0 and trade_delta < 0
            ):
                new_avg = (
                    (abs(current_qty) * avg_price) + (abs(trade_delta) * trade.price)
                ) / abs(new_qty)
                dict.__setitem__(state.average_prices, trade.symbol, new_avg)
                dict.__setitem__(state.positions, trade.symbol, new_qty)
            else:
                dict.__setitem__(state.positions, trade.symbol, new_qty)
                if (current_qty > 0 and new_qty < 0) or (
                    current_qty < 0 and new_qty > 0
                ):
                    dict.__setitem__(state.average_prices, trade.symbol, trade.price)

            # Add new position contribution to running exposure counters
            new_avg_p = state.average_prices.get(trade.symbol, 0.0)
            if abs(new_qty) > 1e-9:
                state.running_gross_exposure += abs(new_qty) * trade.price
                state.running_net_exposure += new_qty * trade.price
                if new_avg_p > 0:
                    state.cached_unrealized_pnl += new_qty * (trade.price - new_avg_p)

            # Post-trade check for daily loss or drawdown kill switch
            unreal = state.cached_unrealized_pnl
            state.update_peak_equity(unreal)
            dd = state.calculate_drawdown(unreal)
            if dd >= state.limits.max_drawdown_pct or (
                -state.realized_pnl >= state.limits.max_daily_loss
            ):
                state.kill_switch_active = True
                state.kill_switch_reason = f"RISK_LIMIT_BREACH (Drawdown={dd*100:.1f}%, RealizedPnL={state.realized_pnl})"
                if self.on_kill_switch_callback:
                    self.on_kill_switch_callback(owner_id, state.kill_switch_reason)

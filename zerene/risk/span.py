"""
Cross-Collateral SPAN Portfolio Margin & Liquidation Engine for ZERENE.
Implements institutional portfolio margin calculation under multi-scenario stress tests
with collateral haircuts and automated liquidation cascades.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from zerene.models import Order, Side, OrderType, Trade
from zerene.exchange.venue import ExchangeVenue


@dataclass
class CollateralHaircut:
    """Collateral haircut factors (1.0 = no haircut, 0.85 = 15% discount)."""

    asset: str
    haircut_factor: float = 0.85


@dataclass
class MarginRequirement:
    """Calculated portfolio margin requirements."""

    owner_id: str
    cash_balance: float
    collateral_value: float
    unrealized_pnl: float
    total_margin_equity: float
    initial_margin_required: float
    maintenance_margin_required: float
    margin_call_active: bool
    liquidation_required: bool


class SPANPortfolioRiskEngine:
    """
    SPAN-Style Portfolio Risk & Liquidation Engine.
    Evaluates scenario stress matrices across assets to calculate margin requirements.
    """

    def __init__(
        self,
        haircuts: Optional[Dict[str, float]] = None,
        stress_scenarios: Optional[List[float]] = None,
    ):
        self.haircuts = haircuts or {
            "USD": 1.0,
            "USDT": 1.0,
            "BTC-USD": 0.85,
            "ETH-USD": 0.80,
        }
        self.stress_scenarios = stress_scenarios or [
            -0.20,
            -0.10,
            -0.05,
            0.0,
            0.05,
            0.10,
            0.20,
        ]
        self.cash_balances: Dict[str, float] = {}  # owner_id -> USD cash
        self.positions: Dict[str, Dict[str, float]] = {}  # owner_id -> {symbol: qty}

    def set_cash_balance(self, owner_id: str, amount: float) -> None:
        self.cash_balances[owner_id] = amount

    def update_position(
        self, owner_id: str, symbol: str, quantity_delta: float
    ) -> None:
        if owner_id not in self.positions:
            self.positions[owner_id] = {}
        curr = self.positions[owner_id].get(symbol, 0.0)
        self.positions[owner_id][symbol] = curr + quantity_delta

    def calculate_portfolio_margin(
        self, owner_id: str, market_prices: Dict[str, float]
    ) -> MarginRequirement:
        """
        Evaluates portfolio margin equity against stress scenario matrices.
        """
        cash = self.cash_balances.get(owner_id, 100_000.0)
        user_pos = self.positions.get(owner_id, {})

        collateral_val = 0.0
        unrealized = 0.0
        base_gross_exp = 0.0

        for sym, qty in user_pos.items():
            price = market_prices.get(sym, 0.0)
            if price <= 0:
                continue
            haircut = self.haircuts.get(sym, 0.80)

            # Position value after haircut
            pos_val = abs(qty) * price
            base_gross_exp += pos_val
            collateral_val += pos_val * haircut

        # Compute max worst-case loss across stress scenarios
        max_scenario_loss = 0.0
        for shock in self.stress_scenarios:
            scenario_pnl = 0.0
            for sym, qty in user_pos.items():
                p = market_prices.get(sym, 0.0)
                if p <= 0:
                    continue
                shocked_p = p * (1.0 + shock)
                scenario_pnl += qty * (shocked_p - p)

            if scenario_pnl < 0:
                max_scenario_loss = max(max_scenario_loss, abs(scenario_pnl))

        # Initial margin = 1.25x worst-case scenario loss + 2% gross exposure buffer
        im_req = (max_scenario_loss * 1.25) + (base_gross_exp * 0.02)
        mm_req = (max_scenario_loss * 1.0) + (base_gross_exp * 0.01)

        total_margin_equity = cash + collateral_val + unrealized
        margin_call = total_margin_equity < im_req
        liquidation = total_margin_equity < mm_req

        return MarginRequirement(
            owner_id=owner_id,
            cash_balance=cash,
            collateral_value=collateral_val,
            unrealized_pnl=unrealized,
            total_margin_equity=total_margin_equity,
            initial_margin_required=im_req,
            maintenance_margin_required=mm_req,
            margin_call_active=margin_call,
            liquidation_required=liquidation,
        )

    def execute_liquidation_cascade(
        self, owner_id: str, exchange: ExchangeVenue, market_prices: Dict[str, float]
    ) -> List[Order]:
        """
        Submits market liquidation orders for liquidating portfolios below maintenance margin.
        """
        margin = self.calculate_portfolio_margin(owner_id, market_prices)
        if not margin.liquidation_required:
            return []

        # Cancel all resting orders first
        exchange.cancel_all_for_participant(owner_id, reason="LIQUIDATION_CASCADE")

        liquidation_orders: List[Order] = []
        user_pos = self.positions.get(owner_id, {})

        for sym, qty in list(user_pos.items()):
            if abs(qty) <= 1e-9:
                continue

            # Submit aggressive market liquidation order
            liq_side = Side.SELL if qty > 0 else Side.BUY
            liq_order = Order(
                order_id=f"LIQ-{owner_id}-{sym}",
                client_order_id="C-LIQ",
                symbol=sym,
                side=liq_side,
                order_type=OrderType.MARKET,
                quantity=abs(qty),
                timestamp=0.0,
                owner_id="LIQUIDATOR",
            )
            exchange.submit_order(liq_order)
            liquidation_orders.append(liq_order)

            # Reset position counter
            user_pos[sym] = 0.0

        return liquidation_orders

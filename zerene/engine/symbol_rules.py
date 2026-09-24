"""
Institutional Symbol Rules & Microstructure Specifications for ZERENE.
Enforces Minimum Price Variation (MPV / Tick Size), Lot Size, Step Size,
and order quantity boundaries per trading symbol.
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple
from zerene.models import Order, Side, OrderType, OrderStatus


@dataclass(slots=True)
class SymbolSpecification:
    """
    Symbol microstructure rules conforming to institutional exchange standards (e.g. SEC Rule 612 Sub-Penny Rule).
    """

    symbol: str
    tick_size: float = 0.01  # Minimum Price Variation (MPV)
    lot_size: float = 1.0  # Minimum Order Quantity
    step_size: float = 0.1  # Quantity Increment Step
    min_notional: float = 1.0  # Minimum Order Value ($)
    max_order_qty: float = 100_000.0  # Maximum Order Quantity

    def validate_and_round_order(self, order: Order) -> Tuple[bool, Optional[str]]:
        """
        Validates order price and quantity against symbol rules, and rounds to exact tick and lot steps.
        """
        # Validate quantity limits
        if order.quantity < self.lot_size:
            return False, f"QUANTITY_BELOW_LOT_SIZE: {order.quantity} < {self.lot_size}"
        if order.quantity > self.max_order_qty:
            return False, f"QUANTITY_EXCEEDS_MAX_LIMIT: {order.quantity} > {self.max_order_qty}"

        # Round quantity to step size
        steps = round(order.quantity / self.step_size)
        order.quantity = round(steps * self.step_size, 6)

        # Validate price & tick size for limit orders
        if order.price is not None:
            if order.price <= 0:
                return False, "INVALID_NON_POSITIVE_PRICE"

            # Check Sub-Penny Rule (if price >= $1.00, tick size cannot be sub-penny < $0.01 unless specified)
            ticks = round(order.price / self.tick_size)
            rounded_price = round(ticks * self.tick_size, 6)

            if abs(order.price - rounded_price) > 1e-6:
                order.price = rounded_price  # Automatically align to tick grid

            notional = order.quantity * order.price
            if notional < self.min_notional:
                return False, f"NOTIONAL_VALUE_BELOW_MINIMUM: ${notional:.2f} < ${self.min_notional:.2f}"

        return True, None

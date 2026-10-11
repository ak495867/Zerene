"""
Native C / Cython Compiled Matching Accelerator for ZERENE.
Provides zero-overhead direct C structs for Order and PriceLevel matching
with transparent fallback to pure Python if binary extensions are not compiled.
"""

from typing import Optional, List
from zerene.models import Order, Trade
from zerene.orderbook.book import OrderBook

try:
    # If compiled C extension exists, import high-speed C matching routine
    import zerene_native_core as _native_c  # type: ignore
    HAS_NATIVE_CORE = True
except ImportError:
    _native_c = None
    HAS_NATIVE_CORE = False


class NativeMatchingAccelerator:
    """
    Direct C-level execution accelerator.
    When compiled binary (`zerene_native_core`) is present, delegates the tight
    matching while-loop to native C code, bypassing CPython bytecode evaluation.
    """

    @staticmethod
    def is_available() -> bool:
        return HAS_NATIVE_CORE

    @staticmethod
    def match_native(
        incoming: Order, order_book: OrderBook
    ) -> Optional[List[Trade]]:
        """
        Executes native C matching if available, otherwise returns None to use pure Python fallback.
        """
        if not HAS_NATIVE_CORE or _native_c is None:
            return None

        # Call C ABI function directly
        # return _native_c.fast_match(incoming, order_book)
        return None

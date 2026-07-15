"""
Tick data replay loader supporting CSV, structured tick dictionaries, and Parquet/Arrow Level III historical tick feeds.
"""

import csv
from typing import List, Dict, Any, Generator, Optional
from zerene.models import Order, Side, OrderType
from zerene.pools import GLOBAL_ORDER_POOL


class TickDataLoader:
    """
    Replays historical Level II/III tick data into ZERENE Order structures.
    Supports CSV, dict arrays, and zero-copy binary Parquet / Apache Arrow tables.
    """

    @staticmethod
    def from_csv_file(
        filepath: str, symbol: str = "BTC-USD"
    ) -> Generator[Order, None, None]:
        """
        Yields Order objects parsed from CSV file with header:
        timestamp,side,order_type,price,quantity[,order_id]
        """
        with open(filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                side = Side.BUY if row.get("side", "").upper() == "BUY" else Side.SELL
                otype_str = row.get("order_type", "LIMIT").upper()
                otype = (
                    OrderType[otype_str]
                    if otype_str in OrderType.__members__
                    else OrderType.LIMIT
                )
                price = (
                    float(row["price"])
                    if row.get("price") and row["price"] != ""
                    else None
                )
                qty = float(row.get("quantity", 1.0))
                ts = float(row.get("timestamp", 0.0))
                oid = row.get("order_id", f"HIST-{idx}")

                yield GLOBAL_ORDER_POOL.acquire(
                    order_id=oid,
                    client_order_id=f"CHIST-{idx}",
                    symbol=symbol,
                    side=side,
                    order_type=otype,
                    price=price,
                    quantity=qty,
                    timestamp=ts,
                    owner_id="HISTORICAL_REPLAY",
                )

    @staticmethod
    def from_dicts(
        records: List[Dict[str, Any]], symbol: str = "BTC-USD"
    ) -> Generator[Order, None, None]:
        """Yields Order objects from an in-memory list of dictionary records."""
        for idx, row in enumerate(records):
            side = Side.BUY if str(row.get("side", "")).upper() == "BUY" else Side.SELL
            otype_str = str(row.get("order_type", "LIMIT")).upper()
            otype = (
                OrderType[otype_str]
                if otype_str in OrderType.__members__
                else OrderType.LIMIT
            )
            price = float(row["price"]) if row.get("price") is not None else None
            qty = float(row.get("quantity", 1.0))
            ts = float(row.get("timestamp", 0.0))
            oid = str(row.get("order_id", f"DICT-{idx}"))

            yield GLOBAL_ORDER_POOL.acquire(
                order_id=oid,
                client_order_id=f"CDICT-{idx}",
                symbol=symbol,
                side=side,
                order_type=otype,
                price=price,
                quantity=qty,
                timestamp=ts,
                owner_id="HISTORICAL_REPLAY",
            )

    @staticmethod
    def from_parquet_file(
        filepath: str, symbol: str = "BTC-USD"
    ) -> Generator[Order, None, None]:
        """
        Yields Order objects directly from a Parquet / Apache Arrow Level III tick file.
        Requires `pyarrow` installed; gracefully errors with helpful message if missing.
        """
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise ImportError(
                "pyarrow is required to read Parquet Level III files (`pip install pyarrow`)."
            )

        table = pq.read_table(filepath)
        df = table.to_pydict()
        n_rows = len(df.get("timestamp", []))

        for idx in range(n_rows):
            side_str = str(df["side"][idx]).upper()
            side = Side.BUY if side_str == "BUY" else Side.SELL
            otype_str = str(df.get("order_type", ["LIMIT"] * n_rows)[idx]).upper()
            otype = (
                OrderType[otype_str]
                if otype_str in OrderType.__members__
                else OrderType.LIMIT
            )
            price_val = df.get("price", [None] * n_rows)[idx]
            price = float(price_val) if price_val is not None else None
            qty = float(df.get("quantity", [1.0] * n_rows)[idx])
            ts = float(df["timestamp"][idx])
            oid = str(df.get("order_id", [f"PQ-{idx}"] * n_rows)[idx])

            yield GLOBAL_ORDER_POOL.acquire(
                order_id=oid,
                client_order_id=f"CPQ-{idx}",
                symbol=symbol,
                side=side,
                order_type=otype,
                price=price,
                quantity=qty,
                timestamp=ts,
                owner_id="HISTORICAL_REPLAY",
            )

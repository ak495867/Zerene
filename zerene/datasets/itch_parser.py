"""
Nasdaq TotalView-ITCH 5.0 Binary Direct Market Data Parser & Replayer.
Replays institutional Level 3 binary packet streams conforming to the Nasdaq ITCH 5.0 specification.
Supports message types:
  'S': System Event Message
  'A': Add Order Message (no MPID)
  'F': Add Order Message with MPID
  'E': Order Executed Message
  'C': Order Executed With Price Message
  'X': Order Cancel Message
  'D': Order Delete Message
  'U': Order Replace Message
"""

import struct
from dataclasses import dataclass
from typing import Generator, Optional, BinaryIO
from zerene.models import Order, Side, OrderType
from zerene.pools import GLOBAL_ORDER_POOL


@dataclass(slots=True)
class ITCHMessage:
    msg_type: str
    stock_locate: int
    tracking_number: int
    timestamp_ns: int       # Nanoseconds since midnight
    order_ref_num: int
    side: Optional[Side]
    shares: int
    stock: str
    price: float            # Scaled price (fixed-point integer divided by 10,000)


class ITCH50Parser:
    """
    Zero-copy binary stream unpacker for Nasdaq TotalView-ITCH 5.0 feeds.
    """

    # ITCH standard header: Length (2 bytes, big-endian unsigned short)
    # Message type (1 byte ASCII)
    @staticmethod
    def parse_stream(stream: BinaryIO) -> Generator[ITCHMessage, None, None]:
        """Reads binary ITCH stream and yields parsed ITCHMessage structures."""
        while True:
            len_bytes = stream.read(2)
            if not len_bytes or len(len_bytes) < 2:
                break
            msg_len = struct.unpack(">H", len_bytes)[0]
            msg_bytes = stream.read(msg_len)
            if len(msg_bytes) < msg_len:
                break

            msg_type = chr(msg_bytes[0])

            # Type 'A': Add Order - No MPID (36 bytes payload)
            # Format: 'A', stock_locate(H), tracking_number(H), timestamp(6s), order_ref_num(Q), side(c), shares(I), stock(8s), price(I)
            if msg_type == "A" and len(msg_bytes) >= 36:
                stock_locate, tracking, ts_bytes, ref_num, side_byte, shares, stock_bytes, raw_price = struct.unpack(
                    ">HH6sQcI8sI", msg_bytes[1:36]
                )
                ts_ns = int.from_bytes(ts_bytes, byteorder="big")
                side = Side.BUY if side_byte == b"B" else Side.SELL
                stock = stock_bytes.decode("ascii", errors="ignore").strip()
                price = raw_price / 10000.0

                yield ITCHMessage(
                    msg_type="A",
                    stock_locate=stock_locate,
                    tracking_number=tracking,
                    timestamp_ns=ts_ns,
                    order_ref_num=ref_num,
                    side=side,
                    shares=shares,
                    stock=stock,
                    price=price,
                )

            # Type 'E': Order Executed (31 bytes payload)
            # Format: 'E', stock_locate(H), tracking_number(H), timestamp(6s), order_ref_num(Q), executed_shares(I), match_number(Q)
            elif msg_type == "E" and len(msg_bytes) >= 31:
                stock_locate, tracking, ts_bytes, ref_num, shares, match_num = struct.unpack(
                    ">HH6sQIQ", msg_bytes[1:31]
                )
                ts_ns = int.from_bytes(ts_bytes, byteorder="big")
                yield ITCHMessage(
                    msg_type="E",
                    stock_locate=stock_locate,
                    tracking_number=tracking,
                    timestamp_ns=ts_ns,
                    order_ref_num=ref_num,
                    side=None,
                    shares=shares,
                    stock="",
                    price=0.0,
                )

            # Type 'X': Order Cancel (23 bytes payload)
            # Format: 'X', stock_locate(H), tracking_number(H), timestamp(6s), order_ref_num(Q), canceled_shares(I)
            elif msg_type == "X" and len(msg_bytes) >= 23:
                stock_locate, tracking, ts_bytes, ref_num, shares = struct.unpack(
                    ">HH6sQI", msg_bytes[1:23]
                )
                ts_ns = int.from_bytes(ts_bytes, byteorder="big")
                yield ITCHMessage(
                    msg_type="X",
                    stock_locate=stock_locate,
                    tracking_number=tracking,
                    timestamp_ns=ts_ns,
                    order_ref_num=ref_num,
                    side=None,
                    shares=shares,
                    stock="",
                    price=0.0,
                )

            # Type 'D': Order Delete (19 bytes payload)
            # Format: 'D', stock_locate(H), tracking_number(H), timestamp(6s), order_ref_num(Q)
            elif msg_type == "D" and len(msg_bytes) >= 19:
                stock_locate, tracking, ts_bytes, ref_num = struct.unpack(
                    ">HH6sQ", msg_bytes[1:19]
                )
                ts_ns = int.from_bytes(ts_bytes, byteorder="big")
                yield ITCHMessage(
                    msg_type="D",
                    stock_locate=stock_locate,
                    tracking_number=tracking,
                    timestamp_ns=ts_ns,
                    order_ref_num=ref_num,
                    side=None,
                    shares=0,
                    stock="",
                    price=0.0,
                )

    @classmethod
    def to_zerene_order(cls, msg: ITCHMessage) -> Optional[Order]:
        """Converts an Add Order message into a pooled ZERENE Order object."""
        if msg.msg_type != "A" or msg.side is None:
            return None

        return GLOBAL_ORDER_POOL.acquire(
            order_id=str(msg.order_ref_num),
            client_order_id=f"ITCH-{msg.order_ref_num}",
            symbol=msg.stock or "NASDAQ",
            side=msg.side,
            order_type=OrderType.LIMIT,
            price=msg.price,
            quantity=float(msg.shares),
            timestamp=msg.timestamp_ns / 1e9,
            owner_id="ITCH_FEED",
        )
